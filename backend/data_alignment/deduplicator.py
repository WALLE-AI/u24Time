# -*- coding: utf-8 -*-
"""
Deduplicator — 去重器

策略 (借鉴 worldmonitor 地理网格去重 + BettaFish 内容去重):
1. item_id 精确匹配去重（同一来源同一原始 ID）
2. 文本 Jaccard 相似度 (> 0.6) 合并
3. 地理去重: 同日期同 0.1° 格点同类型事件合并
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Optional

from loguru import logger

from data_alignment.schema import CanonicalItem


def _jaccard(a: str, b: str) -> float:
    """基于词集的 Jaccard 相似度"""
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _geo_grid_key(lat: Optional[float], lon: Optional[float], date: Optional[datetime]) -> Optional[str]:
    """0.1° 格点 + 日期 → 地理去重 Key"""
    if lat is None or lon is None:
        return None
    grid_lat = round(lat * 10) / 10
    grid_lon = round(lon * 10) / 10
    date_str = date.strftime("%Y-%m-%d") if date else "nodate"
    return f"{grid_lat:.1f}:{grid_lon:.1f}:{date_str}"


class Deduplicator:
    """
    多策略去重器。

    设计上保持无状态（每次调用传入完整 batch），
    这样管线可以并行调用而不产生竞争。
    """

    GEO_TYPES = {"geo", "military", "climate"}
    JACCARD_THRESHOLD = 0.65

    def deduplicate(self, items: list[CanonicalItem]) -> list[CanonicalItem]:
        """
        对一批 CanonicalItem 进行多策略去重。
        返回去重后的列表（保留先遇到的条目）。
        """
        if not items:
            return []

        seen_ids: set[str] = set()
        geo_seen: dict[str, CanonicalItem] = {}   # grid_key → item
        text_buckets: dict[str, list[CanonicalItem]] = defaultdict(list)  # type → items
        result: list[CanonicalItem] = []

        for item in items:
            # 1. item_id 精确去重
            if item.item_id in seen_ids:
                continue
            seen_ids.add(item.item_id)

            # 2. 地理格点去重（仅对 geo / military 类型）
            if item.source_type in self.GEO_TYPES:
                grid_key = _geo_grid_key(item.geo_lat, item.geo_lon, item.published_at)
                if grid_key:
                    # 同格点同类型事件 → 合并（取严重度更高者）
                    type_grid_key = f"{item.source_type}:{grid_key}"
                    if type_grid_key in geo_seen:
                        existing = geo_seen[type_grid_key]
                        from data_alignment.schema import SeverityLevel as SL
                        if SL._ORDER.get(item.severity_level, 0) > SL._ORDER.get(existing.severity_level, 0):
                            # 替换为更严重的那条
                            geo_seen[type_grid_key] = item
                            result = [r for r in result if r.item_id != existing.item_id]
                            result.append(item)
                        continue
                    geo_seen[type_grid_key] = item

            # 3. 文本 Jaccard 去重（同 source_type 内）
            bucket_key = item.source_type
            duplicate_found = False
            for existing in text_buckets[bucket_key]:
                if _jaccard(item.title, existing.title) >= self.JACCARD_THRESHOLD:
                    # 保留发布时间更新的那条
                    if (
                        item.published_at and existing.published_at
                        and item.published_at > existing.published_at
                    ):
                        # 替换
                        result = [r for r in result if r.item_id != existing.item_id]
                        text_buckets[bucket_key].remove(existing)
                        text_buckets[bucket_key].append(item)
                        result.append(item)
                    duplicate_found = True
                    break

            if not duplicate_found:
                text_buckets[bucket_key].append(item)
                result.append(item)

        return result
