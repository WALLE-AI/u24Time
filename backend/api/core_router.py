# -*- coding: utf-8 -*-
"""
U24Time Backend — FastAPI Core Router
迁移了原版 Flask main.py 的所有路由和爬虫/调度交互功能。
"""

import asyncio
import json
from typing import Optional, Any, Callable
from loguru import logger
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Request, Query, Body, HTTPException, Response

from sse_starlette.sse import EventSourceResponse

from crawler_engine.engine import CrawlerEngine
from data_source.registry import registry
from db.session import get_async_session, get_sync_session
from utils.llm_client import LLMClient
from scheduler import DataScheduler

router = APIRouter()

# ─── 全局对象 ─────────────────────────────────────────────────

_engine = CrawlerEngine()
_llm = LLMClient()
_sse_clients: list[asyncio.Queue] = []

# DataScheduler 初始化
_scheduler = DataScheduler(
    engine=_engine,
    db_session_factory=get_async_session,
    broadcast_cb=None,
)

_HIGH_PRIORITY_EVENTS = {"scheduler_done", "connected", "health_check_done", "full_crawl_complete"}

def _broadcast(event: dict):
    """向所有 SSE 客户端广播消息（P1-B: 分级投递）"""
    event_type = event.get("event", "")
    dead = []
    # 如果并不在事件循环中（多线程上下文调用），则丢给 loop，否则直接调用
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No running event loop for _broadcast, skipping.")
        return

    def _do_broadcast():
        for q in _sse_clients:
            try:
                if event_type in _HIGH_PRIORITY_EVENTS:
                    q.put_nowait(event)
                else:
                    if q.qsize() < q.maxsize:
                        q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            if q in _sse_clients:
                _sse_clients.remove(q)
                
    loop.call_soon_threadsafe(_do_broadcast)


_engine.set_progress_callback(_broadcast)
_scheduler._broadcast = _broadcast

# 在 server.py 会导出并调用
def start_core_scheduler():
    try:
        if not _scheduler.status().get("running", False):
            _scheduler.start()
            logger.info("DataScheduler: 原生 ASGI 启动成功")
    except Exception as e:
        logger.error(f"DataScheduler 启动失败: {e}")

def stop_core_scheduler():
    _scheduler.shutdown()

# ─── 通用响应工具 ─────────────────────────────────────────────

def ok(data: Any = None, msg: str = "ok", **kwargs) -> dict:
    resp = {"success": True, "msg": msg}
    if data is not None:
        resp["data"] = data
    resp.update(kwargs)
    return resp

def err(msg: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail={"success": False, "msg": msg})

# ══════════════════════════════════════════════════════════════
# Stream / EventSource
# ══════════════════════════════════════════════════════════════

@router.get("/stream", summary="SSE 事件流")
async def sse_stream(request: Request):
    """EventSource SSE 端点"""
    client_q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_clients.append(client_q)

    # 发送连接成功事件
    await client_q.put({"event": "connected", "msg": "U24Time SSE connected"})

    async def _generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(client_q.get(), timeout=15.0)
                    yield json.dumps(event, ensure_ascii=False)
                except asyncio.TimeoutError:
                    # keep-alive ping
                    yield "keep-alive"
        finally:
            if client_q in _sse_clients:
                _sse_clients.remove(client_q)

    return EventSourceResponse(_generate())

# ══════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════

@router.get("/health", tags=["System"])
def health():
    return ok(msg="U24Time Backend is running")

# ══════════════════════════════════════════════════════════════
# Scheduler Routes
# ══════════════════════════════════════════════════════════════

@router.get("/api/v1/scheduler/status", tags=["Scheduler"])
def scheduler_status():
    return ok(data=_scheduler.status())

@router.post("/api/v1/scheduler/trigger/{source_id:path}", tags=["Scheduler"])
def scheduler_trigger(source_id: str):
    from scheduler import SOURCE_SCHEDULE
    if source_id not in SOURCE_SCHEDULE and source_id not in [
        "geo.usgs", "geo.acled", "geo.gdelt", "geo.nasa_firms",
        "military.opensky", "cyber.feodo", "cyber.urlhaus", "market.coingecko",
    ]:
        err(f"Unknown source_id: {source_id}", 404)
    _scheduler.trigger(source_id)
    return ok(msg=f"Triggered {source_id} — watch /stream for results")

