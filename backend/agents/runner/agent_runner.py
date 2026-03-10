import asyncio
import logging
import json
from typing import Callable, Any, Dict, Optional, List, AsyncGenerator

from utils.llm_client import LLMClient, TaskType
from agents.context_engine import ContextEngine, AgentMessage
from agents.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

class FollowupRunner:
    """
    生命周期队列与防抖 (Queue / Followup Policy)
    参照 OpenClaw PI AgentRunner: 自动入队工具回调与防重复点击触发
    """
    
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._is_running = False
        self._task: Optional[asyncio.Task] = None
        
    async def _worker(self, execute_cb: Callable, context: Dict[str, Any]):
        while True:
            try:
                # 等待请求
                req = await self._queue.get()
                
                try:
                    await execute_cb(req, context)
                except Exception as e:
                    logger.error(f"FollowupRunner: 执行回调失败 — {e}")
                finally:
                    self._queue.task_done()
                    
                # Auto-Compaction: 当一个请求（包括流式生成）完全结束时，统一触发上下文压实
                if context.get("ctx_engine"):
                    try:
                        compaction_res = await context["ctx_engine"].compact()
                        if compaction_res and getattr(compaction_res, "compacted", False):
                            logger.info(f"FollowupRunner: 后台统一压实完成 {compaction_res.tokens_before} -> {compaction_res.tokens_after}")
                    except Exception as e:
                        logger.warning(f"FollowupRunner: AutoCompaction 钩子执行失败 — {e}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"FollowupRunner: worker 遇到严重异常 — {e}")
                await asyncio.sleep(1) # 熔断保护

    def start(self, execute_cb: Callable, context: Dict[str, Any]):
        """启动长驻防抖队列"""
        if not self._is_running:
            self._is_running = True
            self._task = asyncio.create_task(self._worker(execute_cb, context))

    async def enqueue(self, payload: Any):
        """将事件推入执行队列"""
        await self._queue.put(payload)
        
    async def stop(self):
        """安全停止该 Worker 并取消排队的推演"""
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


class AgentRunner:
    """
    智能体推演核心 (Perception-Intelligence Runner)
    参照 OpenClaw PI Module: 负责 ReAct 循环、工具绑定与状态机跳转
    """

    def __init__(
        self,
        llm: LLMClient,
        context_engine: ContextEngine,
        tools: List[Tool] = None,
        max_iterations: int = 10
    ):
        self.llm = llm
        self.ctx_engine = context_engine
        self.tools = tools or []
        self.max_iterations = max_iterations
        self._tool_map = {t.id: t for t in self.tools}

    def _get_tool_schemas(self) -> List[dict]:
        """生成 OpenAI 函数定义列表"""
        return [t.to_openai_function() for t in self.tools]

    async def run(
        self,
        prompt: str,
        system_override: Optional[str] = None,
        tool_context: Optional[Dict[str, Any]] = None,
        stream_cb: Optional[Callable[[Dict[str, Any]], Any]] = None
    ) -> str:
        """
        同步/阻塞运行推演循环 (ReAct)
        
        Args:
            prompt: 用户输入
            system_override: 覆盖系统提示词
            tool_context: 传递给工具的上下文数据
            stream_cb: 事件回调 (thinking, tool_call, result, etc.)
        """
        # 1. 组装初始消息
        if prompt:
            await self.ctx_engine.ingest(AgentMessage(role="user", content=prompt))
        
        # 2. 准备工具上下文 (Sandbox / Session 信息)
        # 填充 ToolContext 所需的必填字段 (session_id, message_id, agent, user_id)
        t_ctx_data = {
            "session_id": self.ctx_engine.session_id if hasattr(self.ctx_engine, "session_id") else "default",
            "message_id": "init",
            "agent": "AgentRunner",
            "user_id": "default_user",
            **(tool_context or {})
        }
        t_ctx = ToolContext(**t_ctx_data)
        
        iteration = 0
        while iteration < self.max_iterations:
            iteration += 1
            
            # 3. 获取当前上下文并调用 LLM
            messages = [m.to_dict() for m in self.ctx_engine.messages]
            
            # 显式拼接 system prompt (如果 ctx_engine 没带的话)
            # 注意: ContextEngine 通常内部管理 system prompt
            
            logger.debug(f"AgentRunner: 迭代 {iteration}, 消息数 {len(messages)}")
            
            response = await self.llm.chat(
                messages=messages,
                tools=self._get_tool_schemas() if self.tools else None,
                task=TaskType.ANALYSIS
            )
            
            # 4. 判定响应类型
            if isinstance(response, str):
                # 纯文本回复，推演结束
                msg = AgentMessage(role="assistant", content=response)
                await self.ctx_engine.ingest(msg)
                
                if stream_cb:
                    await self._invoke_cb(stream_cb, {"type": "message", "content": response})
                
                return response
            
            elif isinstance(response, dict) and "tool_calls" in response:
                # 处理工具调用
                tool_calls = response["tool_calls"]
                assistant_content = response.get("content")
                
                # 记录助手意图
                assistant_msg = AgentMessage(
                    role="assistant", 
                    content=assistant_content,
                    tool_calls=tool_calls
                )
                await self.ctx_engine.ingest(assistant_msg)
                
                if stream_cb and assistant_content:
                    await self._invoke_cb(stream_cb, {"type": "thinking", "content": assistant_content})

                # 5. 顺序/并行执行工具
                for tc in tool_calls:
                    tc_id = tc["id"]
                    func = tc["function"]
                    t_name = func["name"]
                    t_args = func["arguments"]
                    
                    if stream_cb:
                        await self._invoke_cb(stream_cb, {"type": "tool_use", "name": t_name, "args": t_args})

                    # 解析参数
                    try:
                        args_dict = json.loads(t_args)
                    except Exception as e:
                        logger.error(f"AgentRunner: 解析参数失败 {t_name} — {e}")
                        await self.ctx_engine.ingest(AgentMessage(
                            role="tool", 
                            tool_call_id=tc_id, 
                            content=f"Error: Invalid JSON arguments - {str(e)}"
                        ))
                        continue

                    # 执行工具
                    if t_name not in self._tool_map:
                        res_content = f"Error: Tool '{t_name}' not found."
                    else:
                        tool = self._tool_map[t_name]
                        try:
                            # 统一调用 __call__ 入口 (包含验证、日志、策略)
                            t_res: ToolResult = await tool(args_dict, t_ctx)
                            res_content = str(t_res.output) if t_res.success else f"Error: {t_res.error}"
                        except Exception as e:
                            logger.error(f"AgentRunner: 工具执行异常 {t_name} — {e}")
                            res_content = f"Error: Internal execution error - {str(e)}"
                    
                    # 写入上下文
                    await self.ctx_engine.ingest(AgentMessage(
                        role="tool",
                        tool_call_id=tc_id,
                        content=res_content
                    ))
                    
                    if stream_cb:
                        await self._invoke_cb(stream_cb, {"type": "tool_result", "name": t_name, "content": res_content})
            
            else:
                # 未知响应
                logger.warning(f"AgentRunner: 收到未知响应格式 {response}")
                break
                
        logger.warning(f"AgentRunner: 达到最大迭代次数 {self.max_iterations}")
        return "Max iterations reached."

    async def _invoke_cb(self, cb: Callable, payload: dict):
        if asyncio.iscoroutinefunction(cb):
            await cb(payload)
        else:
            cb(payload)
