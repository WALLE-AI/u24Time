# -*- coding: utf-8 -*-
"""
AlignmentPipeline — 数据对齐主管道

接收原始数据，根据 source_id 选择对应 Normalizer，
输出 CanonicalItem 列表，并写入数据库。
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

from loguru import logger

from data_alignment.schema import CanonicalItem, SourceType
from data_alignment.normalizers.social_normalizer import SocialNormalizer
from data_alignment.normalizers.news_normalizer import NewsNormalizer
from data_alignment.normalizers.geo_event_normalizer import GeoEventNormalizer
from data_alignment.normalizers.combined_normalizers import (
    MilitaryNormalizer,
    MarketNormalizer,
    CyberNormalizer,
)
from data_alignment.normalizers.hotsearch_normalizer import HotSearchNormalizer
from data_alignment.deduplicator import Deduplicator


class AlignmentPipeline:
    """
    数据对齐管线。

    用法:
        pipeline = AlignmentPipeline()
        items = pipeline.align("social.bilibili", raw_rows, meta={"platform": "bilibili"})
    """

    def __init__(self):
        self._social = SocialNormalizer()
        self._news = NewsNormalizer()
        self._geo = GeoEventNormalizer()
        self._military = MilitaryNormalizer()
        self._market = MarketNormalizer()
        self._cyber = CyberNormalizer()
        self._hotsearch = HotSearchNormalizer()
        self._dedup = Deduplicator()

        # SSE 进度回调（可选注入）
        self._progress_cb: Optional[Callable[[dict], None]] = None

    def set_progress_callback(self, cb: Callable[[dict], None]):
        """注入 SSE 进度推送回调"""
        self._progress_cb = cb

    def _emit(self, event: dict):
        if self._progress_cb:
            try:
                self._progress_cb(event)
            except Exception:
                pass

    def align(
        self,
        source_id: str,
        raw_data: list[dict] | dict,
        meta: Optional[dict] = None,
    ) -> list[CanonicalItem]:
        """
        对齐数据。

        Args:
            source_id: 数据源注册 ID，如 "social.bilibili"、"geo.acled"
            raw_data: 原始数据列表（或单个字典）
            meta: 额外元数据（平台名、feed 分类等）
        Returns:
            规范化并去重后的 CanonicalItem 列表
        """
        if isinstance(raw_data, dict):
            raw_data = [raw_data]

        meta = meta or {}
        items: list[CanonicalItem] = []

        self._emit({"event": "align_start", "source_id": source_id, "total": len(raw_data)})

        try:
            items = self._dispatch(source_id, raw_data, meta)
        except Exception as e:
            logger.error(f"AlignmentPipeline: dispatch 失败 source={source_id} err={e}")
            self._emit({"event": "align_error", "source_id": source_id, "error": str(e)})
            return []

        # 去重
        before = len(items)
        items = self._dedup.deduplicate(items)
        after = len(items)
        if before != after:
            logger.info(f"AlignmentPipeline: 去重 {before} → {after} 条 ({source_id})")

        self._emit({
            "event": "align_done",
            "source_id": source_id,
            "items_aligned": after,
        })

        return items

    def _dispatch(self, source_id: str, rows: list[dict], meta: dict) -> list[CanonicalItem]:
        """根据 source_id 分发到对应 Normalizer"""

        # ── 社交平台 ────────────────────────────────────────
        if source_id.startswith("social."):
            platform = source_id.split(".", 1)[1]  # e.g. "bilibili"
            return self._social.normalize_batch(rows, platform)

        # ── 新闻 RSS ────────────────────────────────────────
        if source_id.startswith("news.rss."):
            feed_category = meta.get("feed_category", "news")
            items = []
            for row in rows:
                item = self._news.normalize_from_feedparser(row, source_id, feed_category)
                if item:
                    items.append(item)
            return items

        # ── 地理事件 ────────────────────────────────────────
        if source_id == "geo.acled":
            return [
                item for row in rows
                if (item := self._geo.normalize_acled(row)) is not None
            ]
        if source_id == "geo.usgs":
            return [
                item for feature in rows
                if (item := self._geo.normalize_usgs(feature)) is not None
            ]
        if source_id == "geo.gdelt":
            return [
                item for row in rows
                if (item := self._geo.normalize_gdelt(row)) is not None
            ]

        # ── 军事 ────────────────────────────────────────────
        if source_id == "military.opensky":
            return [
                item for sv in rows
                if (item := self._military.normalize_opensky(sv)) is not None
            ]
        if source_id == "military.ais":
            return [
                item for row in rows
                if (item := self._military.normalize_ais_snapshot(row)) is not None
            ]

        # ── 市场 ────────────────────────────────────────────
        if source_id == "market.coingecko":
            coin_id = meta.get("coin_id", "unknown")
            items = []
            for row in rows:
                item = self._market.normalize_coingecko_simple(coin_id, row)
                if item:
                    items.append(item)
            return items

        # ── 网络威胁 ────────────────────────────────────────
        if source_id == "cyber.feodo":
            return [
                item for row in rows
                if (item := self._cyber.normalize_feodo(row)) is not None
            ]
        if source_id == "cyber.urlhaus":
            return [
                item for row in rows
                if (item := self._cyber.normalize_urlhaus(row)) is not None
            ]

        # ── 中文热搜聚合 (BettaFish NewsNow) ─────────────────
        if source_id.startswith("hotsearch."):
            # raw_data 由 NewsNowAdapter.fetch_all() 返回的整个响应 dict 列表
            # 或 align() 以 dict 方式传入整个 response → [response]
            if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0]:
                return self._hotsearch.normalize_batch(rows[0], source_id)
            # 如果 rows 已是 items 展开列表，也能处理
            return self._hotsearch.normalize_batch({"items": rows}, source_id)

        logger.warning(f"AlignmentPipeline: 未知 source_id={source_id}，跳过 {len(rows)} 条")
        return []

    async def align_and_save(
        self,
        source_id: str,
        raw_data: list[dict],
        meta: Optional[dict] = None,
        db_session=None,
    ) -> list[CanonicalItem]:
        """
        对齐数据并异步写入数据库（如果提供了 db_session）。
        """
        items = self.align(source_id, raw_data, meta)

        if db_session is not None and items:
            from db.models import CanonicalItemModel
            try:
                for item in items:
                    model = CanonicalItemModel(
                        item_id=item.item_id,
                        source_id=item.source_id,
                        source_type=item.source_type,
                        title=item.title[:2000],
                        body=item.body,
                        author=item.author,
                        url=item.url,
                        published_at=item.published_at,
                        crawled_at=item.crawled_at,
                        geo_lat=item.geo_lat,
                        geo_lon=item.geo_lon,
                        geo_country=item.geo_country,
                        geo_region=item.geo_region,
                        hotness_score=item.hotness_score,
                        severity_level=item.severity_level,
                        sentiment=item.sentiment,
                        raw_engagement=item.raw_engagement,
                        raw_metadata=item.raw_metadata,
                        categories=item.categories,
                        keywords=item.keywords,
                        is_classified=item.is_classified,
                        classification_source=item.classification_source,
                    )
                    db_session.add(model)

                await db_session.flush()
                logger.info(f"AlignmentPipeline: 写入 {len(items)} 条到 DB source={source_id}")
            except Exception as e:
                logger.error(f"AlignmentPipeline: DB 写入失败 source={source_id} err={e}")
                await db_session.rollback()
                raise

        return items
