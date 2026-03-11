"""
会话日志模型
"""
from sqlalchemy import ForeignKey, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
import json

from app.models.base import Base, TimestampMixin, UUIDMixin


class JSONEncodedDict(TypeDecorator):
    """JSON 编码字典类型，兼容 SQLite"""
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return json.dumps(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            return json.loads(value)
        return None


class SessionLog(Base, UUIDMixin, TimestampMixin):
    """会话执行日志模型"""
    
    __tablename__ = "session_logs"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    log_type: Mapped[str] = mapped_column(String(50), nullable=False)  # 'tool', 'step', 'terminal', 'info', 'error'
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)  # 'active', 'complete', 'error'
    tool_name: Mapped[str | None] = mapped_column(String(100))
    
    # 元数据（存储额外信息，如工具参数、返回值等）- 使用自定义类型兼容SQLite
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONEncodedDict, default=None)
    
    # 关系
    session = relationship("Session", back_populates="logs")
