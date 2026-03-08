# -*- coding: utf-8 -*-
"""
U24Time Backend — Flask Application Entry Point

Routes:
    GET  /health                     — 服务健康检查
    GET  /api/v1/sources             — 所有数据源状态
    POST /api/v1/crawl/rss           — 触发 RSS 采集任务
    POST /api/v1/crawl/api           — 触发 API 数据源采集任务
    GET  /api/v1/crawl/tasks         — 任务列表
    GET  /api/v1/crawl/tasks/<id>    — 单任务状态
    GET  /api/v1/items               — 查询 CanonicalItem（分页）
    GET  /stream                     — SSE 事件流
"""

from __future__ import annotations

import asyncio
import json
import queue
import threading
from functools import wraps
from typing import Optional

from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from loguru import logger

from config import settings
from crawler_engine.engine import CrawlerEngine
from data_source.registry import registry
from db.session import get_async_session
from utils.llm_client import LLMClient
from scheduler import DataScheduler


# ─── Flask App 初始化 ──────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = settings.SECRET_KEY
CORS(app, origins="*")

# ─── 全局对象 ─────────────────────────────────────────────────

_engine = CrawlerEngine()
_llm = LLMClient()
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

# DataScheduler 初始化（借鉴 WorldMonitor 分层 TTL 策略）
_scheduler = DataScheduler(
    engine=_engine,
    db_session_factory=None,   # 将在 App 启动后通过 _start_scheduler() 注入
    broadcast_cb=None,         # SSE 回调将在下方注入
)


# 高优先级事件：必须投递，Queue.Full 才踢客户端
_HIGH_PRIORITY_EVENTS = {"scheduler_done", "connected", "health_check_done", "full_crawl_complete"}

