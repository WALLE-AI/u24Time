# -*- coding: utf-8 -*-
"""
U24Time Agents API - FastAPI 应用入口
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from agents.config import agents_settings
from agents.routers import bettafish, shared

def create_agents_app() -> FastAPI:
    """创建并配置 Agents FastAPI 子应用"""
    app = FastAPI(
        title="U24Time Agents API", 
        version="1.0.0",
        description="BettaFish & MiroFish Agents Pipeline"
    )

    # CORS 配置
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(shared.router, prefix="/agents", tags=["Shared"])
    app.include_router(bettafish.router, prefix="/agents/bettafish", tags=["BettaFish"])
    
    # 注册 MiroFish 路由
    from agents.routers import mirofish
    app.include_router(mirofish.router, prefix="/agents/mirofish", tags=["MiroFish"])

    logger.info(f"Agents FastAPI App created (Port: {agents_settings.AGENTS_PORT})")
    return app

# 为 uvicorn 运行时暴露 app 实例
app = create_agents_app()
