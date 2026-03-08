# -*- coding: utf-8 -*-
"""
BettaFish Pipeline — 核心事件分析编排引擎
负责将话题提取、爬虫、多 Agent 分析、论坛机制串联为端到端工作流。
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Callable
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from utils.llm_client import LLMClient
from crawler_engine.engine import CrawlerEngine

# 模块引入
from agents.phase1_bettafish.crawlers.topic_extractor import TopicExtractor
from agents.phase1_bettafish.crawlers.social_crawler import SocialCrawler
from agents.phase1_bettafish.alignment.media_db import MediaCrawlerDB
from agents.phase1_bettafish.sentiment.analyzer import SentimentAnalyzer
from agents.phase1_bettafish.analysis.query_agent import QueryAgent
from agents.phase1_bettafish.analysis.insight_agent import InsightAgent
from agents.phase1_bettafish.analysis.media_agent import MediaAgent
from agents.phase1_bettafish.forum.monitor import ForumMonitor

class BettaFishPipeline:
    def __init__(self, db_session: AsyncSession, llm: LLMClient):
        self._db = db_session
        self._llm = llm
        
        # 基础设施依赖
        self._crawler_engine = CrawlerEngine()
        
        # 阶段组件
        self._extractor = TopicExtractor(self._crawler_engine, llm)
        self._crawler = SocialCrawler()
        self._media_db = MediaCrawlerDB(db_session)
        self._sentiment = SentimentAnalyzer()
        
        # 分析 Agent
        self._query_agent = QueryAgent(llm)
        self._insight_agent = InsightAgent(llm)
        self._media_agent = MediaAgent(llm)
        
    async def get_latest_topics(self) -> List[str]:
        """快捷提取当前的话题列表"""
        return await self._extractor.run(count=20)
        
    async def run_end_to_end(
        self, 
        query: str, 
        platforms: List[str], 
        max_reflections: int = 2,
        forum_monitor: Optional[ForumMonitor] = None
    ) -> dict:
        """
        端到端运行 BettaFish 流程
        如果提供了 forum_monitor，则各 Agent 并发执行并向其投递消息广播
        """
        logger.info(f"BettaFishPipeline: 开始执行端到端分析 '{query}'")
        self._query_agent.MAX_REFLECTIONS = max_reflections
        
        # Step 1: （可选）即时深度爬虫
        # await self._crawler.crawl_all([query], platforms)
        
        # Step 2: 检索数据库中的相关 Canonical Items
        logger.info("BettaFishPipeline: 检索本地关联内容...")
        items = await self._media_db.search_topic_globally(query, limit=50)
        
        # Step 3: 进行情感标注 (仅分析需要用到的字段)
        logger.info("BettaFishPipeline: 进行大批量文本情感分析...")
        from data_alignment.schema import CanonicalItem
        # 将 dict 转换回对象方便处理
        obj_items = [CanonicalItem(**item) for item in items]
        analyzed_items = await self._sentiment.analyze_canonical_items(obj_items)
        
        # 广播函数闭包
        async def broadcast(source, content):
            if forum_monitor:
                await forum_monitor.submit(source, content)
                
        # Step 4: 并行启动三驾马车进行专题分析
        logger.info("BettaFishPipeline: 并行启动分析引擎 (Query, Insight, Media)...")
        tasks = [
            self._query_agent.run(query, broadcast_cb=broadcast),
            self._insight_agent.run(query, analyzed_items, broadcast_cb=broadcast),
            self._media_agent.run(query, analyzed_items, broadcast_cb=broadcast)
        ]
        
        reports = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理可能的异常
        final_reports = {}
        for idx, task_name in enumerate(["query", "insight", "media"]):
            res = reports[idx]
            if isinstance(res, Exception):
                logger.error(f"BettaFishPipeline: Agent {task_name} 失败: {res}")
                final_reports[task_name] = f"分析过程中发生错误: {res}"
            else:
                final_reports[task_name] = res.paragraph
                
        # 返回总结合成的输出
        return {
            "query": query,
            "status": "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "reports": final_reports
        }
