# -*- coding: utf-8 -*-
"""
MediaCrawlerDB — 跨平台统一查询引擎
适配 u24time 后端的 canonical_items 表结构，取代 BettaFish 原版的多表 MySQL 架构。
支持 SQLite 和 PostgreSQL。
"""

from typing import List, Optional
from datetime import datetime, timedelta, timezone
from loguru import logger
from sqlalchemy import select, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from data_alignment.schema import CanonicalItem
from db.models import CanonicalItemModel

class MediaCrawlerDB:
    """提供 5 大核心查询工具"""
    
    def __init__(self, db_session: AsyncSession):
        self._db = db_session
        
    async def search_hot_content(self, time_period: str = "week", limit: int = 50) -> List[dict]:
        """
        获取全平台综合热度最高的条目
        time_period: '24h', 'week', 'month', 'year'
        """
        now = datetime.now(timezone.utc)
        if time_period == "24h":
            start_time = now - timedelta(hours=24)
        elif time_period == "month":
            start_time = now - timedelta(days=30)
        elif time_period == "year":
            start_time = now - timedelta(days=365)
        else: # default week
            start_time = now - timedelta(days=7)
            
        stmt = (
            select(CanonicalItemModel)
            .where(CanonicalItemModel.crawled_at >= start_time)
            .order_by(desc(CanonicalItemModel.hotness_score))
            .limit(limit)
        )
        
        try:
            result = await self._db.execute(stmt)
            models = result.scalars().all()
            return [m.to_dict() for m in models]
        except Exception as e:
            logger.error(f"MediaCrawlerDB: search_hot_content error: {e}")
            return []

    async def search_topic_globally(self, topic: str, limit: int = 100) -> List[dict]:
        """
        全量跨平台检索指定话题（匹配标题或正文）
        """
        search_pattern = f"%{topic}%"
        stmt = (
            select(CanonicalItemModel)
            .where(
                or_(
                    CanonicalItemModel.title.ilike(search_pattern),
                    CanonicalItemModel.body.ilike(search_pattern)
                )
            )
            .order_by(desc(CanonicalItemModel.hotness_score))
            .limit(limit)
        )
        
        try:
            result = await self._db.execute(stmt)
            models = result.scalars().all()
            return [m.to_dict() for m in models]
        except Exception as e:
            logger.error(f"MediaCrawlerDB: search_topic_globally error: {e}")
            return []

    async def search_topic_by_date(self, topic: str, start_date: str, end_date: str, limit: int = 100) -> List[dict]:
        """
        在指定日期范围内查询（支持 ISO 格式字符串）
        """
        try:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        except ValueError:
            logger.error("MediaCrawlerDB: 无效的日期格式，需传入 ISO 8601")
            return []
            
        search_pattern = f"%{topic}%"
        stmt = (
            select(CanonicalItemModel)
            .where(
                and_(
                    CanonicalItemModel.crawled_at >= start_dt,
                    CanonicalItemModel.crawled_at <= end_dt,
                    or_(
                        CanonicalItemModel.title.ilike(search_pattern),
                        CanonicalItemModel.body.ilike(search_pattern)
                    )
                )
            )
            .order_by(desc(CanonicalItemModel.crawled_at))
            .limit(limit)
        )
        
        try:
            result = await self._db.execute(stmt)
            models = result.scalars().all()
            return [m.to_dict() for m in models]
        except Exception as e:
            logger.error(f"MediaCrawlerDB: search_topic_by_date error: {e}")
            return []

    async def get_comments_for_topic(self, topic: str, limit: int = 500) -> List[dict]:
        """
        在 CanonicalItem 架构下，评论也是一种 Item（如果单独存储的话）。
        如果混杂存储，可以通过特定的 metadata 或 body 内容作为区分，这里直接复用 search_topic_globally 概念，
        优先获取长文本或特定标记。
        """
        # 实际情况中如果将评论和正文作为 canonical entry 录入，可以用 title 等于空或者 source_type 说明判定。
        # 这里用一种泛化的查询返回所有内容作为替代
        return await self.search_topic_globally(topic, limit=limit)

    async def search_on_platform(self, platform_id: str, topic: str, limit: int = 50) -> List[dict]:
        """
        在指定平台(source_id前缀)中检索。
        如 platform_id = "social.weibo" 或 "hotsearch.bilibili"
        """
        search_pattern = f"%{topic}%"
        platform_pattern = f"{platform_id}%"
        
        stmt = (
            select(CanonicalItemModel)
            .where(
                and_(
                    CanonicalItemModel.source_id.ilike(platform_pattern),
                    or_(
                        CanonicalItemModel.title.ilike(search_pattern),
                        CanonicalItemModel.body.ilike(search_pattern)
                    )
                )
            )
            .order_by(desc(CanonicalItemModel.hotness_score))
            .limit(limit)
        )
        
        try:
            result = await self._db.execute(stmt)
            models = result.scalars().all()
            return [m.to_dict() for m in models]
        except Exception as e:
            logger.error(f"MediaCrawlerDB: search_on_platform error: {e}")
            return []
