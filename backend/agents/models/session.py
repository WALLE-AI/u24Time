"""
会话和消息模型
"""
from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin


class Session(Base, UUIDMixin, TimestampMixin):
    """
    会话模型 (Session)
    
    一个 Session 代表一次完整的用户交互会话，包含：
    - 多轮对话 (Conversation): 每轮 = 用户消息 + 工具调用 + 助手回复
    - 待办任务列表 (Todos)
    - 上传的文件 (Files)
    
    概念说明:
    - Session 是容器概念，用于组织和管理一次完整的交互过程
    - 每个 Session 包含多条 Message，这些 Message 按时间顺序构成多轮对话
    - 使用 ConversationHelper 可以将 Message 列表分组为 Conversation 轮次
    
    示例:
        Session "研究量子计算"
        ├── Conversation 1: "什么是量子计算?" → "量子计算是..."
        ├── Conversation 2: "搜索最新论文" → [工具调用] → "找到5篇论文"
        └── Conversation 3: "总结这些论文" → "总结如下..."
    """
    
    __tablename__ = "sessions"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    agent: Mapped[str] = mapped_column(String(50), default="build", nullable=False)  # build, chat, etc.
    status: Mapped[str] = mapped_column(
        String(20),
        default="active",
        nullable=False,
    )  # active, completed, aborted
    
    # 父会话 (用于分支)
    parent_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("sessions.id"))
    
    # 工作空间跟踪
    workspace_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("workspaces.id"))
    workspace_path: Mapped[str | None] = mapped_column(Text)  # 可空，支持没有配置工作空间的情况
    
    # 元数据
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict)
    
    # Token 统计
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    # 成本统计
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    
    # 压缩统计
    compaction_count: Mapped[int] = mapped_column(Integer, default=0)
    last_compaction_at: Mapped[str | None] = mapped_column(DateTime(timezone=True))
    
    # 关系
    user = relationship("User", back_populates="sessions")
    messages = relationship("Message", back_populates="session", lazy="dynamic", order_by="Message.created_at")
    todos = relationship("Todo", back_populates="session", lazy="dynamic")
    files = relationship("File", back_populates="session", lazy="dynamic")
    logs = relationship("SessionLog", back_populates="session", lazy="dynamic", order_by="SessionLog.created_at")


class Message(Base, UUIDMixin, TimestampMixin):
    """
    消息模型 (Message)
    
    单条消息，属于某个 Session。多条连续的 Message 构成一轮对话：
    
    对话轮次构成:
        1. role='user': 用户消息（对话轮次开始）
        2. role='tool': 工具调用结果（可选，可能有多条）
        3. role='assistant': 助手回复（对话轮次结束）
    
    注意:
    - Message 是单条消息的载体，不代表完整的对话轮次
    - 若需获取完整对话轮次，使用 ConversationHelper.get_conversations(session_id)
    - session_tools 工具返回的是 Message 列表，而非 Conversation 列表
    """
    
    __tablename__ = "messages"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant, system, tool
    content: Mapped[str | None] = mapped_column(Text)
    
    # 工具调用
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tool_call_id: Mapped[str | None] = mapped_column(String(100))
    
    # Token 统计
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    # 元数据
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, default=dict)
    
    # 归档和压缩
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    is_summary: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_message_ids: Mapped[list | None] = mapped_column(JSON)
    
    # 关系
    session = relationship("Session", back_populates="messages")


class Todo(Base, UUIDMixin, TimestampMixin):
    """待办任务模型"""
    
    __tablename__ = "todos"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("sessions.id"), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(100))  # Model-provided ID (e.g. "1", "task-01")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, in_progress, completed, cancelled
    order: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str | None] = mapped_column(Text)
    
    # 关系
    session = relationship("Session", back_populates="todos")
