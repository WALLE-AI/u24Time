# -*- coding: utf-8 -*-
"""
DataAlignmentModel — CanonicalItem Schema
所有数据源最终统一到此数据模型
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# ─── 枚举常量 ─────────────────────────────────────────────────

class SourceType:
    SOCIAL = "social"
    NEWS = "news"
    GEO = "geo"
    MILITARY = "military"
    MARKET = "market"
    CYBER = "cyber"
    CLIMATE = "climate"
    HOTSEARCH = "hotsearch"


class DomainType:
    """四大顶级领域"""
    ECONOMY  = "economy"     # 经济域
    TECH     = "technology"  # 技术域
    ACADEMIC = "academic"    # 学术域
    GLOBAL   = "global"      # 全球监控域


class SubDomainType:
    """各域下的子领域"""
    # Economy
    STOCK       = "stock"       # 股票预测
    FUTURES     = "futures"     # 期货指数
    QUANT       = "quant"       # 量化/宏观
    TRADE       = "trade"       # 国际贸易
    CRYPTO      = "crypto"      # 数字货币
    # Technology
    OSS         = "oss"         # 开源/开发者生态
    CYBER       = "cyber"       # 网络安全
    INFRA       = "infra"       # 互联网基础设施
    AI_SERVICE  = "ai_service"  # AI 服务监控
    # Academic
    PAPER       = "paper"       # 研究论文
    PATENT      = "patent"      # 专利
    CONF        = "conference"  # 学术会议
    PREDICTION  = "prediction"  # 预测市场
    # Global Monitoring
    CONFLICT    = "conflict"    # 武装冲突
    MILITARY    = "military"    # 军事/海事
    DIPLOMACY   = "diplomacy"   # 外交/制裁/多边主义
    DISASTER    = "disaster"    # 自然灾害/气候
    DISPLACEMENT= "displacement" # 人口流离失所
    UNREST      = "unrest"      # 社会动荡
    SOCIAL      = "social"      # 中文社交舆情


class SeverityLevel:
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    _ORDER = {INFO: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}

    @classmethod
    def higher(cls, a: str, b: str) -> str:
        """返回两者中更高的严重等级"""
        return a if cls._ORDER.get(a, 0) >= cls._ORDER.get(b, 0) else b


# ─── 核心统一数据模型 ─────────────────────────────────────────

@dataclass
class CanonicalItem:
    """
    统一标准化情报条目。

    所有数据源（社交平台、RSS 新闻、地理事件、军事、市场、网络威胁、气候）
    在经过对应 Normalizer 处理后，均产出此结构。
    """

    # ── 来源标识 ────────────────────────────────────────────
    item_id: str                    # 全局唯一 ID: "{source_id}:{original_id}"
    source_id: str                  # 数据源注册 ID，如 "social.bilibili"
    source_type: str                # SourceType 中的值

    # ── 内容 ───────────────────────────────────────────────
    title: str                      # 标题或内容摘要（必须非空）
    body: Optional[str] = None      # 正文
    author: Optional[str] = None    # 作者 / 发布者
    url: Optional[str] = None       # 原始链接

    # ── 时间 (均为 UTC aware datetime) ─────────────────────
    published_at: Optional[datetime] = None
    crawled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # ── 地理信息 ────────────────────────────────────────────
    geo_lat: Optional[float] = None     # 纬度 (-90 ~ 90)
    geo_lon: Optional[float] = None     # 经度 (-180 ~ 180)
    geo_country: Optional[str] = None   # ISO-3166 国家码（两位大写）
    geo_region: Optional[str] = None    # 地区名称

    # ── 量化指标 ─────────────────────────────────────────────
    hotness_score: float = 0.0          # 标准化热度分 [0, 100]
    severity_level: str = SeverityLevel.INFO  # SeverityLevel 常量
    sentiment: Optional[float] = None   # 情感分 [-1.0, 1.0]

    # ── 原始平台数据快照 ─────────────────────────────────────
    raw_engagement: dict = field(default_factory=dict)
    raw_metadata: dict = field(default_factory=dict)

    # ── 领域分类 ────────────────────────────────────────────────
    domain: str = ""          # DomainType 值，如 "economy"
    sub_domain: str = ""      # SubDomainType 值，如 "stock"

    # ── 分类标签 ─────────────────────────────────────────────
    categories: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    # ── AI 处理标记 ──────────────────────────────────────────
    is_classified: bool = False
    classification_source: str = ""  # "keyword" / "ml" / "llm"

    def to_dict(self) -> dict:
        """序列化为字典（JSON 友好）"""
        return {
            "item_id": self.item_id,
            "source_id": self.source_id,
            "source_type": self.source_type,
            "title": self.title,
            "body": self.body,
            "author": self.author,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "crawled_at": self.crawled_at.isoformat(),
            "geo_lat": self.geo_lat,
            "geo_lon": self.geo_lon,
            "geo_country": self.geo_country,
            "geo_region": self.geo_region,
            "hotness_score": round(self.hotness_score, 4),
            "severity_level": self.severity_level,
            "sentiment": self.sentiment,
            "raw_engagement": self.raw_engagement,
            "raw_metadata": self.raw_metadata,
            "domain": self.domain,
            "sub_domain": self.sub_domain,
            "categories": self.categories,
            "keywords": self.keywords,
            "is_classified": self.is_classified,
            "classification_source": self.classification_source,
        }


# ─── 热度计算工具 ─────────────────────────────────────────────

class HotnessCalculator:
    """
    跨平台统一热度计算器。
    借鉴 BettaFish MediaCrawlerDB 的加权算法，使用 log 压缩后归一化。
    """

    # 互动权重
    W_LIKE: float = 1.0
    W_COMMENT: float = 5.0
    W_SHARE: float = 10.0
    W_VIEW: float = 0.1
    W_FAVORITE: float = 10.0
    W_DANMAKU: float = 0.5

    @classmethod
    def compute_raw(cls, engagement: dict) -> float:
        """计算原始加权热度值"""
        return (
            engagement.get("likes", 0) * cls.W_LIKE
            + engagement.get("comments", 0) * cls.W_COMMENT
            + engagement.get("shares", 0) * cls.W_SHARE
            + engagement.get("views", 0) * cls.W_VIEW
            + engagement.get("favorites", 0) * cls.W_FAVORITE
            + engagement.get("danmaku", 0) * cls.W_DANMAKU
        )

    @classmethod
    def normalize(cls, raw_score: float, max_score: float = 1_000_000.0) -> float:
        """
        log 压缩归一化到 [0, 100]
        hotness = log10(1 + raw) / log10(1 + max) * 100
        """
        if raw_score <= 0:
            return 0.0
        result = math.log10(1 + raw_score) / math.log10(1 + max_score) * 100.0
        return min(100.0, max(0.0, result))

    @classmethod
    def score(cls, engagement: dict, max_score: float = 1_000_000.0) -> float:
        raw = cls.compute_raw(engagement)
        return cls.normalize(raw, max_score)

    # ── 时间衰减热度（新闻/事件类专用）────────────────────────

    _SEVERITY_BASE: dict = {
        "critical": 100.0,
        "high":      80.0,
        "medium":    55.0,
        "low":       30.0,
        "info":      15.0,
    }

    @classmethod
    def severity_base(cls, severity: str) -> float:
        """severity 字符串 → 基础热度分"""
        return cls._SEVERITY_BASE.get(severity, 15.0)

    @classmethod
    def time_decay_score(
        cls,
        severity: str,
        published_at: "Optional[datetime]",
        *,
        base_override: "Optional[float]" = None,
        bonus: float = 0.0,
        decay_lambda: float = 0.035,
    ) -> float:
        """
        基于 severity + 发布时间的指数衰减热度。

        公式:
            age_hours = max(0, (now - published_at).total_seconds() / 3600)
            hotness   = (base + bonus) × e^(-λ × age_hours)

        参数:
            severity      - SeverityLevel 字符串，决定基础分
            published_at  - 发布时间 (UTC aware datetime)，None 时取当前时间
            base_override - 手动覆盖基础分（忽略 severity）
            bonus         - 附加量化加分（如震级、伤亡数、涨跌幅换算）
            decay_lambda  - 衰减系数（默认 0.035，CRITICAL 半衰期 ≈ 20h）

        返回:
            float in [0.0, 100.0]
        """
        base = base_override if base_override is not None else cls.severity_base(severity)
        total_base = min(base + bonus, 100.0)

        if published_at is not None:
            now = datetime.now(timezone.utc)
            age_hours = max(0.0, (now - published_at).total_seconds() / 3600.0)
        else:
            age_hours = 0.0  # 无发布时间，视为刚发布

        decayed = total_base * math.exp(-decay_lambda * age_hours)
        return round(min(100.0, max(0.0, decayed)), 4)


# ─── 经济领域元数据 ───────────────────────────────────────────

@dataclass
class EconomicMetadata:
    """
    经济域专属元数据，存储在 CanonicalItem.raw_metadata['economic'] 中。
    适用于 stock / futures / quant / crypto 子域。
    """
    symbol: str = ""                      # 代码, e.g. "000001.SS", "BTC-USD"
    price: Optional[float] = None         # 最新价格
    change_pct: Optional[float] = None    # 24h/1d 涨跌幅 %
    open_price: Optional[float] = None
    high_price: Optional[float] = None
    low_price: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    currency: str = "CNY"
    exchange: str = ""                    # "SSE"/"SZSE"/"NYSE"/"BINANCE"...
    interval: str = "1d"                  # 时间粒度 1m/5m/1h/1d/1w
    signal: Optional[str] = None         # 量化信号: BUY/SELL/HOLD/UNKNOWN/CASH
    indicators: dict = field(default_factory=dict)  # SMA50/RSI/MACD/BBOLL...

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "change_pct": self.change_pct,
            "open_price": self.open_price,
            "high_price": self.high_price,
            "low_price": self.low_price,
            "volume": self.volume,
            "market_cap": self.market_cap,
            "currency": self.currency,
            "exchange": self.exchange,
            "interval": self.interval,
            "signal": self.signal,
            "indicators": self.indicators,
        }


# ─── 关键词严重度分类器 ─────────────────────────────────────

SEVERITY_KEYWORDS: dict[str, list[str]] = {
    SeverityLevel.CRITICAL: [
        "nuclear", "chemical weapon", "biological weapon", "mass casualties",
        "terrorist attack", "coup d'état", "civil war", "genocide",
        "核武器", "生化武器", "政变", "内战", "种族灭绝",
    ],
    SeverityLevel.HIGH: [
        "explosion", "airstrike", "missile", "bombing", "military offensive",
        "earthquake", "tsunami", "major flood", "wildfire", "pandemic",
        "爆炸", "空袭", "导弹", "军事行动", "地震", "海啸", "洪灾",
    ],
    SeverityLevel.MEDIUM: [
        "protest", "riot", "strike", "sanction", "cyberattack", "data breach",
        "抗议", "罢工", "制裁", "网络攻击", "数据泄露",
    ],
    SeverityLevel.LOW: [
        "warning", "alert", "investigation", "arrest", "fire",
        "预警", "调查", "逮捕", "火灾",
    ],
}


def classify_severity_by_keywords(text: str) -> tuple[str, str]:
    """
    通过关键词分类严重等级。
    返回 (severity_level, classification_source)
    """
    text_lower = text.lower()
    for level in [SeverityLevel.CRITICAL, SeverityLevel.HIGH, SeverityLevel.MEDIUM, SeverityLevel.LOW]:
        for kw in SEVERITY_KEYWORDS.get(level, []):
            if kw.lower() in text_lower:
                return level, "keyword"
    return SeverityLevel.INFO, "keyword"