def _broadcast(event: dict):
    """向所有 SSE 客户端广播消息（P1-B: 分级投递，防止 Queue.Full 误踢客户端）"""
    event_type = event.get("event", "")
    with _sse_lock:
        dead: list[queue.Queue] = []
        for q in _sse_clients:
            try:
                if event_type in _HIGH_PRIORITY_EVENTS:
                    q.put_nowait(event)          # 重要事件：必须投递
                else:
                    if not q.full():             # 低优先级：满了直接丢弃，不踢客户端
                        q.put_nowait(event)
            except queue.Full:
                # 只有高优先级事件 Full 才认为客户端真的死了
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/stream")
def sse_stream():
    """SSE 事件流端点"""
    client_q: queue.Queue = queue.Queue(maxsize=200)  # P1-B: 50 → 200，减少背压丢包
    with _sse_lock:
        _sse_clients.append(client_q)

    def _generate():
        yield _format_sse({"event": "connected", "msg": "U24Time SSE connected"})
        try:
            while True:
                try:
                    event = client_q.get(timeout=30)
                    yield _format_sse(event)
                except queue.Empty:
                    yield ": keep-alive\n\n"
        except GeneratorExit:
            with _sse_lock:
                if client_q in _sse_clients:
                    _sse_clients.remove(client_q)

    return Response(
        stream_with_context(_generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ─── 注入 SSE 回调到 CrawlerEngine 和 Scheduler ───────────
_engine.set_progress_callback(_broadcast)
_scheduler._broadcast = _broadcast


# ─── 调度器启动（Flask 首次请求后自动触发）──────────────────
_scheduler_started = False


@app.before_request
def _ensure_scheduler():
    """在第一次请求时启动调度器（避免多进程 debug 模式重复启动）"""
    global _scheduler_started
    if not _scheduler_started:
        _scheduler_started = True
        try:
            # 注入异步 Session 工厂
            _scheduler._db_factory = get_async_session
            _scheduler.start()
            logger.info("DataScheduler: 首次请求后启动成功 (已注入 DB Factory)")
        except Exception as e:
            logger.error(f"DataScheduler 启动失败: {e}")


import atexit
atexit.register(_scheduler.shutdown)


# ─── 异步任务运行工具 ─────────────────────────────────────────

def _run_async(coro):
    """在独立线程的事件循环中运行异步任务（Flask 是同步的）"""
    def _thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(coro)
        finally:
            loop.close()

    t = threading.Thread(target=_thread, daemon=True)
    t.start()


# ─── 通用响应工具 ─────────────────────────────────────────────

def ok(data=None, msg="ok", **kwargs):
    resp = {"success": True, "msg": msg}
    if data is not None:
        resp["data"] = data
    resp.update(kwargs)
    return jsonify(resp)


def err(msg: str, code: int = 400):
    return jsonify({"success": False, "msg": msg}), code


# ══════════════════════════════════════════════════════════════
# Health
# ══════════════════════════════════════════════════════════════

@app.route("/health")
def health():
    return ok(msg="U24Time Backend is running")


# ══════════════════════════════════════════════════════════════
# Scheduler Routes (WorldMonitor 分层 TTL 调度管理)
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/scheduler/status")
def scheduler_status():
    """查看后台采集调度器状态（各任务下次执行时间、stale cache 信息）"""
    return ok(data=_scheduler.status())


@app.route("/api/v1/scheduler/trigger/<path:source_id>", methods=["POST"])
def scheduler_trigger(source_id: str):
    """手动立即触发指定数据源的采集任务"""
    from scheduler import SOURCE_SCHEDULE
    if source_id not in SOURCE_SCHEDULE and source_id not in [
        "geo.usgs", "geo.acled", "geo.gdelt", "geo.nasa_firms",
        "military.opensky", "cyber.feodo", "cyber.urlhaus", "market.coingecko",
    ]:
        return err(f"Unknown source_id: {source_id}. Check /api/v1/scheduler/status for valid IDs.", 404)
    _scheduler.trigger(source_id)
    return ok(msg=f"Triggered {source_id} — watch /stream for results")


@app.route("/api/v1/scheduler/trigger-all", methods=["POST"])
def scheduler_trigger_all():
    """触发全量数据刷新（谨慎使用）"""
    _scheduler.trigger_all_now()
    return ok(msg=f"Full refresh triggered for {len(_scheduler.status()['total_jobs'])} sources")


# ══════════════════════════════════════════════════════════════
# DataSource Routes
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/sources")
def list_sources():
    """返回所有注册数据源及其健康状态"""
    source_type = request.args.get("type")
    if source_type:
        sources = registry.by_type(source_type)
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


@app.route("/api/v1/sources/health")
def sources_health():
    """触发所有数据源健康检查（异步执行，结果通过 SSE 推送）"""
    async def _check():
        summary = await registry.check_all_health()
        _broadcast({"event": "health_check_done", "summary": summary})

    _run_async(_check())
    return ok(msg="Health check started, results will stream via SSE")


@app.route("/api/v1/sources/<source_id>/health")
def source_health(source_id: str):
    """检查单个数据源健康状态"""
    source = registry.get(source_id)
    if not source:
        return err(f"Source '{source_id}' not found", 404)

    async def _check():
        status = await registry.check_health(source_id)
        _broadcast({"event": "source_health", "source_id": source_id, "status": status})

    _run_async(_check())
    return ok(msg=f"Health check for {source_id} started")


# ══════════════════════════════════════════════════════════════
# Crawl Routes
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/crawl/rss", methods=["POST"])
def crawl_rss():
    """
    触发 RSS 采集任务。
    Body (JSON):
        category: str (可选) — 分类过滤，如 "geopolitical"
        feed_ids: list[str] (可选) — 指定 feed_id 列表
    """
    body = request.get_json(silent=True) or {}
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

    _run_async(_run())
    return ok(msg="RSS crawl task started", category=category)


@app.route("/api/v1/crawl/api", methods=["POST"])
def crawl_api():
    """
    触发 API 数据源采集。
    Body (JSON):
        source_id: str — 必须，如 "geo.usgs"
        params: dict  — 可选，传递给 adapter 的参数
    """
    body = request.get_json(silent=True) or {}
    source_id = body.get("source_id")
    params = body.get("params", {})

    if not source_id:
        return err("source_id is required")

    if not registry.get(source_id):
        return err(f"Unknown source_id: {source_id}", 404)

    async def _run():
        async with get_async_session() as session:
            items = await _engine.run_api(source_id, db_session=session, **params)
            _broadcast({
                "event": "api_crawl_complete",
                "source_id": source_id,
                "items_count": len(items),
            })

    _run_async(_run())
    return ok(msg=f"API crawl task started for {source_id}", source_id=source_id)


@app.route("/api/v1/crawl/all", methods=["POST"])
def crawl_all():
    """触发全量采集（所有 API 源 + RSS + 热搜）"""
    async def _run():
        async with get_async_session() as session:
            results = await _engine.run_all(db_session=session)
            total = sum(len(v) for v in results.values())
            _broadcast({"event": "full_crawl_complete", "total_items": total})

    _run_async(_run())
    return ok(msg="Full crawl started")


@app.route("/api/v1/crawl/hotsearch", methods=["POST"])
def crawl_hotsearch():
    """
    触发 BettaFish NewsNow 热搜采集。
    Body (JSON):
        source_ids: list[str] (可选) — 指定 hotsearch.* 列表，默认全部 12 个
    """
    body = request.get_json(silent=True) or {}
    source_ids = body.get("source_ids")  # Optional list like ["hotsearch.weibo", ...]

    async def _run():
        async with get_async_session() as session:
            items = await _engine.run_hotsearch(source_ids=source_ids, db_session=session)
            _broadcast({
                "event": "hotsearch_complete",
                "sources_count": len(set(i.source_id for i in items)) if items else 0,
                "items_count": len(items),
            })

    _run_async(_run())
    return ok(
        msg="HotSearch crawl started (BettaFish NewsNow)",
        source_ids=source_ids or "all",
    )




@app.route("/api/v1/crawl/tasks")
def crawl_tasks():
    """返回最近 100 条爬虫任务记录（优先从 DB 读取，内存兜底）"""
    try:
        from db.session import get_sync_session
        from db.models import CrawlTaskModel
        from sqlalchemy import select, desc

        def _iso(dt):
            if not dt: return None
            from datetime import timezone
            return dt.replace(tzinfo=timezone.utc).isoformat() if dt.tzinfo is None else dt.isoformat()

        with get_sync_session() as session:
            stmt = (
                select(CrawlTaskModel)
                .order_by(desc(CrawlTaskModel.started_at))
                .limit(100)
            )
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

    # 内存兜底（重启前的任务 or DB 不可用时）
    return ok(data=_engine.list_tasks())


@app.route("/api/v1/crawl/tasks/<task_id>")
def crawl_task_detail(task_id: str):
    """查询单条任务状态"""
    task = _engine.get_task(task_id)
    if not task:
        return err(f"Task '{task_id}' not found", 404)
    return ok(data=task)


# ══════════════════════════════════════════════════════════════
# Items Routes（查询 CanonicalItem，如有 DB 则走 DB）
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/items")
def list_items():
    """获取对齐后的数据列表 (支持按 domain 过滤，支持只看最近24小时，仅供热搜榜等使用)"""
    limit = int(request.args.get("limit", 50))
    page = max(1, int(request.args.get("page", 1)))
    domain = request.args.get("domain")
    sub_domain = request.args.get("sub_domain")
    sort_by = request.args.get("sort", "time")  # time / heat
    last_24h = request.args.get("last_24h", "false").lower() == "true"

    try:
        from db.session import get_sync_session
        from db.models import CanonicalItemModel
        from sqlalchemy import select, desc, func
        from datetime import datetime, timedelta, timezone

        with get_sync_session() as session:
            source_id = request.args.get("source_id")

            stmt = select(CanonicalItemModel)
            
            if last_24h:
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

            if sort_by == "heat":
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
            
            # format timestamps strictly as strings for json
            def _format_db_dt(dt):
                if not dt: return None
                from datetime import timezone
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
        return err(f"Database error: {str(e)}", 500)


@app.route("/api/v1/newsflash")
def get_newsflash():
    """0-latency In-Memory endpoint for NewsFlash panel. No DB queries involved."""
    from memory_cache import news_flash_cache
    limit = int(request.args.get("limit", 8))
    domain = request.args.get("domain")
    
    domain_map = {
        "全球监控": "global", "global": "global",
        "经济": "economy", "economy": "economy",
        "技术": "technology", "technology": "technology",
        "学术": "academic", "academic": "academic",
        "娱乐": "entertainment", "entertainment": "entertainment"
    }
    if domain:
        domain = domain_map.get(domain, domain).lower()
    
    # news_flash_cache is a deque, convert to list to iterate/filter
    cache_list = list(news_flash_cache)
    
    if domain and domain != "all":
        # Check against both actual domain string and empty/None for global
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


# ══════════════════════════════════════════════════════════════
# Error Handlers
# ══════════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(e):
    return err("Not found", 404)


@app.errorhandler(500)
def server_error(e):
    return err(f"Internal server error: {str(e)}", 500)


# ══════════════════════════════════════════════════════════════
# Domain Routes — v1
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/domains", methods=["GET"])
def list_domains():
    """返回4个域及各自源统计"""
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


@app.route("/api/v1/domains/activity")
def domain_activity():
    """
    返回各域的条目总数、最近 24h 新增量及地区分布，供「域活跃度」面板初始化。
    地区分布优先使用 geo_country 字段，对无 geo_country 的条目按 source_id 推断。
    """
    from datetime import datetime, timezone, timedelta
    try:
        from db.session import get_sync_session
        from db.models import CanonicalItemModel
        from sqlalchemy import select, func

        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        # ── source_id → 地区归因规则 ──────────────────────────────
        # CN: 中文平台热搜 / 中国财经平台
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
        # US: 美国科技/安全平台
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
        # Global: 国际学术、全球市场、全球事件
        GLOBAL_SOURCES_PREFIX = (
            "academic.", "economy.crypto.", "economy.quant.",
            "economy.futures.", "economy.trade.",
            "global.conflict.", "global.disaster.",
            "global.displacement.", "global.military.",
        )

        def _classify_source(sid: str, geo_country: str | None) -> str:
            """把一条记录归到 CN / US / Other(具体国码) / Global"""
            if sid in CN_SOURCES:
                return "CN"
            if sid in US_SOURCES:
                return "US"
            # 对 global.* 系列优先使用 geo_country 字段
            if geo_country and geo_country not in ("CN", "US"):
                return geo_country  # 具体国码
            if geo_country == "CN":
                return "CN"
            if geo_country == "US":
                return "US"
            # 其他按 source_id 前缀归为 Global
            for prefix in GLOBAL_SOURCES_PREFIX:
                if sid.startswith(prefix):
                    return "Global"
            return "Global"

        with get_sync_session() as session:
            # 各域总条目数
            total_stmt = (
                select(CanonicalItemModel.domain, func.count().label("total"))
                .where(CanonicalItemModel.domain.isnot(None))
                .group_by(CanonicalItemModel.domain)
            )
            totals = {row.domain: row.total for row in session.execute(total_stmt).all()}

            # 最近 24h 各域新增条目数
            recent_stmt = (
                select(CanonicalItemModel.domain, func.count().label("recent"))
                .where(
                    CanonicalItemModel.domain.isnot(None),
                    CanonicalItemModel.crawled_at >= cutoff,
                )
                .group_by(CanonicalItemModel.domain)
            )
            recents = {row.domain: row.recent for row in session.execute(recent_stmt).all()}

            # 地区分布：按域 + source_id + geo_country 聚合
            geo_stmt = (
                select(
                    CanonicalItemModel.domain,
                    CanonicalItemModel.source_id,
                    CanonicalItemModel.geo_country,
                    func.count().label("n"),
                )
                .where(CanonicalItemModel.domain.isnot(None))
                .group_by(
                    CanonicalItemModel.domain,
                    CanonicalItemModel.source_id,
                    CanonicalItemModel.geo_country,
                )
            )
            geo_rows = session.execute(geo_stmt).all()

        # 按域聚合地区分布（合并数量 ≤3 的国家到 Other）
        domain_geo: dict[str, dict[str, int]] = {}
        for row in geo_rows:
            d = row.domain or ""
            if not d:
                continue
            region = _classify_source(row.source_id, row.geo_country)
            domain_geo.setdefault(d, {})
            domain_geo[d][region] = domain_geo[d].get(region, 0) + row.n

        def _compact_geo(raw: dict) -> dict:
            """把数量极少的小国合并到 Other"""
            total_n = sum(raw.values()) or 1
            result: dict[str, int] = {}
            others = 0
            for k, v in sorted(raw.items(), key=lambda x: -x[1]):
                if k in ("CN", "US", "Global") or v / total_n >= 0.02:
                    result[k] = v
                else:
                    others += v
            if others:
                result["Other"] = result.get("Other", 0) + others
            return result

        # 从调度器 stale_cache 中归并各 source 的最近采集时间到域级别
        _DOMAIN_ALIAS = {"tech": "technology"}
        domain_last_updated: dict[str, str] = {}
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
            {
                "domain": d,
                "total_items": 0,
                "recent_items": 0,
                "last_updated": None,
                "geo_distribution": {},
            }
            for d in ["global", "economy", "technology", "academic"]
        ])


