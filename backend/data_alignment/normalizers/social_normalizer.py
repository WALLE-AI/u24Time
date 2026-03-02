# -*- coding: utf-8 -*-
"""
SocialNormalizer — 社交平台数据规范化器
覆盖: bilibili / douyin / weibo / xhs / kuaishou / zhihu / tieba

数据对齐策略 (借鉴 BettaFish search.py _extract_engagement):
- 各平台字段名不同 → 统一映射到 engagement 字典
- 热度 = 加权互动求和 → log 压缩归一化
- 时间戳多格式 → 统一转 UTC datetime
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Optional

from loguru import logger

from data_alignment.schema import (
    CanonicalItem,
    HotnessCalculator,
    SourceType,
    SeverityLevel,
    classify_severity_by_keywords,
    classify_domain_by_keywords,
)


# 各平台字段映射 (来字段 → 标准字段)
ENGAGEMENT_FIELD_MAP: dict[str, dict[str, list[str]]] = {
    "likes": [
        "liked_count", "like_count", "voteup_count",
        "digg_count", "like_cnt",
    ],
    "comments": [
        "video_comment", "comments_count", "comment_count",
        "total_replay_num", "sub_comment_count", "comment_cnt",
    ],
    "shares": [
        "video_share_count", "shared_count", "share_count",
        "total_forwards", "share_cnt",
    ],
    "views": [
        "video_play_count", "viewd_count", "play_count", "view_count",
    ],
    "favorites": [
        "video_favorite_count", "collected_count", "collect_count",
    ],
    "danmaku": [
        "video_danmaku", "danmaku_count",
    ],
}

# 各平台 URL 字段
URL_FIELDS = [
    "video_url", "note_url", "content_url", "url",
    "aweme_url", "link",
]

# 各平台昵称字段
AUTHOR_FIELDS = [
    "nickname", "user_nickname", "user_name",
    "author_name", "name",
]

# 各平台时间字段
TIME_FIELDS = [
    "create_time", "time", "created_time",
    "publish_time", "crawl_date", "create_date_time",
    "pubdate",
]


def _extract_first(row: dict, fields: list[str]) -> Any:
    for f in fields:
        val = row.get(f)
        if val is not None:
            return val
    return None


def _extract_engagement(row: dict) -> dict:
    """将原始行映射到标准化互动指标"""
    engagement: dict[str, int] = {}
    for key, potential_cols in ENGAGEMENT_FIELD_MAP.items():
        for col in potential_cols:
            if col in row and row[col] is not None:
                try:
                    engagement[key] = int(float(row[col]))
                except (ValueError, TypeError):
                    engagement[key] = 0
                break
    return engagement


def _parse_timestamp(ts: Any) -> Optional[datetime]:
    """统一转换时间戳为 UTC aware datetime"""
    if ts is None:
        return None
    try:
        if isinstance(ts, datetime):
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and str(ts).isdigit()):
            val = float(ts)
            # 毫秒时间戳 vs 秒时间戳
            if val > 1_000_000_000_000:
                val /= 1000
            return datetime.fromtimestamp(val, tz=timezone.utc)
        if isinstance(ts, str):
            # 清理时区后缀
            ts_clean = ts.split("+")[0].strip().replace("Z", "")
            dt = datetime.fromisoformat(ts_clean)
            return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None
    return None


def _make_item_id(source_id: str, row: dict, platform: str) -> str:
    """生成唯一 item_id"""
    original_id = (
        row.get("id")
        or row.get("video_id")
        or row.get("note_id")
        or row.get("aweme_id")
        or row.get("content_id")
    )
    if original_id:
        return f"{source_id}:{original_id}"
    # fallback: hash
    raw = f"{platform}:{row.get('title', '')}:{row.get('url', '')}"
    return f"{source_id}:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


class SocialNormalizer:
    """
    社交平台规范化器。

    支持注册到 AlignmentPipeline 后批量处理 BettaFish MindSpider 抓取的原始行。
    """

    # platform 名到 source_id 的映射
    PLATFORM_SOURCE_MAP = {
        "bilibili": "social.bilibili",
        "bili": "social.bilibili",
        "douyin": "social.douyin",
        "dy": "social.douyin",
        "weibo": "social.weibo",
        "wb": "social.weibo",
        "xhs": "social.xhs",
        "xiaohongshu": "social.xhs",
        "kuaishou": "social.kuaishou",
        "ks": "social.kuaishou",
        "zhihu": "social.zhihu",
        "tieba": "social.tieba",
    }

    def normalize(self, raw_row: dict, platform: str) -> Optional[CanonicalItem]:
        """
        将一行原始社交数据转换为 CanonicalItem。

        Args:
            raw_row: 原始数据字典（数据库查询行 或 Playwright 抓取结果）
            platform: 平台标识，如 'bilibili'、'xhs'
        Returns:
            CanonicalItem 或 None（数据不足时）
        """
        source_id = self.PLATFORM_SOURCE_MAP.get(platform.lower(), f"social.{platform}")

        title = (
            raw_row.get("title")
            or raw_row.get("content")
            or raw_row.get("desc")
            or raw_row.get("content_text")
            or ""
        ).strip()

        if not title:
            logger.debug(f"SocialNormalizer: 跳过空标题 row={list(raw_row.keys())}")
            return None

        engagement = _extract_engagement(raw_row)
        hotness = HotnessCalculator.score(engagement)
        ts = _extract_first(raw_row, TIME_FIELDS)
        published_at = _parse_timestamp(ts)
        url = _extract_first(raw_row, URL_FIELDS)
        author = _extract_first(raw_row, AUTHOR_FIELDS)
        item_id = _make_item_id(source_id, raw_row, platform)

        severity, cls_src = classify_severity_by_keywords(title)

        return CanonicalItem(
            item_id=item_id,
            source_id=source_id,
            source_type=SourceType.SOCIAL,
            title=title,
            body=raw_row.get("desc") or raw_row.get("content_text"),
            author=str(author) if author else None,
            url=str(url) if url else None,
            published_at=published_at,
            hotness_score=hotness,
            severity_level=severity,
            raw_engagement=engagement,
            raw_metadata={
                "platform": platform,
                "source_keyword": raw_row.get("source_keyword"),
                "tag_list": raw_row.get("tag_list"),
            },
            categories=["social"],
            keywords=[raw_row.get("source_keyword", "")],
            is_classified=True,
            classification_source=cls_src,
        )

        item.domain, item.sub_domain = classify_domain_by_keywords(title)
        return item

    def normalize_batch(self, rows: list[dict], platform: str) -> list[CanonicalItem]:
        results = []
        for row in rows:
            try:
                item = self.normalize(row, platform)
                if item:
                    results.append(item)
            except Exception as e:
                logger.warning(f"SocialNormalizer: 规范化失败 platform={platform} err={e}")
        return results
