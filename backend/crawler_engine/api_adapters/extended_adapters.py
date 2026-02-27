# -*- coding: utf-8 -*-
"""
Extended API Adapters — 借鉴 WorldMonitor 数据源策略补充的适配器
WorldMonitor 策略：按数据新鲜度分层 TTL，并发拉取，stale-while-revalidate

包含:
- YahooFinanceAdapter   (股票/指数/商品价格，5分钟 TTL)
- FearGreedAdapter      (另类Fear&Greed，1小时 TTL)
- BtcHashrateAdapter    (Bitcoin 算力，30分钟 TTL)
- HuggingFaceAdapter    (每日 AI 论文，1小时 TTL)
- CloudStatusAdapter    (云服务/AI服务状态，5分钟 TTL)
- NVDAdapter            (NVD CVE 最新漏洞，30分钟 TTL)
- ReliefWebAdapter      (人道危机，1小时 TTL)
- PolymarketAdapter     (预测市场，30分钟 TTL)
- HackerNewsAdapter     (HN Top Stories，15分钟 TTL)
- SemanticScholarAdapter (学术趋势论文，1小时 TTL)
"""

from __future__ import annotations
import asyncio
import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from config import settings

_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError)),
)

# Use a more realistic browser User-Agent to avoid TLS/Rate-limit issues
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

import asyncio
from datetime import datetime, timezone
from typing import Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

_RETRY = dict(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.ConnectError)),
)

HEADERS = {"User-Agent": "U24Time-Crawler/1.0 (https://github.com/u24time)"}


# ══════════════════════════════════════════════════════════════
# YahooFinanceAdapter  — 5分钟 TTL
# ══════════════════════════════════════════════════════════════

class YahooFinanceAdapter:
    """
    Yahoo Finance Chart API v8 Adapter（无需 API Key）。
    WorldMonitor 使用此源作为宏观信号面板的核心数据。

    文档: https://query1.finance.yahoo.com/v8/finance/chart/{symbol}
    """

    BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart"

    # 全球主要股票指数（参考 worldmonitor get-macro-signals）
    DEFAULT_INDICES = [
        "^GSPC",   # S&P 500
        "^DJI",   # Dow Jones
        "^IXIC",   # NASDAQ
        "000001.SS",  # 上证指数
        "^N225",   # 日经 225
        "^FTSE",   # 英国富时100
        "^HSI",    # 恒生指数
    ]

    # 大宗商品期货
    COMMODITIES = ["GC=F", "CL=F", "SI=F", "NG=F", "HG=F"]

    @retry(**_RETRY)
    async def fetch_quote(self, symbol: str, range_: str = "1d", interval: str = "1d") -> dict:
        """获取单个 symbol 的 chart 数据"""
        url = f"{self.BASE_URL}/{symbol}"
        params = {"range": range_, "interval": interval}
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return {"symbol": symbol, **resp.json()}

    async def fetch_indices(self, symbols: Optional[list[str]] = None) -> list[dict]:
        """
        并发获取多个指数行情（WorldMonitor 并发策略）。
        按 2 个一组串行请求，避免 Yahoo Finance 限速。
        """
        targets = symbols or self.DEFAULT_INDICES
        results = []
        # Yahoo Finance 会对并发请求限速，故分批串行
        for symbol in targets:
            try:
                data = await self.fetch_quote(symbol, range_="1d", interval="1d")
                results.append(data)
                await asyncio.sleep(0.3)  # 避免 Yahoo 限速
            except Exception as e:
                logger.warning(f"YahooFinanceAdapter: {symbol} 失败 → {e}")
        logger.info(f"YahooFinanceAdapter: 获取 {len(results)}/{len(targets)} 个 symbol")
        return results

    async def fetch_commodities(self) -> list[dict]:
        """获取大宗商品期货行情"""
        return await self.fetch_indices(self.COMMODITIES)


# ══════════════════════════════════════════════════════════════
# FearGreedAdapter  — 1小时 TTL
# ══════════════════════════════════════════════════════════════

