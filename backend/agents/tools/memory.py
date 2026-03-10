from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


def optional_string_enum(*args):
    """Placeholder for description representing enums"""
    return " | ".join(args)

# ----------------------------------------------------------------------------
# Memory Search Tool
# ----------------------------------------------------------------------------

class MemorySearchToolParams(BaseModel):
    query: str
    maxResults: Optional[int] = None
    minScore: Optional[float] = None


class MemorySearchTool(Tool):
    @property
    def id(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Mandatory recall step: semantically search MEMORY.md + memory/*.md"

    @property
    def parameters(self) -> Type[BaseModel]:
        return MemorySearchToolParams

    async def execute(self, args: MemorySearchToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Memory Get Tool
# ----------------------------------------------------------------------------

class MemoryGetToolParams(BaseModel):
    path: str
    from_: Optional[int] = Field(None, alias="from")
    lines: Optional[int] = None

    class Config:
        populate_by_name = True


class MemoryGetTool(Tool):
    @property
    def id(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Safe snippet read from MEMORY.md or memory/*.md with optional from/lines"

    @property
    def parameters(self) -> Type[BaseModel]:
        return MemoryGetToolParams

    async def execute(self, args: MemoryGetToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
