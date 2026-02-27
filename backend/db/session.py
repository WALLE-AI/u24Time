# -*- coding: utf-8 -*-
"""
U24Time Backend — Database Session & Engine
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from contextlib import asynccontextmanager, contextmanager

from config import settings
from db.models import Base


# ─── Sync Engine (for Alembic + simple ops) ──────────────────
sync_engine = create_engine(
    settings.database_url,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
)

SyncSession = sessionmaker(bind=sync_engine, expire_on_commit=False)


@contextmanager
def get_sync_session() -> Session:
    session = SyncSession()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Async Engine (for application runtime) ──────────────────
async_engine = create_async_engine(
    settings.async_database_url,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=20,
)

AsyncSessionFactory = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


@asynccontextmanager
async def get_async_session() -> AsyncSession:
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """创建所有表（开发模式用；生产建议使用 Alembic）"""
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
