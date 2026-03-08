# -*- coding: utf-8 -*-
"""
InsightAgent — 社媒侧数据挖掘 Agent
整合 MediaCrawlerDB + SentimentAnalyzer 进行平台视角洞察
"""

from typing import List, Callable, Optional
from loguru import logger
from pydantic import BaseModel

from utils.llm_client import LLMClient
from data_alignment.schema import CanonicalItem

class AgentReport(BaseModel):
    source: str
    paragraph: str

class InsightAgent:
    """
    负责深挖社交媒体侧的结构化特征: 热度分、评论情感分类
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def run(self, query: str, items: List[CanonicalItem], broadcast_cb: Optional[Callable] = None) -> AgentReport:
        logger.info(f"InsightAgent: 开始分析 '{query}' 的社交网络数据 ({len(items)} 条数据)...")
        
        # 1. 提炼情绪和热度分布
        insight_context = self._aggregate_meta(items)
        
        # 2. 生成洞见段落
        paragraph = await self._summarize(query, insight_context)
        
        if broadcast_cb:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(broadcast_cb):
                    await broadcast_cb("INSIGHT", paragraph)
                else:
                    broadcast_cb("INSIGHT", paragraph)
            except Exception as e:
                logger.error(f"InsightAgent: 无法广播消息 - {e}")
                
        return AgentReport(source="insight", paragraph=paragraph)
        
    def _aggregate_meta(self, items: List[CanonicalItem]) -> str:
        """从相关 CanonicalItem 中提取情感和热度分布特征"""
        if not items:
            return "社交媒体数据库中没有相关的贴文记录。"
            
        total = len(items)
        hot = sum(1 for i in items if i.hotness_score > 50.0)
        
        # 简化版情感分类统计
        pos, neg, neu = 0, 0, 0
        for i in items:
            if i.sentiment is None:
                neu += 1
            elif i.sentiment > 0.2:
                pos += 1
            elif i.sentiment < -0.2:
                neg += 1
            else:
                neu += 1
                
        # 统计主力平台
        platforms = {}
        for i in items:
            if i.source_id.startswith("social."):
                plat = i.source_id.split(".")[1]
            elif i.source_id.startswith("hotsearch."):
                plat = i.source_id.split(".")[1]
            else:
                plat = "other"
            platforms[plat] = platforms.get(plat, 0) + 1
            
        top_platform = max(platforms.items(), key=lambda x: x[1])[0] if platforms else "未知"
                
        return (
            f"网民画像:\n"
            f"- 样本总数: {total} 条讨论\n"
            f"- 高热讨论(热度>50): {hot} 条\n"
            f"- 情绪倾向: 正向 {pos} 条 | 负向 {neg} 条 | 中性或未评估 {neu} 条\n"
            f"- 核心发酵平台: {top_platform} (占 {platforms.get(top_platform, 0)} 条)\n"
        )
        
    async def _summarize(self, query: str, context: str) -> str:
        """基于社交媒体统计数据进行洞察"""
        prompt = (
            f"目标主题: '{query}'\n"
            f"社媒统计摘要:\n{context}\n\n"
            f"请以【Insight 社交媒体洞察员】的口吻，分析网民对该事件的情绪焦点及传播热度。"
            f"请从数据事实出发，言辞锐利，说明事件的扩散效应和潜在导向。\n"
            f"字数控制在 150 字左右。"
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
                            {"role": "system", "content": "You are a Social Insight Data Analyst Agent."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                    }
                )
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"InsightAgent: 总结失败: {e}")
            return "统计洞察受阻。"
