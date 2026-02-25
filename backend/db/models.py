# -*- coding: utf-8 -*-
"""
U24Time Backend — SQLAlchemy ORM Models
数据库模型定义
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, DateTime, Float, Index, Integer,
    JSON, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class CanonicalItemModel(Base):
    """统一标准化后的情报条目"""

    __tablename__ = "canonical_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ─── 来源标识 ────────────────────────────────────────────
    item_id: Mapped[str] = mapped_column(String(512), nullable=False, comment="全局唯一ID: source_id:platform:original_id")
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="数据源注册ID, 如 social.bilibili")
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="来源类型: social/news/geo/military/market/cyber/climate")

    # ─── 内容 ────────────────────────────────────────────────
    title: Mapped[str] = mapped_column(Text, nullable=False, comment="标题或内容摘要")
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="正文（可为空）")
    author: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, comment="作者/发布者")
    url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True, comment="原始链接")

    # ─── 时间 ─────────────────────────────────────────────────
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, comment="发布时间 (UTC)")
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, comment="采集时间 (UTC)")

    # ─── 地理信息 ─────────────────────────────────────────────
    geo_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="纬度")
    geo_lon: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="经度")
    geo_country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, comment="ISO-3166 国家码")
    geo_region: Mapped[Optional[str]] = mapped_column(String(256), nullable=True, comment="地区名称")

    # ─── 量化指标 ─────────────────────────────────────────────
    hotness_score: Mapped[float] = mapped_column(Float, default=0.0, comment="标准化热度分 [0, 100]")
    severity_level: Mapped[str] = mapped_column(String(16), default="info", comment="严重等级: info/low/medium/high/critical")
    sentiment: Mapped[Optional[float]] = mapped_column(Float, nullable=True, comment="情感分 [-1.0, 1.0]")

    # ─── 原始平台数据快照 ─────────────────────────────────────
    raw_engagement: Mapped[dict] = mapped_column(JSON, default=dict, comment="原始互动数据: likes/comments/shares/views")
    raw_metadata: Mapped[dict] = mapped_column(JSON, default=dict, comment="其他原始字段")

    # ─── 分类标签 ─────────────────────────────────────────────
    categories: Mapped[list] = mapped_column(JSON, default=list, comment="分类标签列表")
    keywords: Mapped[list] = mapped_column(JSON, default=list, comment="关键词列表")

    # ─── AI 处理标记 ──────────────────────────────────────────
    is_classified: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已分类")
    classification_source: Mapped[str] = mapped_column(String(16), default="", comment="分类来源: keyword/ml/llm")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        UniqueConstraint("item_id", name="uq_canonical_item_id"),
        Index("ix_canonical_source_id", "source_id"),
        Index("ix_canonical_source_type", "source_type"),
        Index("ix_canonical_published_at", "published_at"),
        Index("ix_canonical_hotness", "hotness_score"),
        Index("ix_canonical_severity", "severity_level"),
        Index("ix_canonical_geo", "geo_lat", "geo_lon"),
    )


class RawItemModel(Base):
    """原始采集数据备份（便于重新对齐）"""

    __tablename__ = "raw_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    original_id: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    raw_data: Mapped[dict] = mapped_column(JSON, nullable=False, comment="原始 JSON 数据")
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_aligned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已对齐到 canonical_items")

    __table_args__ = (
        Index("ix_raw_source_id", "source_id"),
        Index("ix_raw_aligned", "is_aligned"),
    )


class CrawlTaskModel(Base):
    """爬虫任务记录"""

    __tablename__ = "crawl_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, comment="任务唯一ID (UUID)")
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, comment="目标数据源ID")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False, comment="任务类型: rss/social/api")
    params: Mapped[dict] = mapped_column(JSON, default=dict, comment="任务参数（关键词、平台等）")
    status: Mapped[str] = mapped_column(String(16), default="pending", comment="任务状态: pending/running/done/failed")
    items_fetched: Mapped[int] = mapped_column(Integer, default=0, comment="抓取条目数")
    items_aligned: Mapped[int] = mapped_column(Integer, default=0, comment="对齐条目数")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="错误信息")
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (
        Index("ix_task_status", "status"),
        Index("ix_task_source", "source_id"),
    )


class DataSourceHealthModel(Base):
    """数据源健康记录"""

    __tablename__ = "data_source_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, comment="healthy/degraded/down")
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, comment="响应延迟 (ms)")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_health_source_id", "source_id"),
        Index("ix_health_checked_at", "checked_at"),
    )
