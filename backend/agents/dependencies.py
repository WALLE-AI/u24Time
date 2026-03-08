# -*- coding: utf-8 -*-
"""
FastAPI Dependencies 依赖注入
提供数据库 Session 和 LLMClient 实例
"""

from typing import AsyncGenerator
from loguru import logger

from db.session import get_async_session
from sqlalchemy.ext.asyncio import AsyncSession

from utils.llm_client import LLMClient
from agents.config import agents_settings

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：获取异步数据库 Session"""
    async with get_async_session() as session:
        yield session

async def get_llm() -> LLMClient:
    """FastAPI 依赖：获取统一 LLM 客户端"""
    if not agents_settings.LLM_API_KEY:
        logger.warning("Agents Dependencies: LLM_API_KEY is not set.")
    return LLMClient(
        api_key=agents_settings.LLM_API_KEY,
        base_url=agents_settings.LLM_BASE_URL,
        model=agents_settings.LLM_MODEL_NAME
    )