class FearGreedAdapter:
    """
    Crypto Fear & Greed Index (alternative.me).
    WorldMonitor 7信号面板之一。

    文档: https://alternative.me/crypto/fear-and-greed-index/
    """

    API_URL = "https://api.alternative.me/fng/"

    @retry(**_RETRY)
    async def fetch(self, limit: int = 30) -> list[dict]:
        """获取最近 N 天的 FGI 数据"""
        params = {"limit": limit, "format": "json"}
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("data", [])
            logger.info(f"FearGreedAdapter: 获取 {len(entries)} 条 FGI 数据")
            return entries


# ══════════════════════════════════════════════════════════════
# BtcHashrateAdapter  — 30分钟 TTL
# ══════════════════════════════════════════════════════════════

class BtcHashrateAdapter:
    """
    Bitcoin 全网算力 (mempool.space).
    WorldMonitor 7信号面板之一，用于判断 GROWING/STABLE/DECLINING。

    文档: https://mempool.space/api/v1/mining/hashrate/1m
    """

    API_URL = "https://mempool.space/api/v1/mining/hashrate/1m"

    @retry(**_RETRY)
    async def fetch(self) -> dict:
        """获取近 1 个月算力历史"""
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.API_URL)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"BtcHashrateAdapter: 获取算力数据 {len(data.get('hashrates', []))} 条")
            return data


# ══════════════════════════════════════════════════════════════
# HuggingFaceAdapter  — 1小时 TTL
# ══════════════════════════════════════════════════════════════

class HuggingFaceAdapter:
    """
    HuggingFace Daily Papers API（无需 API Key）.

    文档: https://huggingface.co/api/daily_papers
    """

    API_URL = "https://huggingface.co/api/daily_papers"

    @retry(**_RETRY)
    async def fetch(self, limit: int = 20) -> list[dict]:
        """获取今日推荐的 AI 论文列表"""
        params = {"limit": limit}
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            papers = resp.json()
            if isinstance(papers, dict):
                papers = papers.get("data", papers.get("papers", []))
            logger.info(f"HuggingFaceAdapter: 获取 {len(papers)} 篇论文")
            return papers


# ══════════════════════════════════════════════════════════════
# CloudStatusAdapter  — 5分钟 TTL
# ══════════════════════════════════════════════════════════════

# StatusPage.io v2 JSON API 端点映射（无需 Key）
STATUSPAGE_ENDPOINTS: dict[str, str] = {
    "tech.infra.cloud_aws":        "https://health.aws.amazon.com/health/status",
    "tech.infra.cloud_cloudflare": "https://www.cloudflarestatus.com/api/v2/status.json",
    "tech.infra.cloud_gcp":        "https://status.cloud.google.com/incidents.json",
    "tech.infra.cloud_vercel":     "https://www.vercel-status.com/api/v2/status.json",
    "tech.infra.dev_github":       "https://www.githubstatus.com/api/v2/status.json",
    "tech.infra.dev_npm":          "https://status.npmjs.org/api/v2/status.json",
    "tech.infra.comm_slack":       "https://slack-status.com/api/v2.0.0/current",
    "tech.infra.comm_discord":     "https://discordstatus.com/api/v2/status.json",
    "tech.infra.saas_stripe":      "https://status.stripe.com/current",
    "tech.ai.openai_status":       "https://status.openai.com/api/v2/status.json",
    "tech.ai.anthropic_status":    "https://status.anthropic.com/api/v2/status.json",
    "tech.ai.replicate_status":    "https://www.replicatestatus.com/api/v2/status.json",
}