@router.post("/api/v1/scheduler/trigger-all", tags=["Scheduler"])
def scheduler_trigger_all():
    _scheduler.trigger_all_now()
    return ok(msg=f"Full refresh triggered for {len(_scheduler.status()['total_jobs'])} sources")

# ══════════════════════════════════════════════════════════════
# DataSource Routes
# ══════════════════════════════════════════════════════════════

@router.get("/api/v1/sources", tags=["Sources"])
def list_sources(type: Optional[str] = Query(None)):
    if type:
        sources = registry.by_type(type)
    else:
        sources = registry.all()

    return ok(
        data=[
            {
                "source_id": s.source_id,
                "name": s.name,
                "source_type": s.source_type,
                "crawl_method": s.crawl_method,
                "status": s.status,
                "api_key_required": s.api_key_required,
                "is_enabled": s.is_enabled,
                "description": s.description,
                "tags": s.tags,
                "last_checked": s.last_checked.isoformat() if s.last_checked else None,
                "last_latency_ms": s.last_latency_ms,
            }
            for s in sources
        ],
        total=len(sources),
    )

@router.get("/api/v1/sources/health", tags=["Sources"])
async def sources_health():
    async def _check():
        summary = await registry.check_all_health()
        _broadcast({"event": "health_check_done", "summary": summary})
    asyncio.create_task(_check())
    return ok(msg="Health check started, results will stream via SSE")

@router.get("/api/v1/sources/{source_id}/health", tags=["Sources"])
async def source_health(source_id: str):
    source = registry.get(source_id)
    if not source:
        err(f"Source '{source_id}' not found", 404)
    async def _check():
        status = await registry.check_health(source_id)
        _broadcast({"event": "source_health", "source_id": source_id, "status": status})
    asyncio.create_task(_check())
    return ok(msg=f"Health check for {source_id} started")

# ══════════════════════════════════════════════════════════════
# Crawl Routes
# ══════════════════════════════════════════════════════════════

@router.post("/api/v1/crawl/rss", tags=["Crawl"])
async def crawl_rss(body: dict = Body(default={})):
    category = body.get("category")
    feed_ids = body.get("feed_ids")

    async def _run():
        async with get_async_session() as session:
            items = await _engine.run_rss(category=category, feed_ids=feed_ids, db_session=session)
            _broadcast({
                "event": "rss_complete",
                "category": category,
                "items_count": len(items),
            })
    asyncio.create_task(_run())
    return ok(msg="RSS crawl task started", category=category)


@router.post("/api/v1/crawl/api", tags=["Crawl"])
async def crawl_api(body: dict = Body(default={})):
    source_id = body.get("source_id")
    params = body.get("params", {})

    if not source_id:
        err("source_id is required")
    if not registry.get(source_id):
        err(f"Unknown source_id: {source_id}", 404)

    async def _run():
        async with get_async_session() as session:
            items = await _engine.run_api(source_id, db_session=session, **params)
            _broadcast({
                "event": "api_crawl_complete",
                "source_id": source_id,
                "items_count": len(items),
            })
    asyncio.create_task(_run())
    return ok(msg=f"API crawl task started for {source_id}", source_id=source_id)

@router.post("/api/v1/crawl/all", tags=["Crawl"])
async def crawl_all():
    async def _run():
        async with get_async_session() as session:
            results = await _engine.run_all(db_session=session)
            total = sum(len(v) for v in results.values())
            _broadcast({"event": "full_crawl_complete", "total_items": total})
    asyncio.create_task(_run())
    return ok(msg="Full crawl started")

