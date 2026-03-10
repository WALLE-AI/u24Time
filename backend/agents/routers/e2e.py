# -*- coding: utf-8 -*-
"""
E2E API Router — 端对端分析流程路由
提供 REST + SSE + WebSocket 接口

Endpoints:
  POST /agents/e2e/run            — 触发 E2E 分析
  GET  /agents/e2e/status/{run_id} — 查询运行状态
  GET  /agents/e2e/stream/{run_id} — SSE 实时流
  WS   /agents/e2e/ws/{run_id}     — WebSocket 双向
  GET  /agents/e2e/scheduler/status — 调度器状态
  POST /agents/e2e/scheduler/trigger — 手动触发心跳
  GET  /agents/e2e/memory/search   — 记忆检索
  GET  /agents/e2e/registry/status  — SubagentRegistry 状态
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_async_session
from utils.llm_client import LLMClient
from agents.channel_dispatcher import ChannelDispatcher, get_channel_dispatcher
from agents.subagent_registry import get_subagent_registry
from agents.memory import get_memory_manager

router = APIRouter()


# ─── Request / Response Models ────────────────────────────────────────────────

class RunE2ERequest(BaseModel):
    topic: str = "auto"
    is_heartbeat: bool = False
    platforms: list[str] = ["weibo", "wechat", "bilibili", "douyin", "twitter"]
    token_budget: int = 8_000


class MemorySearchRequest(BaseModel):
    query: str
    k: int = 5
    enable_temporal_decay: bool = True
    enable_mmr: bool = True


# ─── 依赖注入 ─────────────────────────────────────────────────────────────────

def _get_llm() -> LLMClient:
    return LLMClient()


# ─── E2E 运行记录 (轻量内存存储) ─────────────────────────────────────────────

_run_records: dict[str, dict] = {}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/run", summary="触发 E2E 端对端分析", tags=["E2E"])
async def run_e2e(
    request: RunE2ERequest,
    llm: LLMClient = Depends(_get_llm),
    dispatcher: ChannelDispatcher = Depends(get_channel_dispatcher),
):
    """
    触发完整端对端智能体分析流程 (Phase 0-7)

    - topic="auto": 自动从热搜提取话题
    - is_heartbeat=True: 定时任务触发, UI 静默
    """
    from agents.pipeline.e2e_coordinator import EndToEndCoordinator
    from agents.subagent_registry import get_subagent_registry

    run_id = str(uuid.uuid4())
    _run_records[run_id] = {
        "run_id": run_id,
        "status": "running",
        "topic": request.topic,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "is_heartbeat": request.is_heartbeat,
    }

    async def _run():
        from db.session import get_async_session
        try:
            registry = get_subagent_registry()
            async with get_async_session() as db:
                coordinator = EndToEndCoordinator(
                    db_session=db,
                    llm=llm,
                    registry=registry,
                    channel_dispatcher=dispatcher,
                    token_budget=request.token_budget,
                )
                result = await coordinator.run(
                    topic=request.topic,
                    is_heartbeat=request.is_heartbeat,
                    platforms=request.platforms,
                    session_id=run_id,
                )
            _run_records[run_id].update({
                "status": result.get("status", "success"),
                "result": result,
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })
            await dispatcher.dispatch(
                "run_complete",
                {"run_id": run_id, "status": result.get("status")},
                run_id=run_id,
                is_heartbeat=request.is_heartbeat,
            )
        except Exception as e:
            logger.exception(f"E2E run {run_id} 失败: {e}")
            _run_records[run_id].update({
                "status": "error",
                "error": str(e),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            })

    asyncio.create_task(_run())

    return {
        "run_id": run_id,
        "status": "accepted",
        "message": f"E2E 分析任务已提交 (run_id={run_id}), "
                   "通过 /agents/e2e/stream/{run_id} 获取实时进展",
    }


@router.get("/status/{run_id}", summary="查询运行状态")
async def get_run_status(run_id: str):
    """查询指定运行的当前状态"""
    record = _run_records.get(run_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Run {run_id} 不存在")
    return record


@router.get("/stream/{run_id}", summary="SSE 实时事件流")
async def sse_stream(run_id: str, timeout: float = Query(300.0, ge=10, le=3600)):
    """
    SSE 实时推送 E2E 分析进展
    前端使用: new EventSource('/agents/e2e/stream/{run_id}')
    """
    from agents.channel_dispatcher import ChannelDispatcher
    return StreamingResponse(
        ChannelDispatcher.sse_stream(run_id, timeout_s=timeout),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.websocket("/ws/{run_id}")
async def websocket_endpoint(run_id: str, ws: WebSocket):
    """WebSocket 双向实时通信"""
    dispatcher = get_channel_dispatcher()
    await ws.accept()
    dispatcher.register_ws(run_id, ws)
    logger.info(f"E2E WS: 客户端连接 run={run_id}")
    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=60.0)
                # 回应 ping
                if data == "ping":
                    await ws.send_text('{"event":"pong"}')
            except asyncio.TimeoutError:
                await ws.send_text('{"event":"ping"}')
    except WebSocketDisconnect:
        logger.info(f"E2E WS: 客户端断开 run={run_id}")
    finally:
        dispatcher.unregister_ws(run_id)


@router.get("/scheduler/status", summary="调度器状态")
async def get_scheduler_status():
    """查看心跳调度器当前状态"""
    from agents.scheduler import get_heartbeat_scheduler
    scheduler = get_heartbeat_scheduler()
    if not scheduler:
        return {"status": "not_initialized"}
    return scheduler.status()


@router.post("/scheduler/trigger", summary="手动触发 E2E 分析")
async def trigger_pipeline(
    topic: str = Query("auto"),
    is_heartbeat: bool = Query(False),
    db: AsyncSession = Depends(get_async_session),
    llm: LLMClient = Depends(_get_llm),
):
    """手动触发 E2E Pipeline (等同于一次心跳, 但可指定话题)"""
    from agents.scheduler import get_heartbeat_scheduler
    scheduler = get_heartbeat_scheduler()
    if not scheduler:
        raise HTTPException(status_code=503, detail="调度器未初始化")
    result = await scheduler.trigger_now(is_heartbeat=is_heartbeat)
    return result


@router.get("/memory/search", summary="记忆检索")
async def search_memory(
    query: str = Query(..., min_length=1),
    k: int = Query(5, ge=1, le=20),
    enable_decay: bool = Query(True),
    enable_mmr: bool = Query(True),
):
    """
    五步混合检索记忆库
    返回与 query 最相关的历史分析报告片段
    """
    try:
        memory = await get_memory_manager()
        results = await memory.search_history(
            query=query,
            k=k,
            enable_temporal_decay=enable_decay,
            enable_mmr=enable_mmr,
        )
        return {
            "query": query,
            "results": [
                {
                    "chunk_id": r.chunk_id,
                    "path": r.path,
                    "snippet": r.snippet,
                    "score": round(r.score, 4),
                    "source": r.source,
                }
                for r in results
            ],
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"记忆检索失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/status", summary="记忆库状态")
async def get_memory_status():
    """查看长期记忆库状态 (文件数/Chunk数/Provider)"""
    try:
        memory = await get_memory_manager()
        return memory.status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/registry/status", summary="SubagentRegistry 状态")
async def get_registry_status():
    """查看子智能体注册表状态"""
    registry = get_subagent_registry()
    return {
        "summary": registry.status_summary(),
        "active_runs": [
            {
                "run_id": r.run_id,
                "stage": r.stage,
                "status": r.status.value,
                "started_at": r.started_at,
            }
            for r in registry.list_active()
        ],
    }


@router.get("/runs", summary="所有运行记录")
async def list_runs(limit: int = Query(20, ge=1, le=100)):
    """列出最近的 E2E 运行记录"""
    records = sorted(
        _run_records.values(),
        key=lambda x: x.get("started_at", ""),
        reverse=True,
    )[:limit]
    return {"runs": records, "total": len(_run_records)}
