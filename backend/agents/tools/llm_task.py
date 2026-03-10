from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


class LlmTaskToolParams(BaseModel):
    prompt: str = Field(description="Task instruction for the LLM.")
    input: Optional[Any] = Field(None, description="Optional input payload for the task.")
    schema_: Optional[Any] = Field(None, alias="schema", description="Optional JSON Schema to validate the returned JSON.")
    provider: Optional[str] = Field(None, description="Provider override.")
    model: Optional[str] = Field(None, description="Model id override.")
    authProfileId: Optional[str] = Field(None, description="Auth profile override.")
    temperature: Optional[float] = None
    maxTokens: Optional[int] = None
    timeoutMs: Optional[int] = None

    class Config:
        populate_by_name = True


class LlmTaskTool(Tool):
    @property
    def id(self) -> str:
        return "llm-task"

    @property
    def description(self) -> str:
        return "Run a generic JSON-only LLM task and return schema-validated JSON."

    @property
    def parameters(self) -> Type[BaseModel]:
        return LlmTaskToolParams

    async def execute(self, args: LlmTaskToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