@router.post("/api/v1/crawl/hotsearch", tags=["Crawl"])
async def crawl_hotsearch(body: dict = Body(default={})):
    source_ids = body.get("source_ids")

    async def _run():
        async with get_async_session() as session:
            items = await _engine.run_hotsearch(source_ids=source_ids, db_session=session)
            _broadcast({
                "event": "hotsearch_complete",
                "sources_count": len(set(i.source_id for i in items)) if items else 0,
                "items_count": len(items),
            })
    asyncio.create_task(_run())
    return ok(
        msg="HotSearch crawl started (BettaFish NewsNow)",
        source_ids=source_ids or "all",
    )

@router.get("/api/v1/crawl/tasks", tags=["Crawl"])
def crawl_tasks():
    try:
        from db.models import CrawlTaskModel
        from sqlalchemy import select, desc

        def _iso(dt):
            if not dt: return None
            return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()

        with get_sync_session() as session:
            stmt = select(CrawlTaskModel).order_by(desc(CrawlTaskModel.started_at)).limit(100)
            rows = session.scalars(stmt).all()
            if rows:
                return ok(data=[{
                    "task_id": r.task_id,
                    "task_type": r.task_type,
                    "source_id": r.source_id,
                    "source_ids": [r.source_id],
                    "status": r.status,
                    "items_fetched": r.items_fetched,
                    "items_aligned": r.items_aligned,
                    "error_message": r.error_message,
                    "started_at": _iso(r.started_at),
                    "finished_at": _iso(r.finished_at),
                } for r in rows])
    except Exception as e:
        logger.warning(f"DB query for crawl_tasks failed, falling back to memory: {e}")

    return ok(data=_engine.list_tasks())

@router.get("/api/v1/crawl/tasks/{task_id}", tags=["Crawl"])
def crawl_task_detail(task_id: str):
    task = _engine.get_task(task_id)
    if not task:
        err(f"Task '{task_id}' not found", 404)
    return ok(data=task)


# ══════════════════════════════════════════════════════════════
# Items / Data Read Routes
# ══════════════════════════════════════════════════════════════

@router.get("/api/v1/items", tags=["Data"])
def list_items(
    limit: int = Query(50),
    page: int = Query(1),
    domain: Optional[str] = Query(None),
    sub_domain: Optional[str] = Query(None),
    sort: str = Query("time"),
    last_24h: str = Query("false"),
    source_id: Optional[str] = Query(None)
):
    last_24h_bool = last_24h.lower() == "true"
    page = max(1, page)
    
    try:
        from db.models import CanonicalItemModel
        from sqlalchemy import select, desc, func

        with get_sync_session() as session:
            stmt = select(CanonicalItemModel)
            
            if last_24h_bool:
                yesterday = datetime.now(timezone.utc) - timedelta(days=1)
                stmt = stmt.where(CanonicalItemModel.crawled_at >= yesterday)

            if domain and domain != "all":
                if domain == "global":
                    stmt = stmt.where(CanonicalItemModel.domain.in_(["global", None, ""]))
                else:
                    stmt = stmt.where(CanonicalItemModel.domain == domain)
            
            if sub_domain and sub_domain != "all":
                stmt = stmt.where(CanonicalItemModel.sub_domain == sub_domain)
                
            if source_id:
                stmt = stmt.where(CanonicalItemModel.source_id == source_id)

            if sort == "heat":
                stmt = stmt.order_by(desc(CanonicalItemModel.hotness_score), desc(CanonicalItemModel.crawled_at))
            else:
                stmt = stmt.order_by(desc(CanonicalItemModel.crawled_at))

            stmt = stmt.offset((page - 1) * limit).limit(limit)
            rows = session.scalars(stmt).all()
            
            count_stmt = select(func.count(CanonicalItemModel.item_id))
            if domain and domain != "all":
                if domain == "global":
                    count_stmt = count_stmt.where(CanonicalItemModel.domain.in_(["global", None, ""]))
                else:
                    count_stmt = count_stmt.where(CanonicalItemModel.domain == domain)
            if sub_domain and sub_domain != "all":
                count_stmt = count_stmt.where(CanonicalItemModel.sub_domain == sub_domain)
            if source_id:
                count_stmt = count_stmt.where(CanonicalItemModel.source_id == source_id)
            total = session.scalar(count_stmt)
            
            def _format_db_dt(dt):
                if not dt: return None
                return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()

            items_list = [
                {
                    "item_id": r.item_id,
                    "source_id": r.source_id,
                    "source_type": r.source_type,
                    "title": r.title,
                    "url": r.url,
                    "published_at": _format_db_dt(r.published_at),
                    "hotness_score": r.hotness_score,
                    "severity_level": r.severity_level,
                    "geo_lat": r.geo_lat,
                    "geo_lon": r.geo_lon,
                    "geo_country": r.geo_country,
                    "categories": r.categories,
                    "domain": r.domain,
                    "sub_domain": r.sub_domain,
                    "crawled_at": _format_db_dt(r.crawled_at),
                }
                for r in rows
            ]
            
        return ok(data=items_list, total=total, page=page, limit=limit)
    except Exception as e:
        logger.error(f"API List Items: DB 查询异常 → {e}")
        err(f"Database error: {str(e)}", 500)


