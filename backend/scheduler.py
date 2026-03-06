# -*- coding: utf-8 -*-
"""
DataScheduler — 借鉴 WorldMonitor 分层 TTL 策略的后台调度器

策略参考 worldmonitor/server/worldmonitor/economic/v1/get-macro-signals.ts:
- 实时数据（价格/飞行/服务状态）: 5分钟
- 新闻/热搜: 15分钟
- 事件/威胁/算力: 30分钟
- 宏观指标/论文: 60分钟
- 贸易/人道/慢变数据: 360分钟

特性:
- APScheduler AsyncIOScheduler（与 Flask 事件循环共存）
- stale_cache: 采集失败时返回上次成功结果，不让前端看到空数据
- 通过 CrawlerEngine 采集，自动写库 + SSE 推送
- 并发并行：同一 interval 内的任务并发执行
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Optional, Callable, Any

from loguru import logger

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.executors.pool import ThreadPoolExecutor
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("APScheduler 未安装，调度器将以降级模式运行。安装: pip install apscheduler")


# ──────────────────────────────────────────────────────────────
# 调度分层配置（WorldMonitor TTL 策略）
# ──────────────────────────────────────────────────────────────

REALTIME_INTERVAL_MIN  = 1    # 价格/飞行/服务状态
NEWS_INTERVAL_MIN      = 5    # 新闻/热搜 (changed from 15)
EVENT_INTERVAL_MIN     = 30   # 冲突/CVE/火点/算力
MACRO_INTERVAL_MIN     = 60   # 宏观指标/论文/恐惧贪婪
SLOW_INTERVAL_MIN      = 360  # 贸易/人道/难民统计


# source_id → interval(分钟)的分层映射
SOURCE_SCHEDULE: dict[str, int] = {
    # ── 实时 (5分钟) ──────────────────────────────────────────
    "economy.crypto.coingecko":           REALTIME_INTERVAL_MIN,
    "economy.stock.yfinance_us":          REALTIME_INTERVAL_MIN,
    "economy.stock.country_index":        REALTIME_INTERVAL_MIN,
    "economy.futures.commodity_quotes":   REALTIME_INTERVAL_MIN,
    "global.military.opensky":            REALTIME_INTERVAL_MIN,
    "tech.infra.cloud_aws":               REALTIME_INTERVAL_MIN,
    "tech.infra.cloud_cloudflare":        REALTIME_INTERVAL_MIN,
    "tech.infra.cloud_gcp":               REALTIME_INTERVAL_MIN,
    "tech.infra.cloud_vercel":            REALTIME_INTERVAL_MIN,
    "tech.infra.dev_github":              REALTIME_INTERVAL_MIN,
    "tech.infra.dev_npm":                 REALTIME_INTERVAL_MIN,
    "tech.infra.comm_slack":              REALTIME_INTERVAL_MIN,
    "tech.infra.comm_discord":            REALTIME_INTERVAL_MIN,
    "tech.infra.saas_stripe":             REALTIME_INTERVAL_MIN,
    "tech.ai.openai_status":              REALTIME_INTERVAL_MIN,
    "tech.ai.anthropic_status":           REALTIME_INTERVAL_MIN,
    "tech.ai.replicate_status":           REALTIME_INTERVAL_MIN,
    "tech.ai.hf_models":                  NEWS_INTERVAL_MIN,  # 15 min by default, but user wants 5 min for tech section refresh?
    "tech.ai.hf_datasets":                NEWS_INTERVAL_MIN,
    "tech.ai.ms_models":                  NEWS_INTERVAL_MIN,
    "tech.ai.ms_datasets":                NEWS_INTERVAL_MIN,

    # ── 新闻/热搜 (15分钟) ─────────────────────────────────────
    "global.social.weibo_newsnow":        NEWS_INTERVAL_MIN,
    "global.social.zhihu_newsnow":        NEWS_INTERVAL_MIN,
    "global.social.bilibili_newsnow":     NEWS_INTERVAL_MIN,
    "global.social.douyin_newsnow":       NEWS_INTERVAL_MIN,
    "global.social.tieba_newsnow":        NEWS_INTERVAL_MIN,
    "economy.stock.wallstreetcn":         NEWS_INTERVAL_MIN,
    "economy.stock.cls_hot":              NEWS_INTERVAL_MIN,
    "economy.stock.xueqiu":              NEWS_INTERVAL_MIN,
    "global.diplomacy.thepaper":          NEWS_INTERVAL_MIN,
    "tech.oss.github_trending":           NEWS_INTERVAL_MIN,
    "tech.oss.coolapk":                   NEWS_INTERVAL_MIN,
    "tech.oss.toutiao_tech":              NEWS_INTERVAL_MIN,
    "tech.oss.hackernews":                NEWS_INTERVAL_MIN,
    "tech.oss.techcrunch":                NEWS_INTERVAL_MIN,
    "tech.oss.tech_events":               NEWS_INTERVAL_MIN,
    "tech.oss.trending_repos":            NEWS_INTERVAL_MIN,

    # ── 事件/威胁 (30分钟) ─────────────────────────────────────
    "global.disaster.usgs":               EVENT_INTERVAL_MIN,
    "global.disaster.nasa_firms":         EVENT_INTERVAL_MIN,
    "global.conflict.gdelt":              EVENT_INTERVAL_MIN,
    "global.conflict.humanitarian":       EVENT_INTERVAL_MIN,
    "tech.cyber.nvd_cve":                 EVENT_INTERVAL_MIN,
    "tech.cyber.feodo":                   EVENT_INTERVAL_MIN,
    "tech.cyber.urlhaus":                 EVENT_INTERVAL_MIN,
    "economy.quant.mempool_hashrate":     REALTIME_INTERVAL_MIN,
    "academic.prediction.polymarket":     EVENT_INTERVAL_MIN,

    # ── 宏观指标/论文 (60分钟) ─────────────────────────────────
    "economy.quant.fear_greed_index":     REALTIME_INTERVAL_MIN,
    "economy.quant.fred_series":          MACRO_INTERVAL_MIN,
    "economy.quant.macro_signals":        MACRO_INTERVAL_MIN,
    "economy.quant.bis_policy_rates":     MACRO_INTERVAL_MIN,
    "academic.arxiv.cs_ai":               MACRO_INTERVAL_MIN,
    "academic.arxiv.cs_lg":               MACRO_INTERVAL_MIN,
    "academic.arxiv.cs_cv":               MACRO_INTERVAL_MIN,
    "academic.arxiv.cs_cl":               MACRO_INTERVAL_MIN,
    "academic.arxiv.econ":                MACRO_INTERVAL_MIN,
    "academic.arxiv.physics":             MACRO_INTERVAL_MIN,
    "academic.arxiv.q_bio":               MACRO_INTERVAL_MIN,
    "academic.arxiv.math_st":             MACRO_INTERVAL_MIN,
    "academic.huggingface.papers":        MACRO_INTERVAL_MIN,
    "academic.semantic_scholar.trending": MACRO_INTERVAL_MIN,
    "global.conflict.acled":              MACRO_INTERVAL_MIN,
    "global.conflict.ucdp":               MACRO_INTERVAL_MIN,
    "global.displacement.unhcr":          MACRO_INTERVAL_MIN,

    # ── 慢变数据 (6小时) ──────────────────────────────────────
    "economy.trade.wto_flows":            SLOW_INTERVAL_MIN,
    "economy.trade.wto_barriers":         SLOW_INTERVAL_MIN,
    "economy.quant.worldbank_indicators": SLOW_INTERVAL_MIN,
    "global.displacement.idmc":           SLOW_INTERVAL_MIN,
}


class DataScheduler:
    """
    后台数据采集调度器。

    Design:
    ·借鉴 WorldMonitor 分层 TTL，不同数据源按新鲜度需求分配采集频率
    ·stale_cache 失败兜底：上次成功结果持久化，前端 API 始终有数据
    ·采集通过 CrawlerEngine.run_api() / run_hotsearch()，复用已有管道
    ·通过 SSE _broadcast 实时推送采集结果

    Usage:
        scheduler = DataScheduler(engine, db_session_factory)
        scheduler.start()

        # 手动触发：
        scheduler.trigger(source_id)

        # 关闭：
        scheduler.shutdown()
    """

    def __init__(
        self,
        engine,                   # CrawlerEngine 实例
        db_session_factory=None,  # async session factory（可选）
        broadcast_cb: Optional[Callable[[dict], None]] = None,
    ):
        self._engine = engine
        self._db_factory = db_session_factory
        self._broadcast = broadcast_cb

        # stale_cache: source_id → last successful items count
        self._last_success: dict[str, datetime] = {}
        self._last_count: dict[str, int] = {}

        # APScheduler
        self._scheduler = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

        if HAS_APSCHEDULER:
            self._scheduler = BackgroundScheduler(
                executors={"default": ThreadPoolExecutor(max_workers=4)},
                job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
            )

    def start(self):
        """启动调度器（在独立线程中运行事件循环）"""
        if not HAS_APSCHEDULER:
            logger.warning("DataScheduler: APScheduler 未安装，跳过调度器启动")
            return

        # 为调度任务启动专用事件循环线程
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name="scheduler-loop"
        )
        self._thread.start()

        # 注册所有调度任务
        self._register_jobs()
        self._scheduler.start()
        logger.info(f"DataScheduler: 已启动，注册 {len(SOURCE_SCHEDULE)} 个定时任务")
        # 启动时立即触发一次全量刷新
        self.trigger_all_now()

    def _register_jobs(self):
        """按 TTL 分层注册所有调度任务"""
        for source_id, interval_min in SOURCE_SCHEDULE.items():
            self._scheduler.add_job(
                func=self._run_sync_wrapper,
                trigger="interval",
                minutes=interval_min,
                id=f"crawl_{source_id.replace('.', '_')}",
                args=[source_id],
                next_run_time=None,  # 启动时不立即运行，等第一个 interval
            )

        # P1-C: 每 30 分钟执行一次 SQLite WAL checkpoint，防止 WAL 文件无限增长
        if HAS_APSCHEDULER:
            self._scheduler.add_job(
                func=self._checkpoint_db,
                trigger="interval",
                minutes=30,
                id="sqlite_wal_checkpoint",
                next_run_time=None,
            )

    def _run_sync_wrapper(self, source_id: str):
        """在调度器线程中触发异步采集（通过事件循环提交）"""
        if self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._crawl(source_id), self._loop
            )
            try:
                future.result(timeout=120)  # 120s 超时
            except Exception as e:
                logger.warning(f"DataScheduler: {source_id} 调度任务异常 → {e}")

    def _checkpoint_db(self):
        """P1-C: 定期 SQLite WAL checkpoint，防止 WAL 文件 > 25MB 无限增长"""
        try:
            from db.session import get_sync_session
            from sqlalchemy import text
            with get_sync_session() as session:
                session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
                logger.info("DataScheduler: SQLite WAL checkpoint (TRUNCATE) 完成")
        except Exception as e:
            logger.warning(f"DataScheduler: WAL checkpoint 失败 → {e}")

    async def _crawl(self, source_id: str):
        """
        执行单个 source 采集并更新 stale_cache。
        WorldMonitor stale-while-revalidate 模式：失败不清空缓存，只记录错误。
        """
        logger.debug(f"DataScheduler: 开始采集 {source_id}")

        # Normalize prefix to frontend tab domain IDs
        # source_id prefix "tech" → frontend tab "technology"
        _raw_domain = source_id.split(".")[0]
        _DOMAIN_ALIAS = {"tech": "technology"}
        _domain = _DOMAIN_ALIAS.get(_raw_domain, _raw_domain)

        if self._broadcast:
            self._broadcast({
                "event": "scheduler_start",
                "source_id": source_id,
                "domain": _domain,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        try:
            # 还原之前的逻辑：为了确保数据能入库，需要传递 db_session。
            # 如果不传，engine 和 pipeline 将直接跳过写库逻辑。
            if self._db_factory:
                async with self._db_factory() as db_session:
                    items = await self._dispatch_crawl(source_id, db_session=db_session)
            else:
                items = await self._dispatch_crawl(source_id, db_session=None)

            # 更新 stale_cache
            self._last_success[source_id] = datetime.now(timezone.utc)
            self._last_count[source_id] = len(items)

            if self._broadcast:
                # 标准化 domain：确保前端 tab id 和 item domain 一致
                _ITEM_DOMAIN_ALIAS = {"tech": "technology"}
                self._broadcast({
                    "event": "scheduler_done",
                    "source_id": source_id,
                    "domain": _domain,  # e.g. "economy", "global", "technology", "academic"
                    "items_count": len(items),
                    "timestamp": self._last_success[source_id].isoformat(),
                    "items": [
                        {
                            "item_id": i.item_id,
                            "title": i.title,
                            "url": i.url,
                            # 统一 domain 别名（tech → technology），确保前端按 tab 过滤时命中
                            "domain": _ITEM_DOMAIN_ALIAS.get(i.domain, i.domain) or _domain,
                            "sub_domain": i.sub_domain,
                            "source_id": i.source_id,
                            "crawled_at": i.crawled_at.isoformat() if i.crawled_at else None,
                            "published_at": i.published_at.isoformat() if i.published_at else None,
                            "hotness_score": i.hotness_score,
                        } for i in items[:20]  # 只传前20条节省带宽
                    ],
                })
            logger.info(f"DataScheduler: {source_id} 完成，{len(items)} 条")

        except Exception as e:
            logger.warning(f"DataScheduler: {source_id} 采集失败（stale cache 保留）→ {e}")
            # stale-while-revalidate: 不清空 last_success，允许前端使用旧数据
            if self._broadcast:
                self._broadcast({
                    "event": "scheduler_error",
                    "source_id": source_id,
                    "domain": _domain,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "error": str(e),
                    "items_count": self._last_count.get(source_id, 0),
                })

    async def _dispatch_crawl(self, source_id: str, db_session=None) -> list:
        """
        根据 source_id 路由到对应的采集方法。
        遵循与 engine.py 相同的 source_id 约定。
        """
        from crawler_engine.api_adapters.extended_adapters import (
            YahooFinanceAdapter, FearGreedAdapter, BtcHashrateAdapter,
            HuggingFaceAdapter, CloudStatusAdapter, NVDAdapter,
            ReliefWebAdapter, PolymarketAdapter, HackerNewsAdapter,
            SemanticScholarAdapter,
        )
        from data_alignment.pipeline import AlignmentPipeline

        pipeline = self._engine._pipeline

        # ── 云/AI 服务状态 (CloudStatusAdapter) ─────────────────
        if source_id.startswith("tech.infra.") or source_id.startswith("tech.ai."):
            async def _do_cloud():
                adapter = CloudStatusAdapter()
                results = await adapter.fetch_all([source_id])
                if source_id in results:
                    return await pipeline.align_and_save(source_id, [results[source_id]], db_session=db_session)
                return []
            return await self._engine.run_custom_adapter(source_id, _do_cloud, db_session=db_session)

        # ── 股票/指数 (Yahoo Finance) ─────────────────────────
        if source_id in ("economy.stock.yfinance_us", "economy.stock.country_index"):
            async def _do_yfinance_indices():
                adapter = YahooFinanceAdapter()
                rows = await adapter.fetch_indices()
                return await pipeline.align_and_save(source_id, rows, meta={"symbol": ""}, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_yfinance_indices, db_session=db_session)

        if source_id == "economy.futures.commodity_quotes":
            async def _do_yfinance_futures():
                adapter = YahooFinanceAdapter()
                rows = await adapter.fetch_commodities()
                return await pipeline.align_and_save(source_id, rows, meta={"symbol": ""}, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_yfinance_futures, db_session=db_session)

        # ── Fear & Greed ──────────────────────────────────────
        if source_id == "economy.quant.fear_greed_index":
            async def _do_fear_greed():
                adapter = FearGreedAdapter()
                rows = await adapter.fetch(limit=1)
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_fear_greed, db_session=db_session)

        # ── Bitcoin Hashrate ──────────────────────────────────
        if source_id == "economy.quant.mempool_hashrate":
            async def _do_mempool():
                adapter = BtcHashrateAdapter()
                data = await adapter.fetch()
                return await pipeline.align_and_save(source_id, [data], db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_mempool, db_session=db_session)

        # ── arXiv RSS Papers ─────────────────────────────────
        if source_id.startswith("academic.arxiv."):
            return await self._engine.run_rss(feed_ids=[source_id], db_session=db_session)

        # ── HuggingFace Daily Papers ──────────────────────────
        if source_id == "academic.huggingface.papers":
            async def _do_hf_papers():
                adapter = HuggingFaceAdapter()
                rows = await adapter.fetch()
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_hf_papers, db_session=db_session)

        # ── HuggingFace Trending Models/Datasets ──────────────
        if source_id in ("tech.ai.hf_models", "tech.ai.hf_datasets"):
            async def _do_hf_trending():
                adapter = HuggingFaceAdapter()
                if "models" in source_id:
                    rows = await adapter.fetch_trending_models()
                else:
                    rows = await adapter.fetch_trending_datasets()
                # Use tech_normalizer via pipeline
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_hf_trending, db_session=db_session)

        # ── ModelScope Trending Models/Datasets ───────────────
        if source_id in ("tech.ai.ms_models", "tech.ai.ms_datasets"):
            # ModelScopeAdapter 暂未实现，跳过避免 NameError
            logger.debug(f"DataScheduler: {source_id} — ModelScopeAdapter 未实现，跳过")
            return []

        # ── Semantic Scholar Trending ────────────────────────
        if source_id == "academic.semantic_scholar.trending":
            async def _do_scholar():
                adapter = SemanticScholarAdapter()
                rows = await adapter.fetch_trending(query="AI")
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_scholar, db_session=db_session)

        # ── NVD CVE ───────────────────────────────────────────
        if source_id == "tech.cyber.nvd_cve":
            async def _do_nvd():
                adapter = NVDAdapter()
                rows = await adapter.fetch_recent()
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_nvd, db_session=db_session)

        # ── ReliefWeb 人道危机 ─────────────────────────────────
        if source_id == "global.conflict.humanitarian":
            async def _do_reliefweb():
                adapter = ReliefWebAdapter()
                rows = await adapter.fetch_disasters()
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_reliefweb, db_session=db_session)

        # ── Polymarket ────────────────────────────────────────
        if source_id == "academic.prediction.polymarket":
            async def _do_polymarket():
                adapter = PolymarketAdapter()
                rows = await adapter.fetch_active()
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_polymarket, db_session=db_session)

        # ── Hacker News ───────────────────────────────────────
        if source_id == "tech.oss.hackernews":
            async def _do_hackernews():
                adapter = HackerNewsAdapter()
                rows = await adapter.fetch_top_stories()
                return await pipeline.align_and_save(source_id, rows, db_session=db_session)
            return await self._engine.run_custom_adapter(source_id, _do_hackernews, db_session=db_session)

        # ── Tech Events ───────────────────────────────────────
        if source_id == "tech.oss.tech_events":
            # Adapter not yet implemented
            return []

        # ── 加密货币 (CoinGecko) ───────────────────────────────
        if source_id == "economy.crypto.coingecko":
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── USGS 地震 ─────────────────────────────────────────
        if source_id in ("global.disaster.usgs", "global.disaster.earthquakes_wm"):
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── GDELT 全球事件 ────────────────────────────────────
        if source_id == "global.conflict.gdelt":
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── ACLED 冲突 ────────────────────────────────────────
        if source_id in ("global.conflict.acled", "global.unrest.acled_protests"):
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── NASA 野火 ─────────────────────────────────────────
        if source_id == "global.disaster.nasa_firms":
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── OpenSky ADS-B ─────────────────────────────────────
        if source_id == "global.military.opensky":
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── Cyber threats ─────────────────────────────────────
        if source_id == "tech.cyber.feodo":
            return await self._engine.run_api(source_id, db_session=db_session)
        if source_id == "tech.cyber.urlhaus":
            return await self._engine.run_api(source_id, db_session=db_session)

        # ── NewsNow 热搜系列 ──────────────────────────────────
        _NEWSNOW_SOURCES = {
            "global.social.weibo_newsnow",
            "global.social.zhihu_newsnow",
            "global.social.bilibili_newsnow",
            "global.social.douyin_newsnow",
            "global.social.tieba_newsnow",
            "economy.stock.wallstreetcn",
            "economy.stock.cls_hot",
            "economy.stock.xueqiu",
            "global.diplomacy.thepaper",
            "tech.oss.github_trending",
            "tech.oss.coolapk",
            "tech.oss.toutiao_tech",
        }
        if source_id in _NEWSNOW_SOURCES:
            return await self._engine.run_hotsearch(source_ids=[source_id], db_session=db_session)

        logger.warning(f"DataScheduler: 未知 source_id={source_id}，跳过")
        return []

    def trigger(self, source_id: str):
        """
        手动立即触发单个 source 的采集任务。
        用于 /api/v1/scheduler/trigger/<source_id> API 端点。
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._crawl(source_id), self._loop)
            logger.info(f"DataScheduler: 手动触发 {source_id}")
        else:
            logger.warning(f"DataScheduler: 调度器未运行，无法触发 {source_id}")

    def status(self) -> dict:
        """返回调度器状态快照"""
        jobs = []
        if self._scheduler and HAS_APSCHEDULER:
            for job in self._scheduler.get_jobs():
                jobs.append({
                    "job_id": job.id,
                    "source_id": job.args[0] if job.args else "",
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "interval_min": SOURCE_SCHEDULE.get(job.args[0] if job.args else "", 0),
                })

        return {
            "running": self._scheduler.running if self._scheduler else False,
            "has_apscheduler": HAS_APSCHEDULER,
            "total_jobs": len(SOURCE_SCHEDULE),
            "jobs": jobs,
            "stale_cache": {
                sid: {
                    "last_success": ts.isoformat(),
                    "items_count": self._last_count.get(sid, 0),
                }
                for sid, ts in self._last_success.items()
            },
        }

    def trigger_all_now(self):
        """立即触发所有已注册的采集任务（全量刷新，一般用于初始化）"""
        logger.info(f"DataScheduler: 全量触发 {len(SOURCE_SCHEDULE)} 个任务")
        for source_id in SOURCE_SCHEDULE:
            self.trigger(source_id)

    def shutdown(self):
        """关闭调度器"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        logger.info("DataScheduler: 已关闭")
