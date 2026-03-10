from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


def optional_string_enum(*args):
    """Placeholder for description representing enums"""
    return " | ".join(args)

# ----------------------------------------------------------------------------
# Sessions Spawn Tool
# ----------------------------------------------------------------------------

class AttachmentParams(BaseModel):
    name: str
    content: str
    encoding: Optional[str] = Field(None, description="utf8|base64")
    mimeType: Optional[str] = None

class AttachAsParams(BaseModel):
    mountPath: Optional[str] = None

class SessionsSpawnToolParams(BaseModel):
    task: str
    label: Optional[str] = None
    runtime: Optional[str] = Field(None, description="subagent|acp")
    agentId: Optional[str] = None
    model: Optional[str] = None
    thinking: Optional[str] = None
    cwd: Optional[str] = None
    runTimeoutSeconds: Optional[int] = Field(None, ge=0)
    timeoutSeconds: Optional[int] = Field(None, ge=0)
    thread: Optional[bool] = None
    mode: Optional[str] = Field(None, description="run|session")
    cleanup: Optional[str] = Field(None, description="delete|keep")
    sandbox: Optional[str] = Field(None, description="inherit|require")
    streamTo: Optional[str] = Field(None, description="parent")
    attachments: Optional[List[AttachmentParams]] = None
    attachAs: Optional[AttachAsParams] = None


class SessionsSpawnTool(Tool):
    @property
    def id(self) -> str:
        return "sessions_spawn"

    @property
    def description(self) -> str:
        return "Spawn an isolated session (runtime='subagent' or runtime='acp')."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SessionsSpawnToolParams

    async def execute(self, args: SessionsSpawnToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Sessions List Tool
# ----------------------------------------------------------------------------

class SessionsListToolParams(BaseModel):
    kinds: Optional[List[str]] = None
    limit: Optional[int] = Field(None, ge=1)
    activeMinutes: Optional[int] = Field(None, ge=1)
    messageLimit: Optional[int] = Field(None, ge=0)


class SessionsListTool(Tool):
    @property
    def id(self) -> str:
        return "sessions_list"

    @property
    def description(self) -> str:
        return "List sessions with optional filters and last messages."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SessionsListToolParams

    async def execute(self, args: SessionsListToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Sessions History Tool
# ----------------------------------------------------------------------------

class SessionsHistoryToolParams(BaseModel):
    sessionKey: str
    limit: Optional[int] = Field(None, ge=1)
    includeTools: Optional[bool] = None


class SessionsHistoryTool(Tool):
    @property
    def id(self) -> str:
        return "sessions_history"

    @property
    def description(self) -> str:
        return "Fetch message history for a session."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SessionsHistoryToolParams

    async def execute(self, args: SessionsHistoryToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Sessions Send Tool
# ----------------------------------------------------------------------------

class SessionsSendToolParams(BaseModel):
    sessionKey: Optional[str] = None
    label: Optional[str] = Field(None, min_length=1, max_length=100)
    agentId: Optional[str] = Field(None, min_length=1, max_length=64)
    message: str
    timeoutSeconds: Optional[int] = Field(None, ge=0)


class SessionsSendTool(Tool):
    @property
    def id(self) -> str:
        return "sessions_send"

    @property
    def description(self) -> str:
        return "Send a message into another session. Use sessionKey or label to identify the target."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SessionsSendToolParams

    async def execute(self, args: SessionsSendToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Subagents Tool
# ----------------------------------------------------------------------------

class SubagentsToolParams(BaseModel):
    action: Optional[str] = Field(None, description="list|kill|steer")
    target: Optional[str] = None
    message: Optional[str] = None
    recentMinutes: Optional[int] = Field(None, ge=1)


class SubagentsTool(Tool):
    @property
    def id(self) -> str:
        return "subagents"

    @property
    def description(self) -> str:
        return "List, kill, or steer spawned sub-agents for this requester session."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SubagentsToolParams

    async def execute(self, args: SubagentsToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Session Status Tool
# ----------------------------------------------------------------------------

class SessionStatusToolParams(BaseModel):
    sessionKey: Optional[str] = None
    model: Optional[str] = None


class SessionStatusTool(Tool):
    @property
    def id(self) -> str:
        return "session_status"

    @property
    def description(self) -> str:
        return "Show a /status-equivalent session status card. Optional: set per-session model override."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SessionStatusToolParams

    async def execute(self, args: SessionStatusToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Agents List Tool
# ----------------------------------------------------------------------------

class AgentsListToolParams(BaseModel):
    pass


class AgentsListTool(Tool):
    @property
    def id(self) -> str:
        return "agents_list"

    @property
    def description(self) -> str:
        return "List OpenClaw agent ids you can target with sessions_spawn."

    @property
    def parameters(self) -> Type[BaseModel]:
        return AgentsListToolParams

    async def execute(self, args: AgentsListToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")