@router.get("/api/v1/newsflash", tags=["Data"])
def get_newsflash(limit: int = 8, domain: Optional[str] = Query(None)):
    from memory_cache import news_flash_cache
    
    domain_map = {
        "全球监控": "global", "global": "global",
        "经济": "economy", "economy": "economy",
        "技术": "technology", "technology": "technology",
        "学术": "academic", "academic": "academic",
        "娱乐": "entertainment", "entertainment": "entertainment"
    }
    if domain:
        domain = domain_map.get(domain, domain).lower()
    
    cache_list = list(news_flash_cache)
    
    if domain and domain != "all":
        filtered = []
        for item in cache_list:
            d = item.get("domain")
            if domain == "global" and (not d or d == "global"):
                filtered.append(item)
            elif d == domain:
                filtered.append(item)
    else:
        filtered = cache_list
        
    return ok(data=filtered[:limit], total=len(filtered))


@router.get("/api/v1/domains", tags=["Domains"])
def list_domains():
    summary = registry.domain_summary()
    domain_meta = {
        "economy":    {"emoji": "💹", "name": "Economy",          "name_cn": "经济"},
        "technology": {"emoji": "💻", "name": "Technology",       "name_cn": "技术"},
        "academic":   {"emoji": "🎓", "name": "Academic",         "name_cn": "学术"},
        "global":     {"emoji": "🌍", "name": "Global Monitoring","name_cn": "全球监控"},
    }
    result = []
    for domain, stats in summary.items():
        meta = domain_meta.get(domain, {"emoji": "📦", "name": domain, "name_cn": domain})
        result.append({
            "domain": domain,
            **meta,
            "source_count": stats["count"],
            "sub_domains": stats["sub_domains"],
        })
    return ok(domains=result, total_sources=len(registry.all()))


