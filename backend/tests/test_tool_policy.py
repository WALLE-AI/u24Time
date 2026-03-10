# -*- coding: utf-8 -*-
"""
Tool Policy Pipeline and WorkspaceGuard Test
验证: 恶意 Agent 尝试通过 ../ 逃逸路径被 Pipeline 拦截
"""
import pytest
import asyncio
from pydantic import BaseModel
from agents.tools.base import Tool, ToolContext, ToolResult
from agents.tools.policy import DEFAULT_TOOL_PIPELINE, ToolExecuteDecision

class FileParams(BaseModel):
    path: str
    content: str
    
class MockFileTool(Tool):
    @property
    def id(self) -> str: return "write_file"
    @property
    def description(self) -> str: return "Writes file to path"
    @property
    def parameters(self) -> type[BaseModel]: return FileParams
    @property
    def metadata(self) -> dict: return {"categories": ["file", "filesystem"]}
    
    async def execute(self, args: FileParams, ctx: ToolContext) -> ToolResult:
        # If execution reaches here, the path is written. We want to test blocks.
        return ToolResult(output="Success", title="File Written")

@pytest.fixture
def mock_ctx():
    return ToolContext(
        session_id="test_session",
        message_id="msg_1",
        agent="agent_1",
        user_id="user_1",
        directory="/safe/workspace"
    )

@pytest.mark.asyncio
async def test_workspace_guard_escape(mock_ctx):
    tool = MockFileTool()
    
    # 恶意的参数: 尝试跨越到 /etc/
    malicious_args = {"path": "../../etc/shadow", "content": "hacked"}
    
    decision = DEFAULT_TOOL_PIPELINE.evaluate(tool, malicious_args, mock_ctx)
    assert decision.allowed is False
    assert "Illegal path escape" in decision.reason

@pytest.mark.asyncio
async def test_workspace_guard_safe(mock_ctx):
    tool = MockFileTool()
    
    # 安全的参数: 当前目录
    safe_args = {"path": "logs/server.log", "content": "started"}
    
    decision = DEFAULT_TOOL_PIPELINE.evaluate(tool, safe_args, mock_ctx)
    assert decision.allowed is True

@pytest.mark.asyncio
async def test_loop_detection_fuse(mock_ctx):
    tool = MockFileTool()
    args = {"path": "test.txt", "content": "fail"}
    
    # Simulate first failure manually using empty try/except block behavior matching base.py
    for _ in range(3):
        # Base.py sets exactly this history hash on exception
        import json
        ah = hash(json.dumps(args, sort_keys=True, ensure_ascii=False))
        mock_ctx._tool_error_history = getattr(mock_ctx, "_tool_error_history", {})
        history = mock_ctx._tool_error_history.setdefault(tool.id, {})
        history[ah] = history.get(ah, 0) + 1
        
    decision = DEFAULT_TOOL_PIPELINE.evaluate(tool, args, mock_ctx)
    assert decision.allowed is False
    assert "repeatedly failed 3 times" in decision.reason
