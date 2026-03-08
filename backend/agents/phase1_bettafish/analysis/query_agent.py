# -*- coding: utf-8 -*-
"""
QueryEngine 事件分析 Agent
并行外部搜索 + 最多2轮反思机制
复用 utils/llm_client.py 
"""

import json
from typing import List, Callable, Optional
from loguru import logger
from pydantic import BaseModel

from utils.llm_client import LLMClient
from agents.config import agents_settings

class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = 0.0

class AgentReport(BaseModel):
    source: str
    paragraph: str

class QueryAgent:
    """
    负责基于关键词执行外部搜索引擎检索并进行总结分析
    """
    MAX_REFLECTIONS = 2
    
    def __init__(self, llm: LLMClient):
        self._llm = llm
        
    async def run(self, query: str, broadcast_cb: Optional[Callable] = None) -> AgentReport:
        """
        完整执行：搜索 → 反思×N → 输出 paragraph
        """
        logger.info(f"QueryAgent: 开始分析 '{query}'")
        
        # Node 1: 初步搜索
        results = await self._search(query)
        
        # Node 2: 结构化整理
        formatted = self._format(results)
        
        # Node 3: 反思分析 (最多 N 轮)
        for i in range(self.MAX_REFLECTIONS):
            logger.info(f"QueryAgent: 正在进行第 {i+1} 轮反思 '{query}'")
            gaps = await self._reflect(query, formatted)
            
            if not gaps or gaps.strip() == "无需补充":
                logger.info(f"QueryAgent: 摘要信息充足，无需补充。")
                break
                
            extra_results = await self._search(gaps)
            formatted = self._format(results + extra_results)
            
        # Node 4: 产生结论摘要
        paragraph = await self._summarize(query, formatted)
        
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
        
    async def _search(self, search_query: str) -> List[SearchResult]:
        """
        通过第三方 API（Tavily、DuckDuckGo 等）获取外部搜索结果
        暂时模拟，实际通过 HTTPX 请求 tavily 接口
        """
        if agents_settings.SEARCH_API_PROVIDER == "tavily" and agents_settings.SEARCH_API_KEY:
            # 真实请求 Tavily
            import httpx
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={
                            "api_key": agents_settings.SEARCH_API_KEY,
                            "query": search_query,
                            "search_depth": "advanced",
                            "include_answer": True
                        }
                    )
                    data = resp.json()
                    results = []
                    for r in data.get("results", [])[:5]:
                        results.append(SearchResult(
                            title=r["title"], 
                            url=r["url"], 
                            content=r["content"],
                            score=r.get("score", 0.0)
                        ))
                    return results
            except Exception as e:
                logger.error(f"QueryAgent: 外部搜索失败: {e}")
                
        # Fallback 模拟数据
        logger.info("QueryAgent: 使用模拟 Search 响应 (无 SEARCH_API_KEY 组合)")
        return [
            SearchResult(title=f"关于 {search_query} 的最新报道", url="http://mock.url", content=f"根据现场发回的消息，{search_query} 产生了巨大反响。")
        ]
        
    def _format(self, results: List[SearchResult]) -> str:
        """格式化搜索结果为上下文段落"""
        if not results:
            return "未找到相关信息。"
        lines = []
        for idx, r in enumerate(results):
            lines.append(f"[{idx+1}] {r.title}\n链接: {r.url}\n内容: {r.content}\n")
        return "\n".join(lines)
        
    async def _reflect(self, origin_query: str, current_context: str) -> str:
        """找信息缺口并提出新的查询词"""
        prompt = (
            f"目标主题: '{origin_query}'\n"
            f"现有资料:\n{current_context}\n\n"
            f"请仔细分析现有资料，指出是否存在关键信息缺失。如果资料已经可以支撑一份关于 '{origin_query}' 的完整综述，请仅回复 '无需补充'。"
            f"如果有关键事实缺失，请提出 1 个具体的简短检索词组用于进一步搜索（不超过 10 个字，不带引号）。"
        )
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}"},
                    json={
                        "model": self._llm.model,
                        "messages": [
                            {"role": "system", "content": "You analyze data gaps and output short search queries or exact words '无需补充'."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.2,
                    }
                )
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"QueryAgent 反思失败: {e}")
            return "无需补充"
            
    async def _summarize(self, query: str, context: str) -> str:
        """最终的段落总结"""
        prompt = (
            f"请基于以下检索资料，为事件 '{query}' 撰写一段高度凝练的新闻摘要综述。\n\n"
            f"资料:\n{context}\n\n"
            f"要求语气客观，条理清晰，字数控制在 250 字左右。"
        )
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}"},
                    json={
                        "model": self._llm.model,
                        "messages": [
                            {"role": "system", "content": "You are a senior news editor."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                    }
                )
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"QueryAgent 总结失败: {e}")
            return "暂时无法生成总结。"