@router.get("/api/v1/domains/activity", tags=["Domains"])
def domain_activity():
    try:
        from db.models import CanonicalItemModel
        from sqlalchemy import select, func

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        CN_SOURCES = {
            "hotsearch.weibo", "hotsearch.zhihu", "hotsearch.bilibili",
            "hotsearch.douyin", "hotsearch.tieba", "hotsearch.toutiao",
            "hotsearch.xueqiu", "hotsearch.wallstreetcn", "hotsearch.cls",
            "hotsearch.thepaper", "hotsearch.coolapk",
            "global.social.weibo_newsnow", "global.social.zhihu_newsnow",
            "global.social.bilibili_newsnow", "global.social.douyin_newsnow",
            "global.social.tieba_newsnow", "global.diplomacy.thepaper",
            "economy.stock.wallstreetcn", "economy.stock.cls_hot",
            "economy.stock.xueqiu", "tech.oss.coolapk",
        }
        US_SOURCES = {
            "tech.oss.hackernews", "tech.oss.techcrunch", "tech.oss.github_trending",
            "tech.oss.trending_repos", "tech.oss.toutiao_tech",
            "tech.infra.cloud_aws", "tech.infra.cloud_cloudflare",
            "tech.infra.cloud_gcp", "tech.infra.cloud_vercel",
            "tech.infra.dev_github", "tech.infra.dev_npm",
            "tech.infra.comm_slack", "tech.infra.comm_discord",
            "tech.infra.saas_stripe", "tech.ai.openai_status",
            "tech.ai.anthropic_status", "tech.ai.replicate_status",
            "tech.cyber.nvd_cve", "tech.cyber.feodo", "tech.cyber.urlhaus",
            "economy.stock.yfinance_us",
        }
        GLOBAL_SOURCES_PREFIX = (
            "academic.", "economy.crypto.", "economy.quant.",
            "economy.futures.", "economy.trade.",
            "global.conflict.", "global.disaster.",
            "global.displacement.", "global.military.",
        )

        def _classify_source(sid: str, geo_country: str | None) -> str:
            if sid in CN_SOURCES: return "CN"
            if sid in US_SOURCES: return "US"
            if geo_country and geo_country not in ("CN", "US"): return geo_country
            if geo_country == "CN": return "CN"
            if geo_country == "US": return "US"
            for prefix in GLOBAL_SOURCES_PREFIX:
                if sid.startswith(prefix):
                    return "Global"
            return "Global"

        with get_sync_session() as session:
            total_stmt = (
                select(CanonicalItemModel.domain, func.count().label("total"))
                .where(CanonicalItemModel.domain.isnot(None))
                .group_by(CanonicalItemModel.domain)
            )
            totals = {row.domain: row.total for row in session.execute(total_stmt).all()}

            recent_stmt = (
                select(CanonicalItemModel.domain, func.count().label("recent"))
                .where(CanonicalItemModel.domain.isnot(None), CanonicalItemModel.crawled_at >= cutoff)
                .group_by(CanonicalItemModel.domain)
            )
            recents = {row.domain: row.recent for row in session.execute(recent_stmt).all()}

            geo_stmt = (
                select(
                    CanonicalItemModel.domain, CanonicalItemModel.source_id,
                    CanonicalItemModel.geo_country, func.count().label("n"),
                )
                .where(CanonicalItemModel.domain.isnot(None))
                .group_by(
                    CanonicalItemModel.domain, CanonicalItemModel.source_id, CanonicalItemModel.geo_country,
                )
            )
            geo_rows = session.execute(geo_stmt).all()

        domain_geo = {}
        for row in geo_rows:
            d = row.domain or ""
            if not d: continue
            region = _classify_source(row.source_id, row.geo_country)
            domain_geo.setdefault(d, {})
            domain_geo[d][region] = domain_geo[d].get(region, 0) + row.n

        def _compact_geo(raw: dict) -> dict:
            total_n = sum(raw.values()) or 1
            result = {}
            others = 0
            for k, v in sorted(raw.items(), key=lambda x: -x[1]):
                if k in ("CN", "US", "Global") or v / total_n >= 0.02:
                    result[k] = v
                else:
                    others += v
            if others:
                result["Other"] = result.get("Other", 0) + others
            return result

        _DOMAIN_ALIAS = {"tech": "technology"}
        domain_last_updated = {}
        for sid, ts in _scheduler._last_success.items():
            raw = sid.split(".")[0]
            domain = _DOMAIN_ALIAS.get(raw, raw)
            iso = ts.isoformat()
            if domain not in domain_last_updated or iso > domain_last_updated[domain]:
                domain_last_updated[domain] = iso

        domains = ["global", "economy", "technology", "academic", "entertainment"]
        result = [
            {
                "domain": d,
                "total_items": totals.get(d, 0),
                "recent_items": recents.get(d, 0),
                "last_updated": domain_last_updated.get(d),
                "geo_distribution": _compact_geo(domain_geo.get(d, {})),
            }
            for d in domains
        ]
        return ok(data=result)

    except Exception as e:
        logger.warning(f"/api/v1/domains/activity 查询失败: {e}")
        return ok(data=[
            {"domain": d, "total_items": 0, "recent_items": 0, "last_updated": None, "geo_distribution": {}}
            for d in ["global", "economy", "technology", "academic"]
        ])


