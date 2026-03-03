# -*- coding: utf-8 -*-
"""
CrawlerEngine — 主调度器

统一管理:
- RSS 新闻采集 (RSSFetcher)
- 各 API 数据源采集 (api_adapters)
- 社交平台爬虫 (PlaywrightCrawler → 保留接口，Playwright 运行时加载)

采集结果 → AlignmentPipeline → CanonicalItem
进度通过 SSE progress_cb 回调推送
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Callable

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import CrawlTaskModel

from crawler_engine.news.rss_fetcher import RSSFetcher
from crawler_engine.news.rss_sources import ALL_RSS_FEEDS
from crawler_engine.api_adapters import (
    ACLEDAdapter, GDELTAdapter, USGSAdapter,
    NASAFIRMSAdapter, OpenSkyAdapter, CoinGeckoAdapter,
    FeodoAdapter, URLhausAdapter, NewsNowAdapter,
)
from data_alignment.pipeline import AlignmentPipeline
from data_alignment.schema import CanonicalItem


class CrawlerTask:
    """爬虫任务描述对象"""

    def __init__(self, task_type: str, source_ids: list[str], params: dict = None):
        self.task_id = str(uuid.uuid4())
        self.task_type = task_type           # rss / api / social
        self.source_ids = source_ids
        self.params = params or {}
        self.status = "pending"              # pending/running/done/failed
        self.items_fetched = 0
        self.items_aligned = 0
        self.error_message = None
        self.started_at: Optional[datetime] = None
        self.finished_at: Optional[datetime] = None


class CrawlerEngine:
    """
    爬虫引擎主类。

    Usage:
        engine = CrawlerEngine()
        engine.set_progress_callback(my_sse_fn)
        items = await engine.run_rss(category="geopolitical")
        items = await engine.run_api("geo.usgs")
    """

    def __init__(self):
        self._rss_fetcher = RSSFetcher()
        self._pipeline = AlignmentPipeline()
        self._progress_cb: Optional[Callable[[dict], None]] = None

        # API Adapters（懒加载）
        self._acled: Optional[ACLEDAdapter] = None
        self._gdelt: Optional[GDELTAdapter] = None
        self._usgs: Optional[USGSAdapter] = None
        self._nasa: Optional[NASAFIRMSAdapter] = None
        self._opensky: Optional[OpenSkyAdapter] = None
        self._coingecko: Optional[CoinGeckoAdapter] = None
        self._feodo: Optional[FeodoAdapter] = None
        self._urlhaus: Optional[URLhausAdapter] = None
        self._newsnow: Optional[NewsNowAdapter] = None

        # 任务追踪
        self._tasks: dict[str, CrawlerTask] = {}

    def set_progress_callback(self, cb: Callable[[dict], None]):
        """注入 SSE 进度推送回调"""
        self._progress_cb = cb
        self._pipeline.set_progress_callback(cb)

    def _emit(self, event: dict):
        if self._progress_cb:
            try:
                self._progress_cb(event)
            except Exception:
                pass

    # ─── RSS 采集 ────────────────────────────────────────────

    async def run_rss(
        self,
        category: Optional[str] = None,
        feed_ids: Optional[list[str]] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> list[CanonicalItem]:
        """
        采集 RSS 新闻并对齐。

        Args:
            category: 按分类拉取，如 'geopolitical'/'military'/'tech'
            feed_ids: 指定 feed_id 列表，为空则拉取全部（受 category 过滤）
        """
        task = CrawlerTask("rss", source_ids=[], params={"category": category, "feed_ids": feed_ids})
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        self._tasks[task.task_id] = task

        self._emit({"event": "task_start", "task_id": task.task_id, "type": "rss", "category": category})

        if feed_ids:
            feeds = [f for f in ALL_RSS_FEEDS if f.feed_id in feed_ids]
        elif category:
            feeds = [f for f in ALL_RSS_FEEDS if f.category == category]
        else:
            feeds = ALL_RSS_FEEDS

        all_items: list[CanonicalItem] = []
        try:
            results = await self._rss_fetcher.fetch_feeds(feeds)
            task.items_fetched = sum(len(entries) for _, entries in results)

            for feed, entries in results:
                source_id = feed.feed_id
                items = await self._pipeline.align_and_save(
                    source_id=source_id,
                    raw_data=entries,
                    meta={"feed_category": feed.category},
                    db_session=db_session,
                )
                all_items.extend(items)

            task.items_aligned = len(all_items)
            task.status = "done"
            logger.info(f"CrawlerEngine RSS: {task.items_fetched} fetched → {task.items_aligned} aligned")
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            logger.error(f"CrawlerEngine RSS 失败: {e}")
        finally:
            task.finished_at = datetime.now(timezone.utc)
            if db_session:
                try:
                    task_model = CrawlTaskModel(
                        task_id=task.task_id,
                        source_id="rss.all" if not feed_ids else ",".join(feed_ids),
                        task_type="rss",
                        params={"category": category},
                        status=task.status,
                        items_fetched=task.items_fetched,
                        items_aligned=task.items_aligned,
                        error_message=task.error_message,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                    db_session.add(task_model)
                    await db_session.commit()
                except Exception as e:
                    logger.error(f"Failed to save CrawlTask to DB: {e}")

            self._emit({
                "event": "task_done",
                "task_id": task.task_id,
                "status": task.status,
                "items_fetched": task.items_fetched,
                "items_aligned": task.items_aligned,
            })

        return all_items

    # ─── API 采集 ────────────────────────────────────────────

    async def run_api(self, source_id: str, db_session: Optional[AsyncSession] = None, **kwargs) -> list[CanonicalItem]:
        """
        运行指定 source_id 对应的 API 采集器。

        支持:
            geo.acled, geo.gdelt, geo.usgs, geo.nasa_firms,
            military.opensky, market.coingecko,
            cyber.feodo, cyber.urlhaus
        """
        task = CrawlerTask("api", source_ids=[source_id], params=kwargs)
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        self._tasks[task.task_id] = task

        self._emit({"event": "task_start", "task_id": task.task_id, "type": "api", "source_id": source_id})

        raw_data: list[dict] = []
        meta: dict = {}

        try:
            if source_id in ("geo.acled", "global.conflict.acled"):
                if not self._acled:
                    self._acled = ACLEDAdapter()
                raw_data = await self._acled.fetch_recent(**kwargs)

            elif source_id in ("geo.gdelt", "global.conflict.gdelt"):
                if not self._gdelt:
                    self._gdelt = GDELTAdapter()
                raw_data = await self._gdelt.fetch_latest_events()

            elif source_id in ("geo.usgs", "global.disaster.usgs"):
                if not self._usgs:
                    self._usgs = USGSAdapter()
                raw_data = await self._usgs.fetch_recent(**kwargs)

            elif source_id in ("geo.nasa_firms", "global.disaster.nasa_firms"):
                if not self._nasa:
                    self._nasa = NASAFIRMSAdapter()
                raw_data = await self._nasa.fetch_active_fires(**kwargs)

            elif source_id in ("military.opensky", "global.military.opensky"):
                if not self._opensky:
                    self._opensky = OpenSkyAdapter()
                states = await self._opensky.fetch_all_states(**kwargs)
                raw_data = states  # list[list] → pipeline handles it

            elif source_id in ("market.coingecko", "economy.crypto.coingecko"):
                if not self._coingecko:
                    self._coingecko = CoinGeckoAdapter()
                coin_ids = kwargs.get("coin_ids")
                prices = await self._coingecko.fetch_prices(coin_ids)
                # prices: {coin_id: {usd: ..., ...}} → expand
                raw_data = [{"coin_id": cid, **price_data} for cid, price_data in prices.items()]
                meta = {"multi_coin": True}

            elif source_id in ("cyber.feodo", "tech.cyber.feodo"):
                if not self._feodo:
                    self._feodo = FeodoAdapter()
                raw_data = await self._feodo.fetch_c2_list()

            elif source_id in ("cyber.urlhaus", "tech.cyber.urlhaus"):
                if not self._urlhaus:
                    self._urlhaus = URLhausAdapter()
                raw_data = await self._urlhaus.fetch_recent(**kwargs)

            elif source_id in ("economy.stock.country_index", "economy.stock.sector_summary", "economy.stock.yfinance_us"):
                from crawler_engine.api_adapters.extended_adapters import YahooFinanceAdapter
                adapter = YahooFinanceAdapter()
                symbols = kwargs.get("symbols")
                raw_data = await adapter.fetch_indices(symbols)
                meta = {"multi_item": True, "yahoo_chart": True}

            elif source_id == "economy.futures.commodity_quotes":
                from crawler_engine.api_adapters.extended_adapters import YahooFinanceAdapter
                adapter = YahooFinanceAdapter()
                raw_data = await adapter.fetch_commodities()
                meta = {"multi_item": True, "yahoo_chart": True}

            elif source_id == "economy.quant.fear_greed_index":
                from crawler_engine.api_adapters.extended_adapters import FearGreedAdapter
                adapter = FearGreedAdapter()
                raw_data = await adapter.fetch(limit=1)
                meta = {"multi_item": True}

            elif source_id == "economy.quant.mempool_hashrate":
                from crawler_engine.api_adapters.extended_adapters import BtcHashrateAdapter
                adapter = BtcHashrateAdapter()
                data = await adapter.fetch()
                raw_data = data.get("hashrates", [])
                meta = {"multi_item": True}

            elif source_id == "academic.huggingface.papers":
                from crawler_engine.api_adapters.extended_adapters import HuggingFaceAdapter
                adapter = HuggingFaceAdapter()
                raw_data = await adapter.fetch(limit=30)
                meta = {"multi_item": True}
                
            elif source_id == "academic.semantic_scholar.trending":
                from crawler_engine.api_adapters.extended_adapters import SemanticScholarAdapter
                adapter = SemanticScholarAdapter()
                raw_data = await adapter.fetch_trending(query="AI", limit=30)
                meta = {"multi_item": True}

            else:
                logger.warning(f"CrawlerEngine: 未知 source_id={source_id}")

            task.items_fetched = len(raw_data)

            # 特殊处理 coingecko/yahoo — 每个项分别对齐
            if source_id in ("market.coingecko", "economy.crypto.coingecko") and meta.get("multi_coin"):
                all_items: list[CanonicalItem] = []
                for row in raw_data:
                    coin_id = row.pop("coin_id", "unknown")
                    items = await self._pipeline.align_and_save(source_id, [row], meta={"coin_id": coin_id}, db_session=db_session)
                    all_items.extend(items)
            
            elif meta.get("yahoo_chart") and meta.get("multi_item"):
                all_items: list[CanonicalItem] = []
                for row in raw_data:
                    symbol = row.pop("symbol", "unknown")
                    items = await self._pipeline.align_and_save(source_id, [row], meta={"symbol": symbol}, db_session=db_session)
                    all_items.extend(items)

            elif meta.get("multi_item"):
                all_items: list[CanonicalItem] = []
                for row in raw_data:
                    items = await self._pipeline.align_and_save(source_id, [row], meta=meta, db_session=db_session)
                    all_items.extend(items)

            else:
                all_items = await self._pipeline.align_and_save(source_id, raw_data, meta, db_session=db_session)

            task.items_aligned = len(all_items)
            task.status = "done"
            logger.info(f"CrawlerEngine API {source_id}: {task.items_fetched} → {task.items_aligned}")

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            all_items = []
            logger.error(f"CrawlerEngine API {source_id} 失败: {e}")
        finally:
            task.finished_at = datetime.now(timezone.utc)
            if db_session:
                try:
                    task_model = CrawlTaskModel(
                        task_id=task.task_id,
                        source_id=source_id,
                        task_type="api",
                        params=kwargs,
                        status=task.status,
                        items_fetched=task.items_fetched,
                        items_aligned=task.items_aligned,
                        error_message=task.error_message,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                    db_session.add(task_model)
                    await db_session.commit()
                except Exception as e:
                    logger.error(f"Failed to save CrawlTask to DB: {e}")

            self._emit({
                "event": "task_done",
                "task_id": task.task_id,
                "source_id": source_id,
                "status": task.status,
                "items_fetched": task.items_fetched,
                "items_aligned": task.items_aligned,
            })

        return all_items

    # ─── 扩展 API 采集 ────────────────────────────────────

    async def run_custom_adapter(self, source_id: str, fetch_func: Callable, db_session: Optional[AsyncSession] = None) -> list[CanonicalItem]:
        """
        运行自定义数据源并追踪为爬虫任务。
        fetch_func 为异步包装函数，返回 list[CanonicalItem]。
        """
        task = CrawlerTask("api", source_ids=[source_id], params={"custom": True})
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        self._tasks[task.task_id] = task

        self._emit({"event": "task_start", "task_id": task.task_id, "type": "api", "source_id": source_id})

        all_items: list[CanonicalItem] = []
        try:
            all_items = await fetch_func()
            task.items_fetched = len(all_items)
            task.items_aligned = len(all_items)
            task.status = "done"
            logger.info(f"CrawlerEngine Custom Adapter {source_id}: {task.items_aligned} aligned")
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            logger.error(f"CrawlerEngine Custom Adapter {source_id} 失败: {e}")
        finally:
            task.finished_at = datetime.now(timezone.utc)
            if db_session:
                try:
                    task_model = CrawlTaskModel(
                        task_id=task.task_id,
                        source_id=source_id,
                        task_type="api",
                        params={"custom": True},
                        status=task.status,
                        items_fetched=task.items_fetched,
                        items_aligned=task.items_aligned,
                        error_message=task.error_message,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                    db_session.add(task_model)
                    await db_session.commit()
                except Exception as e:
                    logger.error(f"Failed to save CrawlTask to DB: {e}")

            self._emit({
                "event": "task_done",
                "task_id": task.task_id,
                "source_id": source_id,
                "status": task.status,
                "items_fetched": task.items_fetched,
                "items_aligned": task.items_aligned,
            })

        return all_items

    # ─── 热搜采集 (BettaFish NewsNow) ────────────────────────

    async def run_hotsearch(
        self,
        source_ids: Optional[list[str]] = None,
        db_session: Optional[AsyncSession] = None,
    ) -> list[CanonicalItem]:
        """
        采集 BettaFish NewsNow 聚合热搜数据并对齐。

        Args:
            source_ids: 要拉取的 hotsearch.* 列表，默认全部 12 个
        """
        if not self._newsnow:
            self._newsnow = NewsNowAdapter()

        task = CrawlerTask("hotsearch", source_ids=source_ids or [], params={})
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        self._tasks[task.task_id] = task
        self._emit({"event": "task_start", "task_id": task.task_id, "type": "hotsearch"})

        all_items: list[CanonicalItem] = []
        try:
            batch = await self._newsnow.fetch_all(source_ids)

            # --- Github Trending Dual-Stage Enrichment Injection ---
            if "tech.oss.github_trending" in batch:
                github_items = batch["tech.oss.github_trending"].get("items", [])
                if github_items:
                    from crawler_engine.api_adapters.github_adapter import GithubAdapter
                    adapter = GithubAdapter()
                    enriched_items = await adapter.enrichen_trending_repos(github_items)
                    batch["tech.oss.github_trending"]["items"] = enriched_items
            # ---------------------------------------------------------

            task.items_fetched = sum(len(v.get("items", [])) for v in batch.values())

            for sid, response in batch.items():
                items = await self._pipeline.align_and_save(
                    source_id=sid,
                    raw_data=[response],   # pipeline expects list[dict]
                    meta={},
                    db_session=db_session,
                )
                all_items.extend(items)

            task.items_aligned = len(all_items)
            task.status = "done"
            logger.info(
                f"CrawlerEngine HotSearch: {len(batch)} sources, "
                f"{task.items_fetched} fetched → {task.items_aligned} aligned"
            )
        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            logger.error(f"CrawlerEngine HotSearch 失败: {e}")
        finally:
            task.finished_at = datetime.now(timezone.utc)
            if db_session:
                try:
                    task_model = CrawlTaskModel(
                        task_id=task.task_id,
                        source_id="hotsearch.all" if not source_ids else ",".join(source_ids),
                        task_type="hotsearch",
                        params={},
                        status=task.status,
                        items_fetched=task.items_fetched,
                        items_aligned=task.items_aligned,
                        error_message=task.error_message,
                        started_at=task.started_at,
                        finished_at=task.finished_at,
                    )
                    db_session.add(task_model)
                    await db_session.commit()
                except Exception as e:
                    logger.error(f"Failed to save CrawlTask to DB: {e}")

            self._emit({
                "event": "task_done",
                "task_id": task.task_id,
                "status": task.status,
                "items_fetched": task.items_fetched,
                "items_aligned": task.items_aligned,
            })

        return all_items

    # ─── 全量采集 (all sources) ───────────────────────────────

    async def run_all(self, db_session: Optional[AsyncSession] = None) -> dict[str, list[CanonicalItem]]:
        """并发运行所有 API 数据源采集（不含 Playwright 社交爬虫）"""
        api_sources = [
            "geo.usgs", "geo.gdelt", "geo.nasa_firms",
            "military.opensky", "market.coingecko",
            "cyber.feodo", "cyber.urlhaus",
        ]
        results: dict[str, list[CanonicalItem]] = {}

        async def _run(sid: str):
            results[sid] = await self.run_api(sid, db_session=db_session)

        await asyncio.gather(*[_run(sid) for sid in api_sources], return_exceptions=True)
        results["rss"] = await self.run_rss(db_session=db_session)
        results["hotsearch"] = await self.run_hotsearch(db_session=db_session)
        return results

    # ─── 任务状态查询 ────────────────────────────────────────

    def get_task(self, task_id: str) -> Optional[dict]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task.task_id,
            "task_type": task.task_type,
            "source_ids": task.source_ids,
            "status": task.status,
            "items_fetched": task.items_fetched,
            "items_aligned": task.items_aligned,
            "error_message": task.error_message,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        }

    def list_tasks(self) -> list[dict]:
        return [self.get_task(tid) for tid in list(self._tasks.keys())[-50:]]
