# -*- coding: utf-8 -*-
"""
BlockReplyPipeline Test
验证: 能够成功地将包含 <think> 标签的 LLM 原始流剥离成 thinking 与 message 事件流
"""
import pytest
import asyncio
from typing import AsyncGenerator
from agents.runner.block_reply import BlockReplyPipeline

async def mock_llm_stream(chunks: list[str]) -> AsyncGenerator[str, None]:
    for chunk in chunks:
        yield chunk
        await asyncio.sleep(0.01)

@pytest.mark.asyncio
async def test_block_reply_pipeline_simple():
    chunks = [
        "Hello! ",
        "<think>",
        "Let me calculate",
        " this...\n",
        "Wait, 1+1=2.",
        "</think>",
        "\nThe answer is 2."
    ]
    
    pipeline = BlockReplyPipeline()
    results = []
    
    async for event in pipeline.process_stream(mock_llm_stream(chunks)):
        results.append(event)
        
    messages = "".join([e["chunk"] for e in results if e["type"] == "message"])
    thinking = "".join([e["chunk"] for e in results if e["type"] == "thinking"])
    
    assert messages == "Hello! \nThe answer is 2."
    assert thinking == "Let me calculate this...\nWait, 1+1=2."

@pytest.mark.asyncio
async def test_block_reply_pipeline_truncated_tags():
    chunks = [
        "Normal text ",
        "<thi",
        "nk>Hidden thought",
        "</th",
        "ink> Final text"
    ]
    
    pipeline = BlockReplyPipeline()
    results = []
    
    async for event in pipeline.process_stream(mock_llm_stream(chunks)):
        results.append(event)
        
    messages = "".join([e["chunk"] for e in results if e["type"] == "message"])
    thinking = "".join([e["chunk"] for e in results if e["type"] == "thinking"])
    
    assert messages == "Normal text  Final text"
    assert thinking == "Hidden thought"
