from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult

# ----------------------------------------------------------------------------
# Exec Tool
# ----------------------------------------------------------------------------

class ExecToolParams(BaseModel):
    command: str = Field(description="Shell command to execute")
    workdir: Optional[str] = Field(None, description="Working directory (defaults to cwd)")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    yieldMs: Optional[int] = Field(None, description="Milliseconds to wait before backgrounding (default 10000)")
    background: Optional[bool] = Field(None, description="Run in background immediately")
    timeout: Optional[int] = Field(None, description="Timeout in seconds (optional, kills process on expiry)")
    pty: Optional[bool] = Field(None, description="Run in a pseudo-terminal (PTY) when available (TTY-required CLIs, coding agents)")
    elevated: Optional[bool] = Field(None, description="Run on the host with elevated permissions (if allowed)")
    host: Optional[str] = Field(None, description="Exec host (sandbox|gateway|node)")
    security: Optional[str] = Field(None, description="Exec security mode (deny|allowlist|full)")
    ask: Optional[str] = Field(None, description="Exec ask mode (off|on-miss|always)")
    node: Optional[str] = Field(None, description="Node id/name for host=node")


class ExecTool(Tool):
    @property
    def id(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute bash commands in a sandbox or host environment."

    @property
    def parameters(self) -> Type[BaseModel]:
        return ExecToolParams

    async def execute(self, args: ExecToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Process Tool
# ----------------------------------------------------------------------------

class ProcessToolParams(BaseModel):
    action: str = Field(description="Process action (list|poll|log|write|send-keys|submit|paste|kill|clear|remove)")
    sessionId: Optional[str] = Field(None, description="Session id for actions other than list")
    data: Optional[str] = Field(None, description="Data to write for write")
    keys: Optional[List[str]] = Field(None, description="Key tokens to send for send-keys")
    hex: Optional[List[str]] = Field(None, description="Hex bytes to send for send-keys")
    literal: Optional[str] = Field(None, description="Literal string for send-keys")
    text: Optional[str] = Field(None, description="Text to paste for paste")
    bracketed: Optional[bool] = Field(None, description="Wrap paste in bracketed mode")
    eof: Optional[bool] = Field(None, description="Close stdin after write")
    offset: Optional[int] = Field(None, description="Log offset")
    limit: Optional[int] = Field(None, description="Log length")
    timeout: Optional[int] = Field(None, ge=0, description="For poll: wait up to this many milliseconds before returning")


class ProcessTool(Tool):
    @property
    def id(self) -> str:
        return "process"

    @property
    def description(self) -> str:
        return "Manage running exec sessions: list, poll, log, write, send-keys, submit, paste, kill."

    @property
    def parameters(self) -> Type[BaseModel]:
        return ProcessToolParams

    async def execute(self, args: ProcessToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
