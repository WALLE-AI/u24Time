# -*- coding: utf-8 -*-
"""
Memory Collection Isolation Test
验证: 同一 Database 下不同的 collection 读写相互隔离
"""
import pytest
import os
import asyncio
from agents.memory import MemoryIndexManager, EmbeddingProvider

# Mock provider
class MockProvider(EmbeddingProvider):
    def __init__(self):
        super().__init__("mock")
    async def embed(self, texts: list[str]) -> list[list[float]]:
        # Return dummy 1536 dim vectors
        return [[0.1] * 1536 for _ in texts]
        
@pytest.mark.asyncio
async def test_collection_isolation(tmp_path):
    db_path = str(tmp_path / "test_memory.db")
    
    # Init manager
    mem = await MemoryIndexManager.create(
        db_path=db_path,
        provider=MockProvider(),
        half_life_days=0 # Disable decay for strict score matching
    )
    
    # Store in collection A
    await mem.store_analysis(
        topic="apples",
        content="Apples are red and sweet fruits.",
        collection="agentA_workspace1"
    )
    
    # Store in collection B
    await mem.store_analysis(
        topic="apples",
        content="Apples is a trillion dollar tech company.",
        collection="agentB_workspace2"
    )
    
    # Search in A should yield fruit
    res_a = await mem.search_history("apples", k=5, collection="agentA_workspace1")
    assert len(res_a) == 1
    assert "sweet fruits" in res_a[0].snippet
    
    # Search in B should yield company
    res_b = await mem.search_history("apples", k=5, collection="agentB_workspace2")
    assert len(res_b) == 1
    assert "tech company" in res_b[0].snippet
    
    await mem.close()
