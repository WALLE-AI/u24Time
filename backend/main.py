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


# ─── Flask App 初始化 ──────────────────────────────────────────

app = Flask(__name__)
app.config["SECRET_KEY"] = settings.SECRET_KEY
CORS(app, origins="*")

# ─── 全局对象 ─────────────────────────────────────────────────

_engine = CrawlerEngine()
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()


# ─── SSE 支持 ─────────────────────────────────────────────────

def _broadcast(event: dict):
    """向所有 SSE 客户端广播消息"""
    with _sse_lock:
        dead: list[queue.Queue] = []
        for q in _sse_clients:
            try:
                q.put_nowait(event)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)


def _format_sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.route("/stream")
def sse_stream():
    """SSE 事件流端点"""
    client_q: queue.Queue = queue.Queue(maxsize=50)
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


# ─── 注入 SSE 回调到 CrawlerEngine ────────────────────────────
_engine.set_progress_callback(_broadcast)


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
        items = await _engine.run_rss(category=category, feed_ids=feed_ids)
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
        items = await _engine.run_api(source_id, **params)
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
        results = await _engine.run_all()
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
        items = await _engine.run_hotsearch(source_ids=source_ids)
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
    """返回最近 50 条爬虫任务记录"""
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
    """
    查询 CanonicalItem（需要 DB 连接）。
    Query params: source_type, source_id, severity,
                  page (default 1), limit (default 50)
    """
    try:
        from db.session import get_sync_session
        from db.models import CanonicalItemModel
        from sqlalchemy import select, desc

        source_type = request.args.get("source_type")
        source_id = request.args.get("source_id")
        severity = request.args.get("severity")
        page = max(1, int(request.args.get("page", 1)))
        limit = min(200, max(1, int(request.args.get("limit", 50))))

        with get_sync_session() as session:
            stmt = select(CanonicalItemModel).order_by(desc(CanonicalItemModel.hotness_score))
            if source_type:
                stmt = stmt.where(CanonicalItemModel.source_type == source_type)
            if source_id:
                stmt = stmt.where(CanonicalItemModel.source_id == source_id)
            if severity:
                stmt = stmt.where(CanonicalItemModel.severity_level == severity)
            stmt = stmt.offset((page - 1) * limit).limit(limit)
            rows = session.scalars(stmt).all()

        items = [
            {
                "item_id": r.item_id,
                "source_id": r.source_id,
                "source_type": r.source_type,
                "title": r.title,
                "url": r.url,
                "published_at": r.published_at.isoformat() if r.published_at else None,
                "hotness_score": r.hotness_score,
                "severity_level": r.severity_level,
                "geo_lat": r.geo_lat,
                "geo_lon": r.geo_lon,
                "geo_country": r.geo_country,
                "categories": r.categories,
            }
            for r in rows
        ]
        return ok(data=items, page=page, limit=limit)

    except Exception as e:
        logger.warning(f"/api/v1/items DB 查询失败（可能 DB 未初始化）: {e}")
        return ok(data=[], msg=f"DB not available: {e}")


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
# Main
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app.run(
        host=settings.FLASK_HOST,
        port=settings.FLASK_PORT,
        debug=settings.FLASK_DEBUG,
        threaded=True,
    )
