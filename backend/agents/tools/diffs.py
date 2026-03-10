from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


class DiffsToolParams(BaseModel):
    before: Optional[str] = Field(None, description="Original text content.")
    after: Optional[str] = Field(None, description="Updated text content.")
    patch: Optional[str] = Field(None, description="Unified diff or patch text.")
    path: Optional[str] = Field(None, description="Display path for before/after input.")
    lang: Optional[str] = Field(None, description="Optional language override for before/after input.")
    title: Optional[str] = Field(None, description="Optional title for the rendered diff.")
    mode: Optional[str] = Field(None, description="Output mode: view, file, image, or both. Default: both.")
    theme: Optional[str] = Field(None, description="Viewer theme. Default: dark.")
    layout: Optional[str] = Field(None, description="Diff layout. Default: unified.")
    fileQuality: Optional[str] = Field(None, description="File quality preset: standard, hq, or print.")
    fileFormat: Optional[str] = Field(None, description="Rendered file format: png or pdf.")
    fileScale: Optional[float] = Field(None, ge=1.0, le=4.0)
    fileMaxWidth: Optional[int] = Field(None, ge=640, le=2400)
    expandUnchanged: Optional[bool] = None
    ttlSeconds: Optional[int] = Field(None, ge=1, le=21600)
    baseUrl: Optional[str] = None


class DiffsTool(Tool):
    @property
    def id(self) -> str:
        return "diffs"

    @property
    def description(self) -> str:
        return "Create a read-only diff viewer from before/after text or a unified patch."

    @property
    def parameters(self) -> Type[BaseModel]:
        return DiffsToolParams

    async def execute(self, args: DiffsToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
