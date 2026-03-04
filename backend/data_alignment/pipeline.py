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
from data_alignment.normalizers.economy_normalizer import EconomyNormalizer
from data_alignment.normalizers.tech_normalizer import TechNormalizer
from data_alignment.normalizers.academic_normalizer import AcademicNormalizer
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
        self._economy = EconomyNormalizer()
        self._tech = TechNormalizer()
        self._academic = AcademicNormalizer()
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
            from data_source.registry import registry
            config = registry.get(source_id)
            
            items = self._dispatch(source_id, raw_data, meta, config)
            
            # Enrich with domain info from registry if not already set
            if config:
                for item in items:
                    if not item.domain:
                        item.domain = config.domain
                    if not item.sub_domain:
                        item.sub_domain = config.sub_domain

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

    def _dispatch(self, source_id: str, rows: list[dict], meta: dict, config=None) -> list[CanonicalItem]:
        """根据 source_id 或 config 分发到对应 Normalizer"""

        # 1. 优先根据 config 中的 crawl_method 分发
        if config:
            if config.crawl_method == "rss":
                feed_category = meta.get("feed_category", config.domain or "news")
                if source_id.startswith("academic.arxiv."):
                    return [
                        item for row in rows
                        if (item := self._academic.normalize_arxiv_paper(row, source_id.split(".")[-1])) is not None
                    ]
                return self._news.normalize_batch_from_feedparser(rows, source_id, feed_category)
            
            if config.source_type == "hotsearch" or source_id.endswith("_newsnow"):
                # Exception for github trending since we enriched it with GithubAdapter
                if source_id == "tech.oss.github_trending":
                    items_raw = rows[0].get("items", []) if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0] else rows
                    if isinstance(items_raw, dict) and "items" in items_raw:
                        items_raw = items_raw["items"]  # Just in case
                    return [
                        item for row in items_raw
                        if (item := self._tech.normalize_github_trending(row, source_id)) is not None
                    ]

                # raw_data 由 NewsNowAdapter.fetch_all() 返回的整个响应 dict 列表
                if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0]:
                    return self._hotsearch.normalize_batch(rows[0], source_id)
                return self._hotsearch.normalize_batch({"items": rows}, source_id)

        # 2. 回退到基于 source_id 的启发式规则 (用于支持未注册或旧式 ID)
        
        # ── 社交平台 ────────────────────────────────────────
        if source_id.startswith("social."):
            platform = source_id.split(".", 1)[1]  # e.g. "bilibili"
            return self._social.normalize_batch(rows, platform)

        # ── 新闻 RSS (旧式或者 fallback) ─────────────────────
        if source_id.startswith("news.rss."):
            feed_category = meta.get("feed_category", "news")
            return self._news.normalize_batch_from_feedparser(rows, source_id, feed_category)

        # ── arXiv / 学术 RSS (academic.arxiv.*) ─────────────
        if source_id.startswith("academic.arxiv."):
            category = source_id.split(".")[-1]
            return [
                item for row in rows
                if (item := self._academic.normalize_arxiv_paper(row, category)) is not None
            ]

        # ── HuggingFace 每日论文 ──────────────────────────────
        if source_id == "academic.huggingface.papers":
            return [
                item for row in rows
                if (item := self._academic.normalize_huggingface_paper(row)) is not None
            ]

        # ── Semantic Scholar ──────────────────────────────────
        if source_id == "academic.semantic_scholar.trending":
            return [
                item for row in rows
                if (item := self._academic.normalize_semantic_scholar(row)) is not None
            ]

        # ── 预测市场 Polymarket ───────────────────────────────
        if source_id == "academic.prediction.polymarket":
            return [
                item for row in rows
                if (item := self._academic.normalize_polymarket(row)) is not None
            ]

        # ── 地理事件 (旧式 geo.* source_id) ─────────────────
        if source_id in ("geo.acled", "global.conflict.acled", "global.unrest.acled_protests"):
            return [
                item for row in rows
                if (item := self._geo.normalize_acled(row)) is not None
            ]
        if source_id in ("geo.usgs", "global.disaster.usgs", "global.disaster.earthquakes_wm"):
            return [
                item for feature in rows
                if (item := self._geo.normalize_usgs(feature)) is not None
            ]
        if source_id in ("geo.gdelt", "global.conflict.gdelt"):
            return [
                item for row in rows
                if (item := self._geo.normalize_gdelt(row)) is not None
            ]
        if source_id == "global.conflict.ucdp":
            return [
                item for row in rows
                if (item := self._geo.normalize_gdelt(row)) is not None  # UCDP 格式兼容 gdelt normalizer
            ]
        if source_id in ("global.conflict.humanitarian",):
            return [
                item for row in rows
                if (item := self._geo.normalize_reliefweb(row)) is not None
            ]
        if source_id in ("global.disaster.nasa_firms", "geo.nasa_firms"):
            return [
                item for row in rows
                if (item := self._geo.normalize_nasa_firms(row)) is not None
            ]

        # ── 军事 ────────────────────────────────────────────
        if source_id in ("military.opensky", "global.military.opensky"):
            return [
                item for sv in rows
                if (item := self._military.normalize_opensky(sv)) is not None
            ]
        if source_id in ("military.ais", "global.military.ais"):
            return [
                item for row in rows
                if (item := self._military.normalize_ais_snapshot(row)) is not None
            ]

        # ── 经济域 economy.* ─────────────────────────────────
        if source_id.startswith("economy."):
            return self._dispatch_economy(source_id, rows, meta)

        # ── 技术域 tech.* ─────────────────────────────────────
        if source_id.startswith("tech."):
            return self._dispatch_tech(source_id, rows, meta)

        # ── 市场 (旧式 market.*) ──────────────────────────────
        if source_id == "market.coingecko":
            coin_id = meta.get("coin_id", "unknown")
            items = []
            for row in rows:
                item = self._market.normalize_coingecko_simple(coin_id, row)
                if item:
                    items.append(item)
            return items

        # ── 网络威胁 ────────────────────────────────────────
        if source_id in ("cyber.feodo", "tech.cyber.feodo"):
            return [
                item for row in rows
                if (item := self._tech.normalize_feodo(row)) is not None
            ]
        if source_id in ("cyber.urlhaus", "tech.cyber.urlhaus"):
            return [
                item for row in rows
                if (item := self._tech.normalize_urlhaus(row)) is not None
            ]
        if source_id == "tech.cyber.nvd_cve":
            return [
                item for row in rows
                if (item := self._tech.normalize_nvd_cve(row)) is not None
            ]

        # ── 云服务 / AI 服务状态 ──────────────────────────────
        if source_id.startswith("tech.infra."):
            return [
                item for row in rows
                if (item := self._tech.normalize_service_status(row, source_id)) is not None
            ]
        if source_id.startswith("tech.ai."):
            return [
                item for row in rows
                if (item := self._tech.normalize_ai_service_status(row, source_id)) is not None
            ]

        # ── 中文热搜聚合 (BettaFish NewsNow) ─────────────────
        if source_id.startswith("hotsearch.") or source_id.endswith("_newsnow") or \
                any(source_id == sid for sid in [
                    "global.social.weibo_newsnow", "global.social.zhihu_newsnow",
                    "global.social.bilibili_newsnow", "global.social.douyin_newsnow",
                    "global.social.tieba_newsnow", "economy.stock.wallstreetcn",
                    "economy.stock.cls_hot", "economy.stock.xueqiu",
                    "global.diplomacy.thepaper", "tech.oss.coolapk", "tech.oss.toutiao_tech",
                ]):
            # raw_data 由 NewsNowAdapter.fetch_all() 返回的整个响应 dict 列表
            if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0]:
                return self._hotsearch.normalize_batch(rows[0], source_id)
            return self._hotsearch.normalize_batch({"items": rows}, source_id)

        logger.warning(f"AlignmentPipeline: 未知 source_id={source_id}，跳过 {len(rows)} 条")
        return []

    def _dispatch_economy(self, source_id: str, rows: list[dict], meta: dict) -> list[CanonicalItem]:
        """经济域分发"""
        # Crypto
        if "coingecko" in source_id:
            return [item for row in rows if (item := self._economy.normalize_coingecko(row, source_id)) is not None]
        if "stablecoin" in source_id:
            return [item for row in rows if (item := self._economy.normalize_coingecko(row, source_id)) is not None]
        # Stock (Yahoo chart)
        if source_id in ("economy.stock.yfinance_us", "economy.stock.country_index",
                         "economy.stock.sector_summary", "economy.stock.alpha_vantage",
                         "economy.stock.finnhub", "economy.stock.hk_akshare"):
            symbol = meta.get("symbol", "")
            return [item for row in rows if (item := self._economy.normalize_yahoo_chart(symbol, row, source_id)) is not None]
        # Stock (AKShare spot)
        if source_id in ("economy.stock.akshare_a",):
            return [item for row in rows if (item := self._economy.normalize_akshare_spot(row, source_id)) is not None]
        # Quant signals
        if source_id == "economy.quant.macro_signals":
            return [item for row in rows if (item := self._economy.normalize_macro_signals(row, source_id)) is not None]
        if source_id == "economy.quant.fred_series":
            series_id = meta.get("series_id", source_id)
            title = meta.get("title", series_id)
            observations = meta.get("observations", rows)
            item = self._economy.normalize_fred_series(series_id, title, observations)
            return [item] if item else []
        if source_id == "economy.quant.fear_greed_index":
            return [item for row in rows if (item := self._economy.normalize_fear_greed(row, source_id)) is not None]
        if source_id == "economy.quant.mempool_hashrate":
            return [item for row in rows if (item := self._economy.normalize_mempool_hashrate(row, source_id)) is not None]
        if source_id in ("economy.quant.bis_policy_rates", "economy.quant.bis_exchange_rates",
                         "economy.quant.bis_credit", "economy.quant.worldbank_indicators",
                         "economy.quant.energy_prices"):
            return [item for row in rows if (item := self._economy.normalize_macro_signals(row, source_id)) is not None]
        # Futures/commodities
        if source_id.startswith("economy.futures."):
            symbol = meta.get("symbol", "")
            return [item for row in rows if (item := self._economy.normalize_yahoo_chart(symbol, row, source_id)) is not None]
        # Trade
        if source_id.startswith("economy.trade."):
            return [item for row in rows if (item := self._economy.normalize_wto_trade(row, source_id)) is not None]
        # NewsNow-based economy hotsearch
        if any(source_id == sid for sid in ["economy.stock.wallstreetcn", "economy.stock.cls_hot", "economy.stock.xueqiu"]):
            if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0]:
                return self._hotsearch.normalize_batch(rows[0], source_id)
            return self._hotsearch.normalize_batch({"items": rows}, source_id)
        # Fallback for unknown economy sources
        logger.warning(f"AlignmentPipeline: economy 未知 source_id={source_id}，跳过")
        return []

    def _dispatch_tech(self, source_id: str, rows: list[dict], meta: dict) -> list[CanonicalItem]:
        """技术域分发"""
        if source_id in ("tech.oss.hackernews",):
            return [item for row in rows if (item := self._tech.normalize_hackernews(row, source_id)) is not None]
        if source_id == "tech.cyber.nvd_cve":
            return [item for row in rows if (item := self._tech.normalize_nvd_cve(row, source_id)) is not None]
        if source_id.startswith("tech.infra."):
            return [item for row in rows if (item := self._tech.normalize_service_status(row, source_id)) is not None]
        if source_id.startswith("tech.ai."):
            return [item for row in rows if (item := self._tech.normalize_ai_service_status(row, source_id)) is not None]
        if source_id in ("tech.cyber.feodo",):
            return [item for row in rows if (item := self._tech.normalize_feodo(row, source_id)) is not None]
        if source_id in ("tech.cyber.urlhaus",):
            return [item for row in rows if (item := self._tech.normalize_urlhaus(row, source_id)) is not None]
        # Tech Events
        if source_id == "tech.oss.tech_events":
            return [item for row in rows if (item := self._tech.normalize_service_status(row, source_id)) is not None]  # Or specific normalizer if needed
        if source_id == "tech.oss.github_trending":
            items_raw = rows[0].get("items", []) if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0] else rows
            return [
                item for row in items_raw
                if (item := self._tech.normalize_github_trending(row, source_id)) is not None
            ]

        # NewsNow-based tech hotsearch
        if source_id in ("tech.oss.coolapk", "tech.oss.toutiao_tech"):
            if len(rows) == 1 and isinstance(rows[0], dict) and "items" in rows[0]:
                return self._hotsearch.normalize_batch(rows[0], source_id)
            return self._hotsearch.normalize_batch({"items": rows}, source_id)
        logger.warning(f"AlignmentPipeline: tech 未知 source_id={source_id}，跳过")
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

        # ── <NEW> 内存直传: 写入 NewsFlash Deque ───────────────────────
        from memory_cache import news_flash_cache
        # 把最新对齐的数据加到队列头部
        for item in reversed(items):
            # 转换为前端直用的格式 dict
            item_dict = {
                "item_id": item.item_id,
                "title": item.title,
                "url": item.url,
                "domain": item.domain or "global",
                "sub_domain": item.sub_domain,
                "source_id": item.source_id,
                "crawled_at": item.crawled_at.isoformat() if hasattr(item.crawled_at, 'isoformat') else str(item.crawled_at) if item.crawled_at else None,
                "published_at": item.published_at.isoformat() if hasattr(item.published_at, 'isoformat') else str(item.published_at) if item.published_at else None,
                "hotness_score": item.hotness_score
            }
            news_flash_cache.appendleft(item_dict)
        # ──────────────────────────────────────────────────────────────

        if db_session is not None and items:
            from sqlalchemy import select, update
            from db.models import CanonicalItemModel
            try:
                # 1. 批量查询已存在的 item_id
                ids = [i.item_id for i in items]
                stmt = select(CanonicalItemModel.item_id).where(CanonicalItemModel.item_id.in_(ids))
                existing_ids = set((await db_session.execute(stmt)).scalars().all())

                new_items = [i for i in items if i.item_id not in existing_ids]
                existing_items = [i for i in items if i.item_id in existing_ids]

                # 2. UPSERT: 批量更新已存在条目的 crawled_at 和 hotness_score
                if existing_items:
                    from datetime import datetime, timezone
                    now_utc = datetime.now(timezone.utc)
                    
                    # 使用 in_ 语句批量更新所有匹配的 item_id，避免每条都需要提供内部主键 id
                    # 由于对已存在的条目，我们主要只是刷新最后更新时间，这里为了最高效直接把所有现有的刷同一时刻
                    existing_item_ids = [item.item_id for item in existing_items]
                    
                    # 如果有热度变化，则按热度分组更新，否则全部一起更新时间戳
                    # 简单分为 无热度/有热度 两种更新
                    items_with_heat = [i for i in existing_items if i.hotness_score is not None and i.hotness_score > 0]
                    items_without_heat = [i.item_id for i in existing_items if i.hotness_score is None or i.hotness_score == 0]

                    if items_without_heat:
                        await db_session.execute(
                            update(CanonicalItemModel)
                            .where(CanonicalItemModel.item_id.in_(items_without_heat))
                            .values(crawled_at=now_utc)
                        )
                        
                    if items_with_heat:
                        # 对于有具体热度分数的记录（股市/热榜等），按组分别更新
                        for item in items_with_heat:
                            await db_session.execute(
                                update(CanonicalItemModel)
                                .where(CanonicalItemModel.item_id == item.item_id)
                                .values(crawled_at=now_utc, hotness_score=item.hotness_score)
                            )
                            
                    logger.info(f"AlignmentPipeline: 更新 {len(existing_items)} 条已有记录 crawled_at source={source_id}")

                if not new_items:
                    await db_session.flush()
                    return items

                # === LLM Batch Classification ===
                try:
                    from utils.llm_client import LLMClient
                    llm = LLMClient()
                    if llm.api_key:
                        # 仅对以下情况进行 LLM 领域重分类：
                        # 1. domain 为空 — 来源不明
                        # 2. domain == "global" 且来源是 global.social.*/global.diplomacy.* — 可能混合各域内容
                        # 排除：tech.oss.*/economy.stock.* 等已有明确 domain 的热搜源，防止 LLM 错误覆盖
                        _NEEDS_LLM_PREFIXES = ("global.social.", "global.diplomacy.")
                        items_to_classify = [
                            item for item in new_items
                            if not item.domain
                            or (
                                item.domain == "global"
                                and any(item.source_id.startswith(p) for p in _NEEDS_LLM_PREFIXES)
                            )
                        ]
                        
                        if items_to_classify:
                            BATCH_SIZE = 20
                            for i in range(0, len(items_to_classify), BATCH_SIZE):
                                batch = items_to_classify[i:i+BATCH_SIZE]
                                items_data = [
                                    {
                                        "id": item.item_id, 
                                        "title": item.title, 
                                        "body": item.body or item.title
                                    }
                                    for item in batch
                                ]
                                
                                classification_results = await llm.classify_items_batch(items_data)
                                
                                for item in batch:
                                    if item.item_id in classification_results:
                                        res = classification_results[item.item_id]
                                        item.domain = res["domain"]
                                        if res["sub_domain"]:
                                            item.sub_domain = res["sub_domain"]
                                        item.is_classified = True
                                        item.classification_source = "llm"
                                        
                            logger.info(f"AlignmentPipeline: 完成 {len(items_to_classify)} 条目的 LLM 领域分类 source={source_id}")
                except Exception as e:
                    logger.error(f"AlignmentPipeline: LLM 分类过程异常 source={source_id} err={e}")
                # ================================

                for item in new_items:
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
                        domain=item.domain,          # 新增
                        sub_domain=item.sub_domain,  # 新增
                        is_classified=item.is_classified,
                        classification_source=item.classification_source,
                    )
                    db_session.add(model)

                await db_session.flush()
                logger.info(f"AlignmentPipeline: 写入 {len(new_items)} 条新条目到 DB source={source_id}")
            except Exception as e:
                logger.error(f"AlignmentPipeline: DB 写入失败 source={source_id} err={e}")
                await db_session.rollback()
                raise

        return items
