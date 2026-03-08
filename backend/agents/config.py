# -*- coding: utf-8 -*-
"""
Agents Config — 子应用的配置
继承全局后端的 settings，追加 Agents 专属配置
"""

from typing import Optional
from pydantic import Field
from config import settings

class AgentsSettings:
    """Agents 模块专属配置，包裹全局配置"""

    def __getattr__(self, name):
        """如果自己没有定义，代理给全局 settings"""
        return getattr(settings, name)

    # ─── Agents 模块（FastAPI 子应用）────────────────────────────
    AGENTS_PORT: int = 5002

    # MiroFish Zep Cloud
    ZEP_API_KEY: Optional[str] = None

    # MiroFish OASIS 仿真
    OASIS_MAX_ROUNDS: int = 144
    OASIS_MINUTES_PER_ROUND: int = 30
    OASIS_PLATFORM: str = "parallel"

    # 情感分析（可选）
    SENTIMENT_MODEL_ENABLED: bool = True
    SENTIMENT_MODEL_NAME: str = "tabularisai/multilingual-sentiment-analysis"
    SENTIMENT_CONFIDENCE_THRESHOLD: float = 0.5

    # BettaFish 外部搜索（QueryEngine）
    SEARCH_API_KEY: Optional[str] = None
    SEARCH_API_PROVIDER: str = "tavily"

agents_settings = AgentsSettings()
