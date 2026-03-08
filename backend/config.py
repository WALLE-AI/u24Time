# -*- coding: utf-8 -*-
"""
U24Time Backend — Global Configuration
使用 pydantic-settings 管理全局配置，支持从 .env 文件自动加载
"""

from pathlib import Path
from typing import Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT: Path = Path(__file__).resolve().parent
ENV_FILE: Path = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """全局配置：支持 .env 和环境变量自动加载"""

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow",
    )

    # ─── Flask ───────────────────────────────────────────────
    FLASK_ENV: str = Field("development", description="Flask 运行环境")
    FLASK_DEBUG: bool = Field(True, description="Flask Debug 模式")
    FLASK_HOST: str = Field("0.0.0.0", description="Flask 监听地址")
    FLASK_PORT: int = Field(5001, description="Flask 端口")
    SECRET_KEY: str = Field("change-me-in-production", description="Flask secret key")

    # ─── Redis (Flask-SSE 依赖) ───────────────────────────────
    REDIS_URL: str = Field("redis://127.0.0.1:6379/0", description="Redis 连接 URL")

    # ─── Database ───────────────────────────────────────────────
    DB_TYPE: str = Field("sqlite", description="Database type (sqlite or postgres)")
    DB_HOST: str = Field("127.0.0.1", description="数据库主机")
    DB_PORT: int = Field(5432, description="数据库端口")
    DB_USER: str = Field("u24time", description="数据库用户名")
    DB_PASSWORD: str = Field("", description="数据库密码")
    DB_NAME: str = Field("u24time", description="数据库名称")
    DB_SQLITE_PATH: str = Field("u24time.db", description="SQLite 数据库路径")
    DB_ECHO: bool = Field(False, description="SQLAlchemy SQL 日志")

    @property
    def database_url(self) -> str:
        """同步数据库 URL（用于 Alembic）"""
        if self.DB_TYPE == "sqlite":
            return f"sqlite:///{self.DB_SQLITE_PATH}"
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def async_database_url(self) -> str:
        """异步数据库 URL（用于 SQLAlchemy asyncio）"""
        if self.DB_TYPE == "sqlite":
            return f"sqlite+aiosqlite:///{self.DB_SQLITE_PATH}"
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # ─── 外部数据源 API Keys ──────────────────────────────────
    # ACLED 冲突数据 (https://acleddata.com)
    ACLED_API_KEY: Optional[str] = Field(None, description="ACLED API Key")
    ACLED_EMAIL: Optional[str] = Field(None, description="ACLED 注册邮箱")

    # NASA FIRMS 卫星火点 (https://firms.modaps.eosdis.nasa.gov)
    NASA_FIRMS_MAP_KEY: Optional[str] = Field(None, description="NASA FIRMS MAP_KEY")

    # OpenSky ADS-B (https://opensky-network.org)
    OPENSKY_USERNAME: Optional[str] = Field(None, description="OpenSky 用户名")
    OPENSKY_PASSWORD: Optional[str] = Field(None, description="OpenSky 密码")

    # CoinGecko 加密货币
    COINGECKO_API_KEY: Optional[str] = Field(None, description="CoinGecko API Key（可选）")

    # GitHub (https://api.github.com)
    GITHUB_TOKEN: Optional[str] = Field(None, description="GitHub API Token (可选，用于提高限额)")

    # EIA 能源数据 (https://www.eia.gov/opendata)
    EIA_API_KEY: Optional[str] = Field(None, description="EIA API Key")

    # ─── LLM（可选，用于 AI 分类增强）────────────────────────
    LLM_API_KEY: Optional[str] = Field(None, description="LLM API Key")
    LLM_BASE_URL: str = Field("https://api.openai.com/v1", description="LLM Base URL")
    LLM_MODEL_NAME: str = Field("gpt-4o-mini", description="LLM 模型名称")

    # ─── 爬虫配置 ─────────────────────────────────────────────
    CRAWLER_COOKIE_DIR: str = Field("data/cookies", description="社交平台 Cookie 目录")
    RSS_CONCURRENCY: int = Field(10, description="RSS 并发拉取数")
    HTTP_TIMEOUT: int = Field(15, description="HTTP 请求超时（秒）")
    RSS_TIMEOUT: int = Field(20, description="RSS 拉取超时（秒）")
    SOCIAL_MIN_DELAY: float = Field(2.0, description="社交爬虫最小延迟（秒）")
    SOCIAL_MAX_DELAY: float = Field(5.0, description="社交爬虫最大延迟（秒）")

    # BettaFish MindSpider — NewsNow 聚合热搜 API
    # 可通过 .env 覆盖为自托管实例（如 docker-compose 部署）
    NEWSNOW_BASE_URL: str = Field(
        "https://newsnow.busiyi.world",
        description="NewsNow 聚合热搜 API 基础 URL（BettaFish MindSpider）",
    )

    # ─── 扩展 API ──────────────────────────────────────────────
    SEARCH_API_KEY: Optional[str] = Field(None, description="SerpAPI/Tavily API Key（QueryAgent 外部搜索）")
    SEARCH_API_PROVIDER: str = Field("tavily", description="tavily/serpapi/duckduckgo")


# 全局配置实例
settings = Settings()
