# -*- coding: utf-8 -*-
"""
DataSource Registry — 所有数据源的注册表与健康监控

每个数据源描述为 DataSourceConfig，注册后可统一查询健康状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal

import httpx
from loguru import logger


SourceStatus = Literal["healthy", "degraded", "down", "unknown"]


@dataclass
class DataSourceConfig:
    """单个数据源的配置与元数据"""
    source_id: str               # 唯一注册 ID，如 "social.bilibili"
    name: str                    # 可读名称
    source_type: str             # social/news/geo/military/market/cyber/climate
    description: str             # 简短描述
    crawl_method: str            # playwright / rss / api
    health_url: Optional[str] = None   # 用于心跳检测的 URL（可为空）
    api_key_required: bool = False
    is_enabled: bool = True
    tags: list[str] = field(default_factory=list)

    # 运行时状态（不参与配置初始化）
    status: SourceStatus = "unknown"
    last_checked: Optional[datetime] = None
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None


# ══════════════════════════════════════════════════════════════
# 完整数据源注册表
# ══════════════════════════════════════════════════════════════

ALL_SOURCES: list[DataSourceConfig] = [

    # ─────────────────────────────────────────────────────────
    # A类 — 社交舆情 (借鉴 BettaFish)
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="social.bilibili",
        name="B站 (Bilibili)",
        source_type="social",
        description="B站视频 + 评论，关键词驱动抓取",
        crawl_method="playwright",
        health_url="https://www.bilibili.com",
        tags=["china", "video", "social"],
    ),
    DataSourceConfig(
        source_id="social.douyin",
        name="抖音 (Douyin)",
        source_type="social",
        description="抖音短视频 + 评论",
        crawl_method="playwright",
        health_url="https://www.douyin.com",
        tags=["china", "video", "social"],
    ),
    DataSourceConfig(
        source_id="social.weibo",
        name="微博 (Weibo)",
        source_type="social",
        description="微博帖文 + 评论 + 热搜",
        crawl_method="playwright",
        health_url="https://weibo.com",
        tags=["china", "microblog", "social"],
    ),
    DataSourceConfig(
        source_id="social.xhs",
        name="小红书 (XHS)",
        source_type="social",
        description="小红书图文笔记 + 评论",
        crawl_method="playwright",
        health_url="https://www.xiaohongshu.com",
        tags=["china", "lifestyle", "social"],
    ),
    DataSourceConfig(
        source_id="social.kuaishou",
        name="快手 (Kuaishou)",
        source_type="social",
        description="快手短视频 + 评论",
        crawl_method="playwright",
        health_url="https://www.kuaishou.com",
        tags=["china", "video", "social"],
    ),
    DataSourceConfig(
        source_id="social.zhihu",
        name="知乎 (Zhihu)",
        source_type="social",
        description="知乎问答 + 文章 + 评论",
        crawl_method="playwright",
        health_url="https://www.zhihu.com",
        tags=["china", "qa", "social"],
    ),
    DataSourceConfig(
        source_id="social.tieba",
        name="百度贴吧 (Tieba)",
        source_type="social",
        description="贴吧帖子 + 评论",
        crawl_method="playwright",
        health_url="https://tieba.baidu.com",
        tags=["china", "forum", "social"],
    ),

    # ─────────────────────────────────────────────────────────
    # B1类 — 国际新闻 RSS (借鉴 worldmonitor)
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="news.rss.bbc",
        name="BBC News",
        source_type="news",
        description="BBC World Service RSS",
        crawl_method="rss",
        health_url="https://feeds.bbci.co.uk/news/world/rss.xml",
        tags=["english", "geopolitical", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.reuters",
        name="Reuters",
        source_type="news",
        description="Reuters World News RSS",
        crawl_method="rss",
        health_url="https://feeds.reuters.com/reuters/worldNews",
        tags=["english", "geopolitical", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.aljazeera",
        name="Al Jazeera",
        source_type="news",
        description="Al Jazeera English RSS",
        crawl_method="rss",
        health_url="https://www.aljazeera.com/xml/rss/all.xml",
        tags=["english", "middle-east", "geopolitical", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.guardian",
        name="The Guardian World",
        source_type="news",
        description="Guardian World News RSS",
        crawl_method="rss",
        health_url="https://www.theguardian.com/world/rss",
        tags=["english", "geopolitical", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.defenseone",
        name="Defense One",
        source_type="news",
        description="Defense One Military RSS",
        crawl_method="rss",
        health_url="https://www.defenseone.com/rss/all/",
        tags=["english", "military", "defense", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.usni",
        name="USNI News",
        source_type="news",
        description="US Naval Institute News RSS",
        crawl_method="rss",
        health_url="https://news.usni.org/feed",
        tags=["english", "military", "maritime", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.techcrunch",
        name="TechCrunch",
        source_type="news",
        description="TechCrunch Tech News RSS",
        crawl_method="rss",
        health_url="https://techcrunch.com/feed/",
        tags=["english", "tech", "news"],
    ),
    DataSourceConfig(
        source_id="news.rss.arxiv_cs",
        name="ArXiv CS",
        source_type="news",
        description="ArXiv Computer Science papers RSS",
        crawl_method="rss",
        health_url="https://rss.arxiv.org/rss/cs",
        tags=["english", "research", "ai", "tech"],
    ),
    DataSourceConfig(
        source_id="news.rss.hacker_news",
        name="Hacker News",
        source_type="news",
        description="Hacker News Top Stories RSS",
        crawl_method="rss",
        health_url="https://hnrss.org/frontpage",
        tags=["english", "tech", "community"],
    ),
    DataSourceConfig(
        source_id="news.rss.bellingcat",
        name="Bellingcat",
        source_type="news",
        description="Open source intelligence investigations",
        crawl_method="rss",
        health_url="https://www.bellingcat.com/feed/",
        tags=["english", "osint", "geopolitical"],
    ),
    DataSourceConfig(
        source_id="news.rss.kyiv_independent",
        name="Kyiv Independent",
        source_type="news",
        description="Ukraine conflict coverage",
        crawl_method="rss",
        health_url="https://kyivindependent.com/feed/",
        tags=["english", "ukraine", "conflict"],
    ),
    DataSourceConfig(
        source_id="news.rss.scmp",
        name="SCMP",
        source_type="news",
        description="South China Morning Post Asia RSS",
        crawl_method="rss",
        health_url="https://www.scmp.com/rss/91/feed",
        tags=["english", "asia", "china", "news"],
    ),

    # ─────────────────────────────────────────────────────────
    # B2类 — 地理事件 API
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="geo.acled",
        name="ACLED Conflict Data",
        source_type="geo",
        description="Armed Conflict Location & Event Data (冲突/抗议/暴力事件)",
        crawl_method="api",
        health_url="https://api.acleddata.com/acled/read/?limit=1",
        api_key_required=True,
        tags=["conflict", "protest", "geopolitical"],
    ),
    DataSourceConfig(
        source_id="geo.gdelt",
        name="GDELT Global Events",
        source_type="geo",
        description="GDELT 全球大事件数据库（免费无需 Key）",
        crawl_method="api",
        health_url="https://api.gdeltproject.org/api/v2/doc/doc?query=test&mode=artlist&maxrecords=1&format=json",
        api_key_required=False,
        tags=["conflict", "geopolitical", "media"],
    ),
    DataSourceConfig(
        source_id="geo.usgs",
        name="USGS Earthquakes",
        source_type="geo",
        description="USGS 地震 M4.5+ 实时数据",
        crawl_method="api",
        health_url="https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson",
        api_key_required=False,
        tags=["earthquake", "disaster", "geophysics"],
    ),
    DataSourceConfig(
        source_id="geo.nasa_firms",
        name="NASA FIRMS Wildfires",
        source_type="geo",
        description="NASA 卫星火点探测数据",
        crawl_method="api",
        health_url="https://firms.modaps.eosdis.nasa.gov/",
        api_key_required=True,
        tags=["wildfire", "disaster", "climate"],
    ),

    # ─────────────────────────────────────────────────────────
    # B3类 — 军事 / 海事
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="military.opensky",
        name="OpenSky ADS-B",
        source_type="military",
        description="OpenSky Network 实时飞行 ADS-B 数据",
        crawl_method="api",
        health_url="https://opensky-network.org/api/states/all?lamin=0&lomin=0&lamax=1&lomax=1",
        api_key_required=False,
        tags=["aviation", "adsb", "military"],
    ),
    DataSourceConfig(
        source_id="military.ais",
        name="AIS Vessel Tracking",
        source_type="military",
        description="AIS 全球船舶位置数据",
        crawl_method="api",
        health_url=None,
        api_key_required=False,
        tags=["maritime", "ais", "military"],
    ),

    # ─────────────────────────────────────────────────────────
    # B4类 — 市场数据
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="market.coingecko",
        name="CoinGecko Crypto",
        source_type="market",
        description="CoinGecko 主流加密货币价格",
        crawl_method="api",
        health_url="https://api.coingecko.com/api/v3/ping",
        api_key_required=False,
        tags=["crypto", "finance", "market"],
    ),

    # ─────────────────────────────────────────────────────────
    # B5类 — 网络威胁情报
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="cyber.feodo",
        name="Feodo Tracker",
        source_type="cyber",
        description="Feodo Tracker C2 服务器黑名单",
        crawl_method="api",
        health_url="https://feodotracker.abuse.ch/downloads/ipblocklist.csv",
        api_key_required=False,
        tags=["c2", "botnet", "threat"],
    ),
    DataSourceConfig(
        source_id="cyber.urlhaus",
        name="URLhaus",
        source_type="cyber",
        description="URLhaus 恶意软件分发 URL 数据库",
        crawl_method="api",
        health_url="https://urlhaus-api.abuse.ch/v1/urls/recent/limit/1/",
        api_key_required=False,
        tags=["malware", "phishing", "threat"],
    ),

    # ─────────────────────────────────────────────────────────
    # C类 — 中文热搜聚合 (BettaFish MindSpider / NewsNow API)
    # 采集端点: https://newsnow.busiyi.world/api/s?id={source_id}&latest
    # ─────────────────────────────────────────────────────────
    DataSourceConfig(
        source_id="hotsearch.weibo",
        name="微博热搜 (NewsNow)",
        source_type="hotsearch",
        description="微博实时热搜榜，通过 NewsNow 聚合 API 获取",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=weibo&latest",
        api_key_required=False,
        tags=["china", "weibo", "hotsearch", "social"],
    ),
    DataSourceConfig(
        source_id="hotsearch.zhihu",
        name="知乎热榜 (NewsNow)",
        source_type="hotsearch",
        description="知乎每日热榜话题",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=zhihu&latest",
        api_key_required=False,
        tags=["china", "zhihu", "hotsearch", "qa"],
    ),
    DataSourceConfig(
        source_id="hotsearch.bilibili",
        name="B站热搜 (NewsNow)",
        source_type="hotsearch",
        description="B站实时热搜榜",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=bilibili-hot-search&latest",
        api_key_required=False,
        tags=["china", "bilibili", "hotsearch", "video"],
    ),
    DataSourceConfig(
        source_id="hotsearch.toutiao",
        name="今日头条热榜 (NewsNow)",
        source_type="hotsearch",
        description="今日头条实时热榜新闻",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=toutiao&latest",
        api_key_required=False,
        tags=["china", "toutiao", "hotsearch", "news"],
    ),
    DataSourceConfig(
        source_id="hotsearch.douyin",
        name="抖音热榜 (NewsNow)",
        source_type="hotsearch",
        description="抖音实时热搜视频榜",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=douyin&latest",
        api_key_required=False,
        tags=["china", "douyin", "hotsearch", "video"],
    ),
    DataSourceConfig(
        source_id="hotsearch.github",
        name="GitHub 每日趋势 (NewsNow)",
        source_type="hotsearch",
        description="GitHub 每日 trending 项目聚合",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=github-trending-today&latest",
        api_key_required=False,
        tags=["github", "tech", "hotsearch", "open-source"],
    ),
    DataSourceConfig(
        source_id="hotsearch.coolapk",
        name="酷安热榜 (NewsNow)",
        source_type="hotsearch",
        description="酷安 Android 应用社区热榜",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=coolapk&latest",
        api_key_required=False,
        tags=["china", "coolapk", "hotsearch", "android"],
    ),
    DataSourceConfig(
        source_id="hotsearch.tieba",
        name="百度贴吧热帖 (NewsNow)",
        source_type="hotsearch",
        description="百度贴吧热门话题聚合",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=tieba&latest",
        api_key_required=False,
        tags=["china", "tieba", "hotsearch", "forum"],
    ),
    DataSourceConfig(
        source_id="hotsearch.wallstreetcn",
        name="华尔街见闻 (NewsNow)",
        source_type="hotsearch",
        description="华尔街见闻中文财经快讯",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=wallstreetcn&latest",
        api_key_required=False,
        tags=["china", "finance", "economics", "hotsearch"],
    ),
    DataSourceConfig(
        source_id="hotsearch.thepaper",
        name="澎湃新闻 (NewsNow)",
        source_type="hotsearch",
        description="澎湃新闻国内事件热榜",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=thepaper&latest",
        api_key_required=False,
        tags=["china", "news", "politics", "hotsearch"],
    ),
    DataSourceConfig(
        source_id="hotsearch.cls",
        name="财联社热榜 (NewsNow)",
        source_type="hotsearch",
        description="财联社国内财经资讯热榜",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=cls-hot&latest",
        api_key_required=False,
        tags=["china", "finance", "market", "hotsearch"],
    ),
    DataSourceConfig(
        source_id="hotsearch.xueqiu",
        name="雪球热帖 (NewsNow)",
        source_type="hotsearch",
        description="雪球股票投资社区热帖",
        crawl_method="api",
        health_url="https://newsnow.busiyi.world/api/s?id=xueqiu&latest",
        api_key_required=False,
        tags=["china", "finance", "stock", "social", "hotsearch"],
    ),
]


class DataSourceRegistry:
    """
    数据源注册表。
    提供按 ID / 类型查询、健康状态获取等功能。
    """

    def __init__(self, sources: list[DataSourceConfig] = ALL_SOURCES):
        self._sources: dict[str, DataSourceConfig] = {s.source_id: s for s in sources}

    def get(self, source_id: str) -> Optional[DataSourceConfig]:
        return self._sources.get(source_id)

    def all(self) -> list[DataSourceConfig]:
        return list(self._sources.values())

    def by_type(self, source_type: str) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.source_type == source_type]

    def enabled(self) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.is_enabled]

    def health_summary(self) -> dict:
        statuses = {"healthy": 0, "degraded": 0, "down": 0, "unknown": 0}
        for s in self._sources.values():
            statuses[s.status] = statuses.get(s.status, 0) + 1
        return {
            "total": len(self._sources),
            "statuses": statuses,
            "sources": [
                {
                    "source_id": s.source_id,
                    "name": s.name,
                    "source_type": s.source_type,
                    "status": s.status,
                    "last_checked": s.last_checked.isoformat() if s.last_checked else None,
                    "last_latency_ms": s.last_latency_ms,
                    "last_error": s.last_error,
                }
                for s in self._sources.values()
            ],
        }

    async def check_health(self, source_id: str, timeout: int = 8) -> SourceStatus:
        """对单个数据源执行 HTTP 心跳检测"""
        source = self._sources.get(source_id)
        if not source or not source.health_url:
            if source:
                source.status = "unknown"
            return "unknown"

        start = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(
                    source.health_url,
                    headers={"User-Agent": "U24Time-HealthCheck/1.0"},
                    follow_redirects=True,
                )
            latency_ms = int((datetime.now(timezone.utc) - start).total_seconds() * 1000)
            status: SourceStatus = "healthy" if resp.status_code < 400 else "degraded"
            source.status = status
            source.last_latency_ms = latency_ms
            source.last_checked = datetime.now(timezone.utc)
            source.last_error = None
        except Exception as e:
            source.status = "down"
            source.last_error = str(e)[:200]
            source.last_checked = datetime.now(timezone.utc)
            status = "down"
            logger.warning(f"Health check failed: {source_id} → {e}")

        return source.status

    async def check_all_health(self, timeout: int = 8) -> dict:
        """并发检测所有有 health_url 的数据源"""
        import asyncio
        tasks = [
            self.check_health(sid, timeout)
            for sid, s in self._sources.items()
            if s.health_url and s.is_enabled
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        return self.health_summary()


# ─── 全局注册表实例 ───────────────────────────────────────────
registry = DataSourceRegistry()
