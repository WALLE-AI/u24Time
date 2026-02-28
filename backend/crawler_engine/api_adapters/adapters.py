# -*- coding: utf-8 -*-
"""
API Adapters — 各官方 API 的专用数据采集适配器
每个 Adapter 均为无状态 async 类，通过 httpx 异步请求

包含:
- ACLEDAdapter     (冲突/抗议事件)
- GDELTAdapter     (全球大事件)
- USGSAdapter      (地震数据)
- NASAFIRMSAdapter (卫星火点)
- OpenSkyAdapter   (ADS-B 飞行)
- OpenMeteoAdapter (气候异常)
- CoinGeckoAdapter (加密价格)
- FeodoAdapter     (C2 黑名单)
- URLhausAdapter   (恶意 URL)
"""

from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timedelta, timezone
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
# ACLEDAdapter
# ══════════════════════════════════════════════════════════════

class ACLEDAdapter:
    """
    ACLED API v1 Adapter.
    文档: https://acleddata.com/resources/general-guides/
    """

    BASE_URL = "https://api.acleddata.com/acled/read/"

    def __init__(self):
        self.api_key = settings.ACLED_API_KEY
        self.email = settings.ACLED_EMAIL

    @retry(**_RETRY)
    async def fetch_recent(
        self,
        days_back: int = 7,
        limit: int = 500,
        countries: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取最近 N 天的冲突事件。

        Args:
            days_back: 获取范围（天）
            limit: 最大条数
            countries: 国家过滤列表，如 ["Ukraine", "Taiwan"]
        """
        if not self.api_key or not self.email:
            logger.warning("ACLEDAdapter: 未配置 ACLED_API_KEY / ACLED_EMAIL，跳过")
            return []

        since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        params: dict = {
            "key": self.api_key,
            "email": self.email,
            "limit": limit,
            "event_date": since,
            "event_date_where": "greater than or equal",
            "fields": "event_id_cnty|event_date|event_type|sub_event_type|actor1|actor2|country|location|latitude|longitude|fatalities|notes|source",
        }
        if countries:
            params["country"] = "|".join(countries)

        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            events = data.get("data", [])
            logger.info(f"ACLEDAdapter: 获取 {len(events)} 条事件 (since {since})")
            return events


# ══════════════════════════════════════════════════════════════
# GDELTAdapter
# ══════════════════════════════════════════════════════════════

class GDELTAdapter:
    """
    GDELT 2.0 Events API Adapter (免费无需 Key).
    文档: https://www.gdeltproject.org/data.html
    """

    # GDELT 每 15min 更新一次 CSV 列表
    LASTUPDATE_URL = "http://data.gdeltproject.org/gdeltv2/lastupdate.txt"

    @retry(**_RETRY)
    async def fetch_latest_events(self) -> list[dict]:
        """下载最新 GDELT Events CSV 并解析为字典列表"""
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            # 1. 获取最新文件列表
            resp = await client.get(self.LASTUPDATE_URL)
            resp.raise_for_status()
            lines = resp.text.strip().split("\n")

            # 格式: "size md5 url"，取第一行的 Events CSV
            events_url = None
            for line in lines:
                parts = line.strip().split(" ")
                if len(parts) >= 3 and "export.CSV" in parts[2]:
                    events_url = parts[2]
                    break

            if not events_url:
                logger.warning("GDELTAdapter: 无法从 lastupdate.txt 找到 Events CSV")
                return []

            # 2. 下载 CSV (gzip 格式)
            csv_resp = await client.get(events_url, follow_redirects=True)
            csv_resp.raise_for_status()

            import zipfile
            import gzip

            # GDELT v2 是 .zip
            try:
                with zipfile.ZipFile(io.BytesIO(csv_resp.content)) as zf:
                    name = zf.namelist()[0]
                    content = zf.read(name).decode("utf-8", errors="ignore")
            except Exception:
                content = csv_resp.text

        # GDELT Events CSV 无表头，字段顺序参考文档
        GDELT_COLS = [
            "GLOBALEVENTID", "SQLDATE", "MonthYear", "Year", "FractionDate",
            "Actor1Code", "Actor1Name", "Actor1CountryCode", "Actor1KnownGroupCode",
            "Actor1EthnicCode", "Actor1Religion1Code", "Actor1Religion2Code",
            "Actor1Type1Code", "Actor1Type2Code", "Actor1Type3Code",
            "Actor2Code", "Actor2Name", "Actor2CountryCode", "Actor2KnownGroupCode",
            "Actor2EthnicCode", "Actor2Religion1Code", "Actor2Religion2Code",
            "Actor2Type1Code", "Actor2Type2Code", "Actor2Type3Code",
            "IsRootEvent", "EventCode", "EventBaseCode", "EventRootCode",
            "QuadClass", "GoldsteinScale", "NumMentions", "NumSources",
            "NumArticles", "AvgTone", "Actor1Geo_Type", "Actor1Geo_FullName",
            "Actor1Geo_CountryCode", "Actor1Geo_ADM1Code", "Actor1Geo_Lat",
            "Actor1Geo_Long", "Actor1Geo_FeatureID", "Actor2Geo_Type",
            "Actor2Geo_FullName", "Actor2Geo_CountryCode", "Actor2Geo_ADM1Code",
            "Actor2Geo_Lat", "Actor2Geo_Long", "Actor2Geo_FeatureID",
            "ActionGeo_Type", "ActionGeo_FullName", "ActionGeo_CountryCode",
            "ActionGeo_ADM1Code", "ActionGeo_Lat", "ActionGeo_Long",
            "ActionGeo_FeatureID", "DATEADDED", "SOURCEURL",
        ]

        reader = csv.DictReader(io.StringIO(content), fieldnames=GDELT_COLS, delimiter="\t")
        events: list[dict] = []
        for row in reader:
            if row.get("ActionGeo_Lat") and row.get("ActionGeo_Long"):
                events.append(dict(row))

        logger.info(f"GDELTAdapter: 解析 {len(events)} 条有地理坐标的事件")
        return events[:500]  # 限制返回量


# ══════════════════════════════════════════════════════════════
# USGSAdapter
# ══════════════════════════════════════════════════════════════

class USGSAdapter:
    """
    USGS Earthquake Hazards API Adapter.
    文档: https://earthquake.usgs.gov/fdsnws/event/1/
    """

    BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    @retry(**_RETRY)
    async def fetch_recent(self, min_magnitude: float = 4.5, hours_back: int = 24) -> list[dict]:
        """获取最近 N 小时内 M >= min_magnitude 的地震"""
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=hours_back)
        params = {
            "format": "geojson",
            "starttime": start_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "endtime": end_time.strftime("%Y-%m-%dT%H:%M:%S"),
            "minmagnitude": min_magnitude,
            "orderby": "time",
        }
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            features = data.get("features", [])
            logger.info(f"USGSAdapter: 获取 {len(features)} 条地震 (M≥{min_magnitude})")
            return features


# ══════════════════════════════════════════════════════════════
# NASAFIRMSAdapter
# ══════════════════════════════════════════════════════════════

class NASAFIRMSAdapter:
    """
    NASA FIRMS (Fire Information for Resource Management System) Adapter.
    文档: https://firms.modaps.eosdis.nasa.gov/api/
    """

    BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

    def __init__(self):
        self.map_key = settings.NASA_FIRMS_MAP_KEY

    @retry(**_RETRY)
    async def fetch_active_fires(self, days_back: int = 1, world: bool = True) -> list[dict]:
        """获取最近 N 天卫星火点数据（默认全球 VIIRS）"""
        if not self.map_key:
            logger.warning("NASAFIRMSAdapter: 未配置 NASA_FIRMS_MAP_KEY，跳过")
            return []

        # VIIRS SNPP NRT, -180,-90,180,90 = 全球范围
        url = f"{self.BASE_URL}/{self.map_key}/VIIRS_SNPP_NRT/world/{days_back}"
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()

        reader = csv.DictReader(io.StringIO(resp.text))
        fires = [dict(row) for row in reader]
        logger.info(f"NASAFIRMSAdapter: 获取 {len(fires)} 个火点")
        return fires


# ══════════════════════════════════════════════════════════════
# OpenSkyAdapter
# ══════════════════════════════════════════════════════════════

class OpenSkyAdapter:
    """
    OpenSky Network ADS-B API Adapter.
    文档: https://openskynetwork.github.io/opensky-api/
    """

    BASE_URL = "https://opensky-network.org/api/states/all"

    def __init__(self):
        auth = None
        if settings.OPENSKY_USERNAME and settings.OPENSKY_PASSWORD:
            auth = (settings.OPENSKY_USERNAME, settings.OPENSKY_PASSWORD)
        self._auth = auth

    @retry(**_RETRY)
    async def fetch_all_states(
        self,
        lat_min: float = -90, lon_min: float = -180,
        lat_max: float = 90, lon_max: float = 180,
    ) -> list[list]:
        """
        获取当前空域所有飞行状态向量。
        返回 state_vectors 列表（每条为 17 个字段的 list）。
        """
        params = {
            "lamin": lat_min,
            "lomin": lon_min,
            "lamax": lat_max,
            "lomax": lon_max,
        }
        async with httpx.AsyncClient(
            timeout=settings.HTTP_TIMEOUT,
            headers=HEADERS,
            auth=self._auth,
        ) as client:
            resp = await client.get(self.BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            states = data.get("states", []) or []
            logger.info(f"OpenSkyAdapter: 获取 {len(states)} 个飞行目标")
            return states


# ══════════════════════════════════════════════════════════════
# CoinGeckoAdapter
# ══════════════════════════════════════════════════════════════

class CoinGeckoAdapter:
    """
    CoinGecko API v3 Adapter.
    文档: https://www.coingecko.com/en/api/documentation
    """

    BASE_URL = "https://api.coingecko.com/api/v3"
    # 默认监控的主流币种
    DEFAULT_COINS = ["bitcoin", "ethereum", "solana", "binancecoin", "xrp", "cardano"]

    def __init__(self):
        self.api_key = settings.COINGECKO_API_KEY

    @property
    def _headers(self) -> dict:
        h = dict(HEADERS)
        if self.api_key:
            h["x-cg-demo-api-key"] = self.api_key
        return h

    @retry(**_RETRY)
    async def fetch_prices(self, coin_ids: Optional[list[str]] = None) -> dict[str, dict]:
        """
        获取多个币种的当前价格及 24h 涨跌幅。
        返回 {coin_id: {usd: price, usd_24h_change: pct, ...}}
        """
        coins = coin_ids or self.DEFAULT_COINS
        params = {
            "ids": ",".join(coins),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_market_cap": "true",
            "include_24hr_vol": "true",
        }
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=self._headers) as client:
            resp = await client.get(f"{self.BASE_URL}/simple/price", params=params)
            resp.raise_for_status()
            data = resp.json()
            logger.info(f"CoinGeckoAdapter: 获取 {len(data)} 个币种价格")
            return data


# ══════════════════════════════════════════════════════════════
# FeodoAdapter
# ══════════════════════════════════════════════════════════════

class FeodoAdapter:
    """
    Feodo Tracker IP Blocklist Adapter.
    文档: https://feodotracker.abuse.ch/
    """

    CSV_URL = "https://feodotracker.abuse.ch/downloads/ipblocklist.csv"

    @retry(**_RETRY)
    async def fetch_c2_list(self) -> list[dict]:
        """获取在线 C2 服务器列表"""
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.get(self.CSV_URL, follow_redirects=True)
            resp.raise_for_status()

        rows = []
        for line in resp.text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 8:
                rows.append({
                    "first_seen": parts[0],
                    "ip_address": parts[1],
                    "port": parts[2],
                    "status": parts[3],
                    "hostname": parts[4],
                    "as_number": parts[5],
                    "as_name": parts[6],
                    "country": parts[7],
                    "malware": parts[8] if len(parts) > 8 else "unknown",
                    "last_online": parts[9] if len(parts) > 9 else "",
                })

        logger.info(f"FeodoAdapter: 获取 {len(rows)} 条 C2 记录")
        return rows


# ══════════════════════════════════════════════════════════════
# URLhausAdapter
# ══════════════════════════════════════════════════════════════

class URLhausAdapter:
    """
    URLhaus API Adapter.
    文档: https://urlhaus-api.abuse.ch/
    """

    API_URL = "https://urlhaus-api.abuse.ch/v1/urls/recent/"

    @retry(**_RETRY)
    async def fetch_recent(self, limit: int = 100) -> list[dict]:
        """获取最近报告的恶意 URL"""
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT, headers=HEADERS) as client:
            resp = await client.post(
                self.API_URL,
                data={"limit": limit},
                headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
            )
            resp.raise_for_status()
            data = resp.json()
            entries = data.get("urls", [])
            logger.info(f"URLhausAdapter: 获取 {len(entries)} 条恶意 URL")
            return entries


# ══════════════════════════════════════════════════════════════
# NewsNowAdapter  (BettaFish MindSpider 数据聚合源)
# ══════════════════════════════════════════════════════════════

# source_id → NewsNow API 中对应的源标识符
NEWSNOW_SOURCE_MAP: dict[str, str] = {
    "global.social.weibo_newsnow":        "weibo",
    "global.social.zhihu_newsnow":        "zhihu",
    "global.social.bilibili_newsnow":     "bilibili-hot-search",
    "global.social.douyin_newsnow":       "douyin",
    "global.social.tieba_newsnow":        "tieba",
    "global.diplomacy.thepaper":          "thepaper",
    "economy.stock.wallstreetcn":         "wallstreetcn",
    "economy.stock.cls_hot":              "cls-hot",
    "economy.stock.xueqiu":               "xueqiu",
    "tech.oss.github_trending":           "github-trending-today",
    "tech.oss.coolapk":                   "coolapk",
    "tech.oss.toutiao_tech":              "toutiao",
}


class NewsNowAdapter:
    """
    NewsNow 聚合热搜 API 适配器。

    BettaFish MindSpider 使用此 API（https://newsnow.busiyi.world）
    批量获取 12 个中文平台的热榜话题，无需 API Key。

    文档/来源: MindSpider/BroadTopicExtraction/get_today_news.py
    """

    DEFAULT_BASE_URL = "https://newsnow.busiyi.world"

    def __init__(self, base_url: str = None):
        self.base_url = (base_url or settings.NEWSNOW_BASE_URL).rstrip("/")

    @retry(**_RETRY)
    async def _fetch_one(
        self, client: httpx.AsyncClient, source_id: str, newsnow_id: str
    ) -> Optional[tuple[str, dict]]:
        """拉取单个热搜源"""
        url = f"{self.base_url}/api/s?id={newsnow_id}&latest"
        try:
            resp = await client.get(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    "Referer": self.base_url,
                    "Connection": "keep-alive",
                },
                timeout=15,
            )
            if resp.status_code >= 400:
                logger.warning(f"NewsNowAdapter: HTTP {resp.status_code} for {source_id}")
                return None
            data = resp.json()
            return source_id, data
        except Exception as e:
            logger.warning(f"NewsNowAdapter: 拉取失败 {source_id} → {e}")
            return None

    async def fetch_all(
        self,
        source_ids: Optional[list[str]] = None,
    ) -> dict[str, dict]:
        """
        并发拉取所有（或指定）热搜源。

        Args:
            source_ids: 要拉取的 source_id 列表，默认全部

        Returns:
            {source_id: api_response_dict}，status=200 且含 items 的有效响应
        """
        targets = {
            sid: nid
            for sid, nid in NEWSNOW_SOURCE_MAP.items()
            if source_ids is None or sid in source_ids
        }
        if not targets:
            return {}

        results: dict[str, dict] = {}
        async with httpx.AsyncClient(timeout=20, http2=True) as client:
            tasks = [self._fetch_one(client, sid, nid) for sid, nid in targets.items()]
            raw = await asyncio.gather(*tasks, return_exceptions=True)

        for result in raw:
            if isinstance(result, Exception) or result is None:
                continue
            sid, data = result
            if isinstance(data, dict) and data.get("items"):
                results[sid] = data
                logger.debug(f"NewsNowAdapter: {sid} → {len(data['items'])} items")

        logger.info(f"NewsNowAdapter: 完成拉取 {len(results)}/{len(targets)} 个热搜源")
        return results

    async def fetch_single(self, source_id: str) -> Optional[dict]:
        """拉取单个热搜源"""
        newsnow_id = NEWSNOW_SOURCE_MAP.get(source_id)
        if not newsnow_id:
            logger.warning(f"NewsNowAdapter: 未知 source_id={source_id}")
            return None
        async with httpx.AsyncClient(timeout=20) as client:
            result = await self._fetch_one(client, source_id, newsnow_id)
        return result[1] if result else None

