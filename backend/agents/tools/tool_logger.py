"""
工具执行日志记录器

记录工具执行的详细信息，包括：
- 执行开始和结束时间
- 输入参数和输出大小
- 错误和异常
- 会话、用户、智能体信息
"""
import logging
import time
from typing import Any, Optional
from datetime import datetime, timezone
import json

from agents.models.session_log import SessionLog
from sqlalchemy.orm import Session as DBSession

logger = logging.getLogger(__name__)


class ToolExecutionLogger:
    """工具执行日志记录器"""
    
    def __init__(self, db: Optional[DBSession] = None):
        """
        初始化日志记录器
        
        Args:
            db: 数据库会话（可选）
        """
        self.db = db
        self._start_time: Optional[float] = None
        self._tool_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._user_id: Optional[str] = None
        self._agent_id: Optional[str] = None
        self._message_id: Optional[str] = None
        self._args: Optional[dict] = None
    
    async def start_execution(
        self,
        tool_id: str,
        session_id: str,
        user_id: str,
        agent_id: str,
        message_id: str,
        args: dict[str, Any],
    ) -> None:
        """
        记录工具执行开始
        
        Args:
            tool_id: 工具 ID
            session_id: 会话 ID
            user_id: 用户 ID
            agent_id: 智能体 ID
            message_id: 消息 ID
            args: 输入参数
        """
        self._start_time = time.time()
        self._tool_id = tool_id
        self._session_id = session_id
        self._user_id = user_id
        self._agent_id = agent_id
        self._message_id = message_id
        self._args = args
        
        # 记录到标准日志
        logger.info(
            f"Tool execution started",
            extra={
                "tool_id": tool_id,
                "session_id": session_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "message_id": message_id,
                "args_keys": list(args.keys()) if args else [],
            }
        )
        
        # 记录到数据库（如果有数据库会话）
        if self.db:
            try:
                # 构建有意义的初始 content（展示正在运行的命令/参数）
                sanitized = self._sanitize_args(args)
                if "command" in sanitized:
                    start_content = f"$ {sanitized['command']}"
                elif "pattern" in sanitized:
                    start_content = f"$ {tool_id} {sanitized.get('pattern', '')}"
                elif "query" in sanitized:
                    start_content = f"$ {tool_id} {sanitized.get('query', '')}"
                else:
                    start_content = f"Running {tool_id}..."
                
                log_entry = SessionLog(
                    session_id=session_id,
                    log_type="tool",
                    title=f"Tool: {tool_id}",
                    content=start_content,
                    status="active",
                    tool_name=tool_id,
                    metadata_={
                        "user_id": user_id,
                        "agent_id": agent_id,
                        "message_id": message_id,
                        "start_time": datetime.now(timezone.utc).isoformat(),
                        "args": sanitized,
                    }
                )
                self.db.add(log_entry)
                await self.db.commit()
            except Exception as e:
                logger.error(f"Failed to write tool start log to database: {e}")
                await self.db.rollback()
    
    async def end_execution(
        self,
        success: bool,
        output: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        记录工具执行结束
        
        Args:
            success: 是否成功
            output: 输出内容
            error: 错误信息
            metadata: 额外元数据
        """
        if self._start_time is None:
            logger.warning("end_execution called without start_execution")
            return
        
        elapsed_time = time.time() - self._start_time
        output_size = len(output) if output else 0
        
        # 记录到标准日志
        log_data = {
            "tool_id": self._tool_id,
            "session_id": self._session_id,
            "user_id": self._user_id,
            "agent_id": self._agent_id,
            "message_id": self._message_id,
            "success": success,
            "elapsed_seconds": round(elapsed_time, 3),
            "output_size": output_size,
        }
        
        if error:
            log_data["error"] = error
            logger.error(f"Tool execution failed", extra=log_data)
        else:
            logger.info(f"Tool execution completed", extra=log_data)
        
        # 记录到数据库（如果有数据库会话）
        if self.db:
            try:
                status = "complete" if success else "error"
                
                # ✅ FIX: 将实际 output 存入 content（截断到 2000 字符保持 DB 效率）
                # 这修复了 AgentConsole 终端 tab 显示 log.content 为空的 bug
                MAX_CONTENT_SIZE = 2000
                if output:
                    content = output[:MAX_CONTENT_SIZE] + ("..." if len(output) > MAX_CONTENT_SIZE else "")
                elif error:
                    content = f"Error: {error}"
                else:
                    content = f"Tool '{self._tool_id}' execution completed"
                
                log_metadata = {
                    "user_id": self._user_id,
                    "agent_id": self._agent_id,
                    "message_id": self._message_id,
                    "start_time": datetime.fromtimestamp(self._start_time, tz=timezone.utc).isoformat(),
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "elapsed_seconds": round(elapsed_time, 3),
                    "output_size": output_size,
                    "success": success,
                }
                
                if error:
                    log_metadata["error"] = error
                
                if metadata:
                    log_metadata.update(metadata)
                
                log_entry = SessionLog(
                    session_id=self._session_id,
                    log_type="tool",
                    title=f"Tool: {self._tool_id}",
                    content=content,
                    status=status,
                    tool_name=self._tool_id,
                    metadata_=log_metadata,
                )
                self.db.add(log_entry)
                await self.db.commit()
            except Exception as e:
                logger.error(f"Failed to write tool end log to database: {e}")
                await self.db.rollback()
        
        # 重置状态
        self._start_time = None
        self._tool_id = None
        self._session_id = None
        self._user_id = None
        self._agent_id = None
        self._message_id = None
        self._args = None
    
    async def log_error(
        self,
        error: Exception,
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        记录工具执行错误
        
        Args:
            error: 异常对象
            context: 额外上下文信息
        """
        error_message = f"{type(error).__name__}: {str(error)}"
        
        # 记录到标准日志
        log_data = {
            "tool_id": self._tool_id,
            "session_id": self._session_id,
            "user_id": self._user_id,
            "agent_id": self._agent_id,
            "message_id": self._message_id,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
        
        if context:
            log_data.update(context)
        
        logger.exception(f"Tool execution error", extra=log_data)
        
        # 记录到数据库（如果有数据库会话）
        if self.db and self._session_id:
            try:
                log_metadata = {
                    "user_id": self._user_id,
                    "agent_id": self._agent_id,
                    "message_id": self._message_id,
                    "error_type": type(error).__name__,
                    "error_message": str(error),
                }
                
                if context:
                    log_metadata.update(context)
                
                log_entry = SessionLog(
                    session_id=self._session_id,
                    log_type="error",
                    title=f"Tool Error: {self._tool_id}",
                    content=error_message,
                    status="error",
                    tool_name=self._tool_id,
                    metadata_=log_metadata,
                )
                self.db.add(log_entry)
                await self.db.commit()
            except Exception as e:
                logger.error(f"Failed to write error log to database: {e}")
                await self.db.rollback()
    
    @staticmethod
    def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
        """
        清理参数，移除敏感信息
        
        Args:
            args: 原始参数
            
        Returns:
            清理后的参数
        """
        sanitized = {}
        sensitive_keys = {"password", "token", "api_key", "secret", "credential"}
        
        for key, value in args.items():
            # 检查是否是敏感键
            if any(sensitive in key.lower() for sensitive in sensitive_keys):
                sanitized[key] = "[REDACTED]"
            elif isinstance(value, str) and len(value) > 1000:
                # 截断过长的字符串
                sanitized[key] = value[:1000] + "... [truncated]"
            elif isinstance(value, (dict, list)):
                # 转换为 JSON 字符串（限制长度）
                try:
                    json_str = json.dumps(value)
                    if len(json_str) > 1000:
                        sanitized[key] = json_str[:1000] + "... [truncated]"
                    else:
                        sanitized[key] = value
                except:
                    sanitized[key] = str(value)[:1000]
            else:
                sanitized[key] = value
        
        return sanitized


# 全局日志记录器实例（用于无数据库场景）
_global_logger = ToolExecutionLogger()


def get_tool_logger(db: Optional[DBSession] = None) -> ToolExecutionLogger:
    """
    获取工具日志记录器
    
    Args:
        db: 数据库会话（可选）
        
    Returns:
        工具日志记录器实例
    """
    if db:
        return ToolExecutionLogger(db)
    return _global_logger
