# -*- coding: utf-8 -*-
"""
NewsNormalizer — RSS / 新闻 API 数据规范化器

从 feedparser 解析的 RSS 条目转换为 CanonicalItem。
也支持直接从字典处理（用于 worldmonitor 风格 RSS proxy 结果）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional, Any

from loguru import logger

from data_alignment.schema import (
    CanonicalItem,
    SourceType,
    SeverityLevel,
    HotnessCalculator,
    classify_severity_by_keywords,
)


def _parse_feedparser_time(entry: dict) -> Optional[datetime]:
    """解析 feedparser entry 中的时间字段（9元组 → datetime）"""
    # feedparser 提供 published_parsed / updated_parsed（time.struct_time）
    import time as _time
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        t = entry.get(key)
        if t is not None:
            try:
                ts = _time.mktime(t)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except (OverflowError, ValueError):
                continue
    # fallback: 字符串 published
    raw = entry.get("published") or entry.get("updated")
    if raw:
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(raw).astimezone(timezone.utc)
        except Exception:
            pass
    return None


def _extract_summary(entry: dict) -> str:
    """提取摘要，去除 HTML 标签"""
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self._parts: list[str] = []
        def handle_data(self, data):
            self._parts.append(data)
        def get_text(self):
            return " ".join(self._parts).strip()

    raw = entry.get("summary") or entry.get("description") or ""
    if not raw:
        return ""
    stripper = _Stripper()
    try:
        stripper.feed(raw)
        return stripper.get_text()[:2000]
    except Exception:
        return raw[:2000]


class NewsNormalizer:
    """
    RSS / 新闻条目规范化器。

    Usage:
        normalizer = NewsNormalizer()
        item = normalizer.normalize_from_feedparser(entry, source_feed_id="news.rss.bbc")
    """

    def normalize_from_feedparser(
        self,
        entry: Any,
        source_feed_id: str,
        feed_category: str = "news",
    ) -> Optional[CanonicalItem]:
        """
        从 feedparser 解析的 entry 对象创建 CanonicalItem。

        Args:
            entry: feedparser entry 对象 (或包含 link/title 的 dict)
            source_feed_id: 数据源注册 ID，如 "news.rss.bbc"
            feed_category: 此 RSS 源的分类（geopolitical/tech/finance...）
        """
        # feedparser entry 支持属性访问，也支持字典访问
        if hasattr(entry, "get"):
            e = entry
        else:
            e = {k: getattr(entry, k, None) for k in dir(entry)}

        title = (e.get("title") or "").strip()
        if not title:
            return None

        link = e.get("link") or e.get("url") or ""
        body = _extract_summary(e)
        published_at = _parse_feedparser_time(e)

        # author
        author = None
        if e.get("author"):
            author = str(e["author"])
        elif e.get("author_detail"):
            author = e["author_detail"].get("name")

        # item_id
        if link:
            item_id = f"{source_feed_id}:{hashlib.sha1(link.encode()).hexdigest()[:16]}"
        else:
            item_id = f"{source_feed_id}:{hashlib.md5(title.encode()).hexdigest()[:16]}"

        full_text = f"{title} {body}"
        severity, cls_src = classify_severity_by_keywords(full_text)

        # 标签
        tags = []
        if e.get("tags"):
            try:
                tags = [t.get("term", "") for t in e["tags"] if t.get("term")]
            except Exception:
                pass

        hotness = HotnessCalculator.time_decay_score(severity, published_at)

        return CanonicalItem(
            item_id=item_id,
            source_id=source_feed_id,
            source_type=SourceType.NEWS,
            title=title,
            body=body or None,
            author=author,
            url=link or None,
            published_at=published_at,
            hotness_score=hotness,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "feed_id": source_feed_id,
                "tags": tags,
            },
            categories=[feed_category, "news"],
            keywords=tags[:10],
            is_classified=True,
            classification_source=cls_src,
        )

    def normalize_batch_from_feedparser(
        self,
        entries: list,
        source_feed_id: str,
        feed_category: str = "news",
    ) -> list[CanonicalItem]:
        results = []
        for entry in entries:
            try:
                item = self.normalize_from_feedparser(entry, source_feed_id, feed_category)
                if item:
                    results.append(item)
            except Exception as e:
                logger.warning(f"NewsNormalizer: 规范化失败 feed={source_feed_id} err={e}")
        return results
