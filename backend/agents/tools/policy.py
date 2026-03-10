# -*- coding: utf-8 -*-
import json
import logging
from typing import Any, Protocol, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.tools.base import Tool, ToolContext

logger = logging.getLogger(__name__)

class ToolExecuteDecision:
    """工具鉴权判定结果"""
    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

class ToolPolicy(Protocol):
    """工具权限策略协议"""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        ...

class ToolPolicyPipeline:
    """四级鉴权安全管线: Global -> Agent -> Subagent -> Sandbox"""
    def __init__(self, policies: Sequence[ToolPolicy]):
        self.policies = policies

    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        for p in self.policies:
            decision = p.evaluate(tool, args, ctx)
            if not decision.allowed:
                return decision
        return ToolExecuteDecision(True)

class WorkspaceGuardPolicy(ToolPolicy):
    """文件访问结界拦截器"""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        # 只检查涉及文件/目录参数的工具。根据约定检查 path 相关关键字
        for k, v in args.items():
            if isinstance(v, str) and ("path" in k.lower() or "dir" in k.lower() or "file" in k.lower()):
                # 阻止 .. 逃逸和绝对路径越权访问 (强行限制在一个虚拟 root 或抛出错误)
                if ".." in v or v.startswith("/"):
                    return ToolExecuteDecision(False, f"WorkspaceGuard: Illegal path escape detected in arg '{k}': {v}")
        return ToolExecuteDecision(True)

class LoopDetectionPolicy(ToolPolicy):
    """死循环与故障熔断侦测"""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        # 依赖 ctx._tool_error_history 字典
        if not hasattr(ctx, "_tool_error_history"):
            ctx._tool_error_history = {}
            
        history = ctx._tool_error_history.setdefault(tool.id, {})
        try:
            # 简化参数哈希
            args_hash = hash(json.dumps(args, sort_keys=True, ensure_ascii=False))
        except Exception:
            args_hash = hash(str(args))
            
        count = history.get(args_hash, 0)
        # 连续失败3次后即熔断拦截
        if count >= 3:
            return ToolExecuteDecision(False, f"LoopGuard: Tool '{tool.id}' repeatedly failed {count} times with identical args. Fused.")
            
        return ToolExecuteDecision(True)


# ================= 全局默认管线 =================
DEFAULT_TOOL_PIPELINE = ToolPolicyPipeline([WorkspaceGuardPolicy(),LoopDetectionPolicy()])