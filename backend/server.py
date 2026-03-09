# -*- coding: utf-8 -*-
"""
U24Time Unified API - FastAPI 应用主入口 (Phase 5)
集成 HeartbeatScheduler + SubagentRegistry + ChannelDispatcher + CoreCrawler
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from agents.config import agents_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan — 启动时初始化调度器, 关闭时清理"""
    # ── 启动 ──────────────────────────────────────────────────────────────
    logger.info("U24Time App: 启动, 初始化基础设施...")

    # 0. 核心调度系统初始化
    from api.core_router import start_core_scheduler, stop_core_scheduler
    start_core_scheduler()

    # 1. SubagentRegistry 全局单例
    from agents.subagent_registry import get_subagent_registry
    registry = get_subagent_registry()
    registry.start_sweeper()

    # 2. MemoryIndexManager 全局单例
    from agents.memory import get_memory_manager
    await get_memory_manager()

    # 3. ChannelDispatcher 全局单例
    from agents.channel_dispatcher import get_channel_dispatcher
    dispatcher = get_channel_dispatcher()

    # 4. HeartbeatScheduler — 注入 E2E Coordinator
    try:
        from agents.scheduler import create_heartbeat_scheduler
        from agents.pipeline.e2e_coordinator import EndToEndCoordinator

        # 创建一个轻量的 pipeline_fn (无 DB Session — 调度器使用独立 Session)
        async def _heartbeat_pipeline_fn(is_heartbeat: bool = True):
            from db.session import get_session_context
            from utils.llm_client import LLMClient
            async with get_session_context() as db:
                coordinator = EndToEndCoordinator(
                    db_session=db,
                    llm=LLMClient(),
                    registry=registry,
                    channel_dispatcher=dispatcher,
                )
                await coordinator.run(topic="auto", is_heartbeat=is_heartbeat)

        scheduler = create_heartbeat_scheduler(
            pipeline_fn=_heartbeat_pipeline_fn,
            registry=registry,
            heartbeat_cron=agents_settings.__dict__.get("HEARTBEAT_CRON", "0 * * * *"),
        )
        scheduler.start()
        app.state.scheduler = scheduler
    except Exception as e:
        logger.warning(f"U24Time App: HeartbeatScheduler 初始化失败 (非致命) — {e}")
        app.state.scheduler = None

    app.state.registry = registry
    app.state.dispatcher = dispatcher
    logger.info("U24Time App: 基础设施初始化完成")

    yield  # ── 运行中 ────────────────────────────────────────────────────────

    # ── 关闭 ──────────────────────────────────────────────────────────────
    logger.info("U24Time App: 关闭, 清理调度器...")
    stop_core_scheduler()
    if app.state.scheduler:
        app.state.scheduler.stop()
    registry.stop_sweeper()
    from agents.memory import _memory_manager
    if _memory_manager:
        await _memory_manager.close()
    logger.info("U24Time App: 清理完成")


def create_app() -> FastAPI:
    """创建并配置 U24Time 统一系统应用"""
    app = FastAPI(
        title="U24Time Unified API",
        version="3.0.0",
        description=(
            "U24Time 全局统一接口\n\n"
            "包含: Core Crawl Engine / Data Scheduler / Agents E2E Pipeline"
        ),
        lifespan=lifespan,
    )

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Core 基础爬虫与系统路由 ───────────────────────────────────────────
    from api.core_router import router as core_router
    app.include_router(core_router)

    # ── 注册多智能体路由 ──────────────────────────────────────────────────
    from agents.routers import shared
    app.include_router(shared.router, prefix="/agents", tags=["Shared"])

    from agents.routers import bettafish
    app.include_router(bettafish.router, prefix="/agents/bettafish", tags=["BettaFish"])

    from agents.routers import mirofish
    app.include_router(mirofish.router, prefix="/agents/mirofish", tags=["MiroFish"])

    # ── E2E 路由 (v2.1 新增) ──────────────────────────────────────────────
    from agents.routers import e2e
    app.include_router(e2e.router, prefix="/agents/e2e", tags=["E2E"])

    logger.info(
        f"U24Time FastAPI App v3.0 created (Aggregated Architecture)"
    )
    return app


# 为 uvicorn 运行时暴露 app 实例
app = create_app()