@router.get("/api/v1/domains/{domain}/sources", tags=["Domains"])
def domain_sources(domain: str):
    sources = registry.by_domain(domain)
    if not sources:
        err(f"Domain '{domain}' not found or has no sources", 404)
    return ok(
        domain=domain,
        sources=[
            {
                "source_id": s.source_id,
                "name": s.name,
                "sub_domain": s.sub_domain,
                "source_type": s.source_type,
                "crawl_method": s.crawl_method,
                "is_enabled": s.is_enabled,
                "status": s.status,
                "tags": s.tags,
            }
            for s in sources
        ],
        count=len(sources),
    )


@router.get("/api/v1/domains/{domain}/items", tags=["Domains"])
def domain_items(domain: str, limit: int = Query(50), offset: int = Query(0)):
    limit = min(limit, 200)
    try:
        from db import get_db
        db = get_db()
        items = db.query_items_by_domain(domain=domain, limit=limit, offset=offset)
        return ok(domain=domain, items=[i.to_dict() for i in items], count=len(items))
    except Exception as e:
        logger.warning(f"DB not available for domain query: {e}")
        return ok(domain=domain, items=[], count=0, note="DB not available")


@router.get("/api/v1/domains/{domain}/{sub}/items", tags=["Domains"])
def sub_domain_items(domain: str, sub: str, limit: int = Query(50), offset: int = Query(0)):
    limit = min(limit, 200)
    try:
        from db import get_db
        db = get_db()
        items = db.query_items_by_domain(domain=domain, sub_domain=sub, limit=limit, offset=offset)
        return ok(domain=domain, sub_domain=sub, items=[i.to_dict() for i in items], count=len(items))
    except Exception as e:
        return ok(domain=domain, sub_domain=sub, items=[], count=0, note="DB not available")


@router.post("/api/v1/crawl/domain/{domain}", tags=["Crawl"])
def crawl_domain(domain: str):
    sources = registry.by_domain(domain)
    if not sources:
        err(f"Domain '{domain}' not found or has no sources", 404)

    enabled = [s for s in sources if s.is_enabled]
    if not enabled:
        err(f"No enabled sources in domain '{domain}'", 400)

    launched = [s.source_id for s in enabled]
    for source in enabled:
        try:
            _scheduler.trigger(source.source_id)
        except Exception as e:
            logger.warning(f"Failed to trigger {source.source_id}: {e}")

    return ok(msg=f"Domain crawl launched for '{domain}'", domain=domain, launched=launched, total=len(launched))


@router.post("/api/v1/ai/summary", tags=["AI"])
async def ai_summary(domain: Optional[str] = Query(None), limit: int = Query(40), body: dict = Body(default={})):
    domain = body.get("domain") or domain
    limit_val = int(body.get("limit") or limit)
    
    if domain and domain != "all":
        limit_val = max(limit_val, 80)
    limit_val = min(limit_val, 150)
    
    domain_groups = {}
    try:
        from db.models import CanonicalItemModel
        from sqlalchemy import select, desc
        with get_sync_session() as session:
            stmt = select(CanonicalItemModel).order_by(desc(CanonicalItemModel.hotness_score), desc(CanonicalItemModel.crawled_at))
            if domain and domain != "all":
                stmt = stmt.where(CanonicalItemModel.domain == domain)
            stmt = stmt.limit(limit_val)
            rows = session.scalars(stmt).all()
            
            for r in rows:
                d = r.domain or "other"
                if d not in domain_groups:
                    domain_groups[d] = []
                domain_groups[d].append({
                    "title": r.title,
                    "body": r.body,
                    "source_id": r.source_id,
                    "hotness": r.hotness_score
                })
    except Exception as e:
        err(f"Database error: {str(e)}", 500)

    if not domain_groups:
        err(f"No items available for domain '{domain or 'all'}' summarization", 400)

    summary = await _llm.generate_summary(domain_groups, target_domain=domain)
    return ok(summary=summary, domains_count=len(domain_groups))
