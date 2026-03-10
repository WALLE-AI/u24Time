from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


class LobsterToolParams(BaseModel):
    action: str = Field(description="run|resume")
    pipeline: Optional[str] = None
    argsJson: Optional[str] = None
    token: Optional[str] = None
    approve: Optional[bool] = None
    cwd: Optional[str] = Field(None, description="Relative working directory.")
    timeoutMs: Optional[int] = None
    maxStdoutBytes: Optional[int] = None


class LobsterTool(Tool):
    @property
    def id(self) -> str:
        return "lobster"

    @property
    def description(self) -> str:
        return "Run Lobster pipelines as a local-first workflow runtime."

    @property
    def parameters(self) -> Type[BaseModel]:
        return LobsterToolParams

    async def execute(self, args: LobsterToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
