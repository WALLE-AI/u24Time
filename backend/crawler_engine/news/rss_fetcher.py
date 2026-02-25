# -*- coding: utf-8 -*-
"""
RSS Fetcher — 异步批量 RSS 采集器
借鉴 worldmonitor rss-proxy.js 的安全过滤、重试、并发策略
使用 httpx + feedparser 替代 Edge Runtime
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

import feedparser
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from crawler_engine.news.rss_sources import RSSFeed, ALL_RSS_FEEDS, ALLOWED_DOMAINS
from config import settings


class RSSFetcher:
    """
    异步 RSS 批量采集器。

    用法:
        fetcher = RSSFetcher()
        async for feed_id, entries in fetcher.fetch_all():
            ...  # entries: list[feedparser BSONified entry dicts]
    """

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 U24Time-RSS/1.0"

    def __init__(self, concurrency: int = None, timeout: int = None):
        self.concurrency = concurrency or settings.RSS_CONCURRENCY
        self.timeout = timeout or settings.RSS_TIMEOUT

    def _is_allowed(self, url: str) -> bool:
        try:
            domain = url.split("/")[2]
            return domain in ALLOWED_DOMAINS
        except IndexError:
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
        reraise=False,
    )
    async def _fetch_one(self, client: httpx.AsyncClient, feed: RSSFeed) -> Optional[tuple[RSSFeed, list]]:
        """下载并解析单个 RSS feed，返回 (feed, entries) 或 None"""
        if not self._is_allowed(feed.url):
            logger.warning(f"RSSFetcher: 域名不在白名单 {feed.url}")
            return None

        try:
            resp = await client.get(
                feed.url,
                headers={
                    "User-Agent": self.USER_AGENT,
                    "Accept": "application/rss+xml, application/xml, text/xml, */*",
                },
                follow_redirects=True,
                timeout=self.timeout,
            )
            if resp.status_code >= 400:
                logger.warning(f"RSSFetcher: HTTP {resp.status_code} for {feed.url}")
                return None

            # feedparser 可直接接受 bytes/str
            parsed = feedparser.parse(resp.content)
            entries = parsed.get("entries", [])
            logger.debug(f"RSSFetcher: {feed.feed_id} → {len(entries)} entries")
            return feed, [dict(e) for e in entries]

        except Exception as e:
            logger.warning(f"RSSFetcher: 拉取失败 {feed.feed_id} ({feed.url}) → {e}")
            return None

    async def fetch_feeds(
        self,
        feeds: Optional[list[RSSFeed]] = None,
    ) -> list[tuple[RSSFeed, list]]:
        """
        并发拉取多个 RSS 源。

        Args:
            feeds: 要拉取的源列表，默认使用 ALL_RSS_FEEDS
        Returns:
            [(RSSFeed, entries_list), ...]  成功拉取的结果
        """
        if feeds is None:
            feeds = ALL_RSS_FEEDS

        semaphore = asyncio.Semaphore(self.concurrency)
        results: list[tuple[RSSFeed, list]] = []

        async def _guarded(feed: RSSFeed):
            async with semaphore:
                return await self._fetch_one(client, feed)

        limits = httpx.Limits(max_connections=self.concurrency * 2, max_keepalive_connections=self.concurrency)
        async with httpx.AsyncClient(limits=limits, http2=True) as client:
            tasks = [_guarded(f) for f in feeds]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in raw_results:
            if isinstance(result, Exception):
                logger.error(f"RSSFetcher: 任务异常 {result}")
                continue
            if result is not None:
                results.append(result)

        logger.info(f"RSSFetcher: 完成拉取 {len(results)}/{len(feeds)} 个源")
        return results

    async def fetch_by_category(self, category: str) -> list[tuple[RSSFeed, list]]:
        """按分类拉取"""
        feeds = [f for f in ALL_RSS_FEEDS if f.category == category]
        return await self.fetch_feeds(feeds)

    async def fetch_single(self, feed_id: str) -> Optional[tuple[RSSFeed, list]]:
        """拉取单个 feed"""
        feed = next((f for f in ALL_RSS_FEEDS if f.feed_id == feed_id), None)
        if not feed:
            return None
        limits = httpx.Limits(max_connections=5)
        async with httpx.AsyncClient(limits=limits) as client:
            return await self._fetch_one(client, feed)