class CloudStatusAdapter:
    """
    StatusPage.io v2 JSON API 适配器（无需 Key）。
    并发检查所有云服务和 AI 服务的运行状态。
    WorldMonitor 用此类监控基础设施，触发 infra 域 CanonicalItem。
    """

    async def _fetch_one(
        self, client: httpx.AsyncClient, source_id: str, url: str
    ) -> Optional[tuple[str, dict]]:
        """拉取单个服务状态"""
        try:
            resp = await client.get(url, timeout=8, headers=HEADERS, follow_redirects=True)
            if resp.status_code >= 400:
                return None
            data = resp.json()
            # StatusPage.io v2 结构: {status: {indicator, description}, page: {...}}
            raw_status = data.get("status", {})
            indicator = raw_status.get("indicator", "none")
            description = raw_status.get("description", "All Systems Operational")

            # 映射 indicator → worldmonitor/tech_normalizer 的状态字符串
            indicator_map = {
                "none": "SERVICE_OPERATIONAL_STATUS_OPERATIONAL",
                "minor": "SERVICE_OPERATIONAL_STATUS_DEGRADED",
                "major": "SERVICE_OPERATIONAL_STATUS_PARTIAL_OUTAGE",
                "critical": "SERVICE_OPERATIONAL_STATUS_MAJOR_OUTAGE",
                "maintenance": "SERVICE_OPERATIONAL_STATUS_MAINTENANCE",
            }
            normalized_status = indicator_map.get(indicator, "SERVICE_OPERATIONAL_STATUS_UNSPECIFIED")

            return source_id, {
                "id": source_id,
                "name": data.get("page", {}).get("name", source_id),
                "status": normalized_status,
                "description": description,
                "url": data.get("page", {}).get("url", url),
            }
        except Exception as e:
            logger.warning(f"CloudStatusAdapter: {source_id} 失败 → {e}")
            return None

    async def fetch_all(self, source_ids: Optional[list[str]] = None) -> dict[str, dict]:
        """并发拉取所有（或指定）服务状态"""
        targets = {
            sid: url
            for sid, url in STATUSPAGE_ENDPOINTS.items()
            if source_ids is None or sid in source_ids
        }
        results: dict[str, dict] = {}
        async with httpx.AsyncClient(timeout=10, http2=True) as client:
            tasks = [self._fetch_one(client, sid, url) for sid, url in targets.items()]
            raw = await asyncio.gather(*tasks, return_exceptions=True)

        for result in raw:
            if isinstance(result, Exception) or result is None:
                continue
            sid, data = result
            results[sid] = data

        logger.info(f"CloudStatusAdapter: 获取 {len(results)}/{len(targets)} 个服务状态")
        return results


# ══════════════════════════════════════════════════════════════
# NVDAdapter  — 30分钟 TTL
# ══════════════════════════════════════════════════════════════

class NVDAdapter:
    """
    NIST NVD CVE API 2.0 Adapter（无需 Key）。
    获取最近发布的 CVSS 高/严重漏洞。

    文档: https://nvd.nist.gov/developers/vulnerabilities
    """

    API_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"

    @retry(**_RETRY)
    async def fetch_recent(self, days_back: int = 1, min_cvss: float = 7.0, limit: int = 30) -> list[dict]:
        """
        获取最近 N 天 CVSS >= min_cvss 的新 CVE。

        Args:
            days_back: 时间范围（天）
            min_cvss: 最低 CVSS 分数
            limit: 最大结果数
        """
        from datetime import timedelta
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=days_back)
        params = {
            "pubStartDate": start.strftime("%Y-%m-%dT%H:%M:%S.000"),
            "pubEndDate": end.strftime("%Y-%m-%dT%H:%M:%S.000"),
            "cvssV3Severity": "HIGH" if min_cvss >= 7.0 else "MEDIUM",
            "resultsPerPage": min(limit, 100),
        }
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            vulns = data.get("vulnerabilities", [])
            logger.info(f"NVDAdapter: 获取 {len(vulns)} 条 CVE (CVSS≥{min_cvss})")
            return vulns


# ══════════════════════════════════════════════════════════════
# ReliefWebAdapter  — 1小时 TTL
# ══════════════════════════════════════════════════════════════