@app.route("/api/v1/domains/<domain>/sources", methods=["GET"])
def domain_sources(domain: str):
    """返回指定域下所有数据源"""
    sources = registry.by_domain(domain)
    if not sources:
        return err(f"Domain '{domain}' not found or has no sources", 404)
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


@app.route("/api/v1/domains/<domain>/items", methods=["GET"])
def domain_items(domain: str):
    """按域查询 CanonicalItem（需要 DB 支持）"""
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    try:
        from db import get_db
        db = get_db()
        items = db.query_items_by_domain(domain=domain, limit=limit, offset=offset)
        return ok(domain=domain, items=[i.to_dict() for i in items], count=len(items))
    except Exception as e:
        logger.warning(f"DB not available for domain query: {e}")
        # 返回空结果而非错误
        return ok(domain=domain, items=[], count=0, note="DB not available")


@app.route("/api/v1/domains/<domain>/<sub>/items", methods=["GET"])
def sub_domain_items(domain: str, sub: str):
    """按子域查询 CanonicalItem"""
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = int(request.args.get("offset", 0))

    try:
        from db import get_db
        db = get_db()
        items = db.query_items_by_domain(domain=domain, sub_domain=sub, limit=limit, offset=offset)
        return ok(domain=domain, sub_domain=sub, items=[i.to_dict() for i in items], count=len(items))
    except Exception as e:
        logger.warning(f"DB not available for sub-domain query: {e}")
        return ok(domain=domain, sub_domain=sub, items=[], count=0, note="DB not available")


