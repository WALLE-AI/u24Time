# -*- coding: utf-8 -*-
import json
import logging
from typing import Any, Protocol, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from agents.tools.base import Tool, ToolContext

logger = logging.getLogger(__name__)

class ToolExecuteDecision:
    """å·¥å·é´æå¤å®ç»æ"""
    def __init__(self, allowed: bool, reason: str = ""):
        self.allowed = allowed
        self.reason = reason

class ToolPolicy(Protocol):
    """å·¥å·æéç­ç¥åè®®"""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        ...

class ToolPolicyPipeline:
    """åçº§é´æå®å¨ç®¡çº¿: Global -> Agent -> Subagent -> Sandbox"""
    def __init__(self, policies: Sequence[ToolPolicy]):
        self.policies = policies

    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        for p in self.policies:
            decision = p.evaluate(tool, args, ctx)
            if not decision.allowed:
                return decision
        return ToolExecuteDecision(True)

class WorkspaceGuardPolicy(ToolPolicy):
    """æä»¶è®¿é®ç»çæ¦æªå?""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        # åªæ£æ¥æ¶åæä»?ç®å½åæ°çå·¥å·ãæ ¹æ®çº¦å®æ£æ?path ç¸å³å³é®å­?        for k, v in args.items():
            if isinstance(v, str) and ("path" in k.lower() or "dir" in k.lower() or "file" in k.lower()):
                # é»æ­¢ .. éé¸åç»å¯¹è·¯å¾è¶æè®¿é® (å¼ºè¡éå¶å¨ä¸ä¸ªèæ?root ææåºéè¯?
                if ".." in v or v.startswith("/"):
                    return ToolExecuteDecision(False, f"WorkspaceGuard: Illegal path escape detected in arg '{k}': {v}")
        return ToolExecuteDecision(True)

class LoopDetectionPolicy(ToolPolicy):
    """æ­»å¾ªç¯ä¸æéçæ­ä¾¦æµ"""
    def evaluate(self, tool: 'Tool', args: dict[str, Any], ctx: 'ToolContext') -> ToolExecuteDecision:
        # ä¾èµ ctx._tool_error_history å­å¸
        if not hasattr(ctx, "_tool_error_history"):
            ctx._tool_error_history = {}
            
        history = ctx._tool_error_history.setdefault(tool.id, {})
        try:
            # ç®ååæ°åå¸?            args_hash = hash(json.dumps(args, sort_keys=True, ensure_ascii=False))
        except Exception:
            args_hash = hash(str(args))
            
        count = history.get(args_hash, 0)
        # è¿ç»­å¤±è´¥3æ¬¡åå³çæ­æ¦æ?        if count >= 3:
            return ToolExecuteDecision(False, f"LoopGuard: Tool '{tool.id}' repeatedly failed {count} times with identical args. Fused.")
            
        return ToolExecuteDecision(True)


# ================= å¨å±é»è®¤ç®¡çº¿ =================
DEFAULT_TOOL_PIPELINE = ToolPolicyPipeline([
    WorkspaceGuardPolicy(),
    LoopDetectionPolicy()
])