class ReliefWebAdapter:
    """
    ReliefWeb Humanitarian API Adapter.
    文档: https://api.reliefweb.int/v1/disasters

    无需 API Key，免费使用。
    """

    BASE_URL = "https://api.reliefweb.int/v1"

    @retry(**_RETRY)
    async def fetch_disasters(self, limit: int = 20, status: str = "ongoing") -> list[dict]:
        """获取进行中的人道主义灾难列表"""
        params = {
            "appname": "u24time",
            "limit": limit,
            "filter[field]": "status",
            "filter[value]": status,
            "profile": "full",
        }
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(f"{self.BASE_URL}/disasters", params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            logger.info(f"ReliefWebAdapter: 获取 {len(items)} 条 {status} 灾难")
            return items

    @retry(**_RETRY)
    async def fetch_reports(self, limit: int = 20) -> list[dict]:
        """获取最新人道主义报告"""
        params = {
            "appname": "u24time",
            "limit": limit,
            "sort[]": "date:desc",
            "profile": "full",
        }
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(f"{self.BASE_URL}/reports", params=params)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            logger.info(f"ReliefWebAdapter: 获取 {len(items)} 条报告")
            return items


# ══════════════════════════════════════════════════════════════
# PolymarketAdapter  — 30分钟 TTL
# ══════════════════════════════════════════════════════════════

class PolymarketAdapter:
    """
    Polymarket Gamma API Adapter（无需 Key）.
    获取开放预测市场列表，按交易量排序。

    文档: https://gamma-api.polymarket.com
    """

    API_URL = "https://gamma-api.polymarket.com/markets"

    @retry(**_RETRY)
    async def fetch_active(self, limit: int = 30) -> list[dict]:
        """获取活跃预测市场"""
        params = {"closed": "false", "limit": limit, "active": "true"}
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            markets = resp.json()
            if isinstance(markets, dict):
                markets = markets.get("data", [])
            logger.info(f"PolymarketAdapter: 获取 {len(markets)} 个预测市场")
            return markets


# ══════════════════════════════════════════════════════════════
# HackerNewsAdapter  — 15分钟 TTL
# ══════════════════════════════════════════════════════════════

class HackerNewsAdapter:
    """
    Hacker News Firebase REST API Adapter（无需 Key，完全免费）.

    文档: https://hacker-news.firebaseio.com/v0/
    """

    BASE_URL = "https://hacker-news.firebaseio.com/v0"

    @retry(**_RETRY)
    async def fetch_top_stories(self, limit: int = 30) -> list[dict]:
        """获取 HN Top Stories 详情"""
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            # 1. 获取 top story ID 列表
            resp = await client.get(f"{self.BASE_URL}/topstories.json")
            resp.raise_for_status()
            ids = resp.json()[:limit]

            # 2. 并发获取每篇 story 详情（限制并发数避免 Firebase 限速）
            semaphore = asyncio.Semaphore(5)
            results = []

            async def _fetch_item(item_id: int):
                async with semaphore:
                    try:
                        r = await client.get(f"{self.BASE_URL}/item/{item_id}.json")
                        r.raise_for_status()
                        return r.json()
                    except Exception:
                        return None

            tasks = [_fetch_item(iid) for iid in ids]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
            results = [r for r in raw if r and not isinstance(r, Exception)]

        logger.info(f"HackerNewsAdapter: 获取 {len(results)} 篇 HN Top Story")
        return results


# ══════════════════════════════════════════════════════════════
# SemanticScholarAdapter — 1小时 TTL
# ══════════════════════════════════════════════════════════════

class SemanticScholarAdapter:
    """
    Semantic Scholar Graph API v1 Adapter（无需 Key，有限额使用）。
    用于抓取趋势论文或特定领域的学术进展。

    文档: https://api.semanticscholar.org/api-docs/graph
    """

    API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

    @retry(**_RETRY)
    async def fetch_trending(self, query: str = "AI", limit: int = 20) -> list[dict]:
        """抓取最新的趋势论文"""
        # Semantic Scholar API 有较严格的频率限制，增加小额延迟
        await asyncio.sleep(2)
        params = {
            "query": query,
            "limit": limit,
            "fields": "title,abstract,url,year,citationCount,authors",
            "sort": "citationCount:desc",  # 简单起见，按引用量排序代表趋势
        }
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.API_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            papers = data.get("data", [])
            logger.info(f"SemanticScholarAdapter: 获取 {len(papers)} 篇论文 (query={query})")
            return papers