@app.route("/api/v1/crawl/domain/<domain>", methods=["POST"])
def crawl_domain(domain: str):
    """触发整个域的采集任务"""
    sources = registry.by_domain(domain)
    if not sources:
        return err(f"Domain '{domain}' not found or has no sources", 404)

    enabled = [s for s in sources if s.is_enabled]
    if not enabled:
        return err(f"No enabled sources in domain '{domain}'", 400)

    launched = [s.source_id for s in enabled]
    for source in enabled:
        try:
            _scheduler.trigger(source.source_id)
        except Exception as e:
            logger.warning(f"Failed to trigger {source.source_id}: {e}")

    return ok(
        msg=f"Domain crawl launched for '{domain}'",
        domain=domain,
        launched=launched,
        total=len(launched),
    )


# ══════════════════════════════════════════════════════════════
# AI Summary Routes
# ══════════════════════════════════════════════════════════════

@app.route("/api/v1/ai/summary", methods=["POST"])
async def ai_summary():
    """
    生成当前情报摘要，按领域划分。
    """
    # Support both JSON body and Query Params
    json_data = request.get_json(silent=True) or {}
    domain = json_data.get("domain") or request.args.get("domain")
    force = json_data.get("force", False) or request.args.get("force", "false").lower() == "true"
    limit_val = int(json_data.get("limit") or request.args.get("limit", 40))
    
    if domain and domain != "all":
        limit_val = max(limit_val, 80)
    limit = min(limit_val, 150)
    
    # 获取待摘要的内容
    domain_groups: dict[str, list[dict]] = {}
    try:
        from db.session import get_sync_session
        from db.models import CanonicalItemModel
        from sqlalchemy import select, desc
        
        with get_sync_session() as session:
            # 优先按热度排序，获取最有价值的情报
            stmt = select(CanonicalItemModel).order_by(desc(CanonicalItemModel.hotness_score), desc(CanonicalItemModel.crawled_at))
            if domain and domain != "all":
                stmt = stmt.where(CanonicalItemModel.domain == domain)
            stmt = stmt.limit(limit)
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
        logger.warning(f"AI Summary: 从 DB 获取数据失败: {e}")
        return err(f"Database error: {str(e)}", 500)

    if not domain_groups:
        return err(f"No items available for domain '{domain or 'all'}' summarization", 400)

    summary = await _llm.generate_summary(domain_groups, target_domain=domain)
    return ok(summary=summary, domains_count=len(domain_groups))


# ══════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(
        host=settings.FLASK_HOST,
        port=settings.FLASK_PORT,
        debug=settings.FLASK_DEBUG,
        threaded=True,
    )
