# -*- coding: utf-8 -*-
"""
QueryEngine 事件分析 Agent (Node-based Refactored)
状态机执行流：初步搜索 -> 情感感知标签 -> 反思缺口与重搜(循环) -> 聚类观点综述
复用 utils/llm_client.py 
"""

import json
from typing import List, Callable, Optional
from loguru import logger
from pydantic import BaseModel

from utils.llm_client import LLMClient
from agents.config import agents_settings

from .state import DeepSearchState
from .nodes import SearchNode, SentimentPerceptorNode, ReflectionNode, OpinionNode

class AgentReport(BaseModel):
    source: str
    paragraph: str

class QueryAgent:
    """
    负责基于关键词执行外部搜索引擎检索并进行总结分析
    融合了轻量级情感感知器和节点化状态机
    """
    MAX_REFLECTIONS = 2
    
    def __init__(self, llm: LLMClient):
        self._llm = llm
        
        # 初始化工作流节点
        self.search_node = SearchNode(llm)
        self.sentiment_node = SentimentPerceptorNode(llm)
        self.reflection_node = ReflectionNode(llm)
        self.opinion_node = OpinionNode(llm)
        
    async def run(self, query: str, broadcast_cb: Optional[Callable] = None) -> AgentReport:
        """
        状态机执行流：Search -> Sentiment -> Reflection (Loop) -> Opinion
        """
        logger.info(f"QueryAgent: 开始分析 '{query}' (State-Node 模式)")
        
        # 1. 初始状态
        state = DeepSearchState(
            original_query=query,
            current_queries=[query],
            max_reflections=self.MAX_REFLECTIONS
        )
        
        # 2. 图遍历/状态机执行
        while not state.is_completed:
            # 搜索与感知
            state = await self.search_node.execute(state)
            state = await self.sentiment_node.execute(state)
            
            # 广播中间进度
            if broadcast_cb:
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(broadcast_cb):
                        await broadcast_cb("QUERY_THINKING", f"已获取 {len(state.search_results)} 条带情感标记的线索进行分析...")
                    else:
                        broadcast_cb("QUERY_THINKING", f"已获取 {len(state.search_results)} 条带情感标记的线索进行分析...")
                except Exception:
                    pass
                    
            # 反思缺口
            state = await self.reflection_node.execute(state)
            
        # 3. 最终观点综述
        state = await self.opinion_node.execute(state)
        
        paragraph = state.summarized_paragraph
        
        # 4. 广播最终结果
        if broadcast_cb:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(broadcast_cb):
                    await broadcast_cb("QUERY", paragraph)
                else:
                    broadcast_cb("QUERY", paragraph)
            except Exception as e:
                logger.error(f"QueryAgent: 无法广播消息 - {e}")
                
        return AgentReport(source="query", paragraph=paragraph)
