# -*- coding: utf-8 -*-
"""
HotSearchNormalizer — 中文热搜聚合数据规范化器

处理来自 NewsNow API (https://newsnow.busiyi.world) 的热搜条目，
将各平台热榜数据转换为统一的 CanonicalItem。

平台映射:
    hotsearch.weibo         → 微博热搜
    hotsearch.zhihu         → 知乎热榜
    hotsearch.bilibili      → B站热搜
    hotsearch.toutiao       → 今日头条热榜
    hotsearch.douyin        → 抖音热榜
    hotsearch.github        → GitHub Trending
    hotsearch.coolapk       → 酷安热榜
    hotsearch.tieba         → 贴吧热榜
    hotsearch.wallstreetcn  → 华尔街见闻
    hotsearch.thepaper      → 澎湃新闻
    hotsearch.cls           → 财联社
    hotsearch.xueqiu        → 雪球热帖
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
from loguru import logger

from data_alignment.schema import (
    CanonicalItem,
    SourceType,
    SeverityLevel,
    HotnessCalculator,
    classify_severity_by_keywords,
)


# NewsNow source_id → CanonicalItem metadata
NEWSNOW_META: dict[str, dict] = {
    "hotsearch.weibo":        {"platform": "weibo",       "category": "social",    "geo": "CN"},
    "hotsearch.zhihu":        {"platform": "zhihu",       "category": "qa",        "geo": "CN"},
    "hotsearch.bilibili":     {"platform": "bilibili",    "category": "video",     "geo": "CN"},
    "hotsearch.toutiao":      {"platform": "toutiao",     "category": "news",      "geo": "CN"},
    "hotsearch.douyin":       {"platform": "douyin",      "category": "video",     "geo": "CN"},
    "hotsearch.github":       {"platform": "github",      "category": "tech",      "geo": None},
    "hotsearch.coolapk":      {"platform": "coolapk",     "category": "android",   "geo": "CN"},
    "hotsearch.tieba":        {"platform": "tieba",       "category": "forum",     "geo": "CN"},
    "hotsearch.wallstreetcn": {"platform": "wallstreetcn","category": "finance",   "geo": "CN"},
    "hotsearch.thepaper":     {"platform": "thepaper",    "category": "news",      "geo": "CN"},
    "hotsearch.cls":          {"platform": "cls",         "category": "finance",   "geo": "CN"},
    "hotsearch.xueqiu":       {"platform": "xueqiu",      "category": "finance",   "geo": "CN"},
}

# 财经源使用金融严重度补充规则
FINANCE_SOURCES = {"hotsearch.wallstreetcn", "hotsearch.cls", "hotsearch.xueqiu"}


class HotSearchNormalizer:
    """
    BettaFish NewsNow 热搜榜规范化器。

    NewsNow API 响应结构:
        {
            "status": 200,
            "updatedTime": "2026-01-15T12:00:00.000Z",
            "items": [
                {
                    "id": "...",
                    "title": "...",
                    "url": "...",
                    "mobileUrl": "...",
                    "extra": {        # 可选: 含 icon, hover 等扩展字段
                        "hover": "12345热度",  # 热度数值
                        "label": "热"
                    }
                },
                ...
            ]
        }
    """

    def normalize_batch(
        self,
        response: dict,
        source_id: str,
    ) -> list[CanonicalItem]:
        """
        将整个 NewsNow API 响应（含 items 列表）批量转换为 CanonicalItem。

        Args:
            response: NewsNow API 完整 JSON 响应
            source_id: 数据源 ID，如 "hotsearch.weibo"
        Returns:
            规范化后的 CanonicalItem 列表，按排名降序热度赋值
        """
        items_raw = response.get("items", [])
        if not items_raw:
            return []

        meta = NEWSNOW_META.get(source_id, {})
        results: list[CanonicalItem] = []
        total = len(items_raw)

        for rank, raw in enumerate(items_raw, start=1):
            item = self._normalize_one(raw, source_id, meta, rank, total)
            if item:
                results.append(item)

        logger.debug(f"HotSearchNormalizer: {source_id} → {len(results)} items")
        return results

    def _normalize_one(
        self,
        raw: dict,
        source_id: str,
        meta: dict,
        rank: int,
        total: int,
    ) -> Optional[CanonicalItem]:
        """规范化单条热搜条目"""
        try:
            title = (raw.get("title") or "").strip()
            if not title:
                return None

            url = raw.get("url") or raw.get("mobileUrl") or ""
            raw_id = raw.get("id") or f"rank_{rank}"

            # 生成唯一 item_id
            item_id = f"{source_id}:{raw_id}"

            # 提取热度数值（extra.hover 字段，常为如 "12345热度"）
            extra = raw.get("extra") or {}
            raw_hotness = _extract_hotness_from_extra(extra)

            # 如果没有热度数值，用倒排名 (top1 = highest hotness)
            if raw_hotness > 0:
                # 对数归一化 → 0~100
                hotness_score = HotnessCalculator.score({"views": raw_hotness})
            else:
                # 线性归一化：rank 1 = 100, 末位 ≈ 10
                hotness_score = max(10.0, 100.0 * (1.0 - (rank - 1) / max(total, 1)))

            # 严重度分类
            severity, _ = classify_severity_by_keywords(title)

            # 财经源强制降级最小严重度 (热搜话题通常不是真正紧急事件)
            if source_id in FINANCE_SOURCES and severity == SeverityLevel.CRITICAL:
                severity = SeverityLevel.HIGH

            # 发布时间
            pub_ts = raw.get("pubDate") or raw.get("publishedAt")
            if pub_ts:
                try:
                    published_at = datetime.fromisoformat(pub_ts.replace("Z", "+00:00"))
                except Exception:
                    published_at = datetime.now(timezone.utc)
            else:
                published_at = datetime.now(timezone.utc)

            # 分类标签
            category = meta.get("category", "hotsearch")
            categories = ["hotsearch", category]
            if source_id in FINANCE_SOURCES:
                categories.append("finance")

            return CanonicalItem(
                item_id=item_id,
                source_id=source_id,
                source_type=SourceType.SOCIAL,   # 热搜归入 social 类型
                title=title,
                body=extra.get("hover", "") or raw.get("desc", ""),
                url=url,
                published_at=published_at,
                hotness_score=round(hotness_score, 2),
                severity_level=severity,
                categories=categories,
                geo_country=meta.get("geo"),
                raw_engagement={"rank": rank, "raw_hotness": raw_hotness},
                raw_metadata={
                    "platform": meta.get("platform"),
                    "rank": rank,
                    "total_items": total,
                    "extra": extra,
                },
            )
        except Exception as e:
            logger.warning(f"HotSearchNormalizer: 解析条目失败 ({source_id} rank={rank}) → {e}")
            return None


def _extract_hotness_from_extra(extra: dict) -> float:
    """
    从 extra 字段提取原始热度数字。
    常见格式:
        extra.hover = "12345热度"  / "1.2万" / "12345"
    """
    if not extra:
        return 0.0

    # 尝试 hover 字段
    hover = str(extra.get("hover", "") or "")
    # 去掉非数字字符（中文、单位）
    nums = re.sub(r"[^\d.]", "", hover)
    if nums:
        try:
            val = float(nums)
            # 万 / 亿 单位处理
            if "亿" in hover:
                val *= 1e8
            elif "万" in hover:
                val *= 1e4
            return val
        except ValueError:
            pass

    return 0.0
