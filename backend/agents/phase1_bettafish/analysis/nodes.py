# -*- coding: utf-8 -*-
import json
from loguru import logger
from typing import List
import httpx

from utils.llm_client import LLMClient
from agents.config import agents_settings
from .state import DeepSearchState, SearchResult

class BaseNode:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def execute(self, state: DeepSearchState) -> DeepSearchState:
        raise NotImplementedError

class SearchNode(BaseNode):
    """执行网络搜索获取初始资料节点"""
    async def execute(self, state: DeepSearchState) -> DeepSearchState:
        queries_to_run = state.current_queries if state.current_queries else [state.original_query]
        state.current_queries = [] # 清空已消费的查询词
        
        all_new_results = []
        for q in queries_to_run:
            logger.info(f"SearchNode: 正在抓取 '{q}'...")
            results = await self._search_external(q)
            all_new_results.extend(results)
            
        state.search_results.extend(all_new_results)
        return state
        
    async def _search_external(self, search_query: str) -> List[SearchResult]:
        if agents_settings.SEARCH_API_PROVIDER == "tavily" and agents_settings.SEARCH_API_KEY:
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
                    return [SearchResult(
                        title=r["title"], 
                        url=r["url"], 
                        content=r["content"],
                        score=r.get("score", 0.0)
                    ) for r in data.get("results", [])[:5]]
            except Exception as e:
                logger.error(f"SearchNode: 外部搜索失败: {e}")
                
        # Fallback Mock
        logger.info("SearchNode: 使用模拟搜索响应")
        return [SearchResult(title=f"关于 {search_query} 的最新报道", url="http://mock.url", content=f"根据现场发回的消息，{search_query} 产生了巨大反响。")]

class SentimentPerceptorNode(BaseNode):
    """轻量情感感知器节点: 对搜索到的新事实进行快速情感贴标"""
    async def execute(self, state: DeepSearchState) -> DeepSearchState:
        untagged = [r for r in state.search_results if r.sentiment is None]
        if not untagged:
            return state
            
        logger.info(f"SentimentPerceptor: 正在为 {len(untagged)} 条搜索结果分析情感基调...")
        prompt = "分析以下新闻段落的情感倾向。只能输出大写的类别：POS（正面）, NEG（负面）, NEU（中立）。不要多写字。\n\n"
        for r in untagged:
            # 在实际中这里可以是批量请求，或者小模型专有接口. 这里融合LLM
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(
                        f"{self._llm.base_url}/chat/completions",
                        headers={"Authorization": f"Bearer {self._llm.api_key}"},
                        json={
                            "model": self._llm.model,
                            "messages": [{"role": "user", "content": prompt + f"文本: {r.content[:200]}"}],
                            "temperature": 0.1,
                        }
                    )
                    data = response.json()
                    sentiment_str = data["choices"][0]["message"]["content"].strip().upper()
                    if "POS" in sentiment_str: r.sentiment = "POS"
                    elif "NEG" in sentiment_str: r.sentiment = "NEG"
                    else: r.sentiment = "NEU"
            except Exception as e:
                r.sentiment = "NEU"
        return state

class ReflectionNode(BaseNode):
    """反思节点：寻找缺口，提出后续搜索词，或标记查询完成"""
    async def execute(self, state: DeepSearchState) -> DeepSearchState:
        if state.reflections_count >= state.max_reflections:
            state.is_completed = True
            return state
            
        context = "\n".join([f"- [{r.sentiment or 'NEU'}] {r.title}: {r.content}" for r in state.search_results])
        
        prompt = (
            f"目标主题: '{state.original_query}'\n"
            f"现有资料及感情色彩基调:\n{context}\n\n"
            f"请仔细分析资料。如果资料已足够支撑全面综述，回复 '无需补充'。"
            f"如果存在关键缺失（例如缺少不同阵营的视角、伤亡人数不清、诱因不明），请提出 1 个新检索词汇组合（不超过15个字，不带引号）。"
        )
        
        try:
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
                reply = data["choices"][0]["message"]["content"].strip()
                
                if "无需补充" in reply:
                    state.is_completed = True
                else:
                    state.current_queries.append(reply)
                    state.reflections_count += 1
        except Exception as e:
            logger.error(f"ReflectionNode: 反思失败: {e}")
            state.is_completed = True
            
        return state

class OpinionNode(BaseNode):
    """观点生成/综述节点"""
    async def execute(self, state: DeepSearchState) -> DeepSearchState:
        logger.info("OpinionNode: 正在结合情感张力提炼最终综述...")
        context = "\n".join([f"[{r.sentiment or 'NEU'}] {r.content}" for r in state.search_results])
        
        prompt = (
            f"基于以下附带情感标签[POS/NEG/NEU]的检索资料，为事件 '{state.original_query}' 撰写一段高度凝练的新闻摘要综述。\n\n"
            f"资料:\n{context}\n\n"
            f"要求：\n"
            f"1. 融合正负面情绪的冲突感，客观陈述事实。\n"
            f"2. 语气专业克制，字数控制在 250 字左右。"
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}"},
                    json={
                        "model": self._llm.model,
                        "messages": [
                            {"role": "system", "content": "You are a senior objective news editor focusing on sentiment contrasts."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                    }
                )
                data = response.json()
                state.summarized_paragraph = data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"OpinionNode: 总结失败: {e}")
            state.summarized_paragraph = "暂时无法生成带情感分析的综述。"
        return state
