# -*- coding: utf-8 -*-
"""
MilitaryNormalizer — ADS-B / AIS / USNI 军事数据规范化器
MarketNormalizer — CoinGecko / EIA 市场数据规范化器
CyberNormalizer — Feodo Tracker / URLhaus 网络威胁规范化器
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional, Any

from data_alignment.schema import (
    CanonicalItem,
    SourceType,
    SeverityLevel,
)


# ══════════════════════════════════════════════════════════════
# MilitaryNormalizer
# ══════════════════════════════════════════════════════════════

class MilitaryNormalizer:
    """ADS-B 军事飞行 / AIS 舰船数据规范化器"""

    def normalize_opensky(self, state_vector: list | tuple) -> Optional[CanonicalItem]:
        """
        OpenSky Network state vector (array) → CanonicalItem。
        格式: [icao24, callsign, origin_country, time_position,
               last_contact, longitude, latitude, baro_altitude,
               on_ground, velocity, true_track, vertical_rate,
               sensors, geo_altitude, squawk, spi, position_source]
        """
        if not state_vector or len(state_vector) < 7:
            return None

        icao24 = state_vector[0] or "unknown"
        callsign = (state_vector[1] or "").strip() or icao24
        origin_country = state_vector[2] or ""
        lon = state_vector[5]
        lat = state_vector[6]
        altitude = state_vector[7]
        velocity = state_vector[9]
        on_ground = state_vector[8]

        if on_ground:
            return None  # 排除地面静止的飞机

        title = f"[ADS-B] {callsign} ({origin_country}) @ {altitude}m"
        item_id = f"military.opensky:{icao24}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

        return CanonicalItem(
            item_id=item_id,
            source_id="military.opensky",
            source_type=SourceType.MILITARY,
            title=title,
            body=None,
            author=None,
            url=f"https://opensky-network.org/aircraft-profile?icao24={icao24}",
            published_at=datetime.now(timezone.utc),
            geo_lat=float(lat) if lat is not None else None,
            geo_lon=float(lon) if lon is not None else None,
            geo_country=None,
            geo_region=origin_country,
            hotness_score=0.0,
            severity_level=SeverityLevel.INFO,
            raw_engagement={},
            raw_metadata={
                "icao24": icao24,
                "callsign": callsign,
                "altitude_m": altitude,
                "velocity_ms": velocity,
                "origin_country": origin_country,
            },
            categories=["military", "aviation"],
            keywords=["adsb", "flight", callsign.strip()],
            is_classified=True,
            classification_source="adsb_state",
        )

    def normalize_ais_snapshot(self, vessel: dict) -> Optional[CanonicalItem]:
        """
        AIS vessel JSON 快照 → CanonicalItem。
        """
        mmsi = vessel.get("mmsi") or vessel.get("MMSI")
        if not mmsi:
            return None

        name = vessel.get("name") or vessel.get("shipname") or str(mmsi)
        lat = vessel.get("lat") or vessel.get("LAT")
        lon = vessel.get("lon") or vessel.get("LON")
        ship_type = vessel.get("shiptype") or vessel.get("type_name", "Unknown")
        flag = vessel.get("flag") or vessel.get("FLAG", "")

        title = f"[AIS] {name} ({ship_type}) — {flag}"
        item_id = f"military.ais:{mmsi}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

        return CanonicalItem(
            item_id=item_id,
            source_id="military.ais",
            source_type=SourceType.MILITARY,
            title=title,
            body=None,
            author=None,
            url=None,
            published_at=datetime.now(timezone.utc),
            geo_lat=float(lat) if lat is not None else None,
            geo_lon=float(lon) if lon is not None else None,
            geo_country=str(flag).upper() if flag else None,
            geo_region=None,
            hotness_score=0.0,
            severity_level=SeverityLevel.INFO,
            raw_engagement={},
            raw_metadata={
                "mmsi": mmsi,
                "ship_type": ship_type,
                "speed": vessel.get("speed"),
                "course": vessel.get("course"),
            },
            categories=["military", "maritime"],
            keywords=["ais", "vessel", ship_type],
            is_classified=True,
            classification_source="ais_state",
        )


# ══════════════════════════════════════════════════════════════
# MarketNormalizer
# ══════════════════════════════════════════════════════════════

class MarketNormalizer:
    """CoinGecko 加密货币 / EIA 能源价格规范化器"""

    def normalize_coingecko_simple(self, coin_id: str, data: dict) -> Optional[CanonicalItem]:
        """
        CoinGecko /simple/price 响应 → CanonicalItem。
        data = {"usd": 65000, "usd_24h_change": -2.3, ...}
        """
        usd = data.get("usd")
        if usd is None:
            return None

        change = data.get("usd_24h_change", 0.0) or 0.0
        direction = "📈" if change >= 0 else "📉"
        title = f"[CRYPTO] {coin_id.upper()} ${usd:,.2f} {direction} {change:+.2f}%"
        item_id = f"market.coingecko:{coin_id}:{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"

        # 大幅波动升级严重等级
        abs_change = abs(change)
        if abs_change >= 20:
            severity = SeverityLevel.HIGH
        elif abs_change >= 10:
            severity = SeverityLevel.MEDIUM
        elif abs_change >= 5:
            severity = SeverityLevel.LOW
        else:
            severity = SeverityLevel.INFO

        return CanonicalItem(
            item_id=item_id,
            source_id="market.coingecko",
            source_type=SourceType.MARKET,
            title=title,
            body=None,
            author="CoinGecko",
            url=f"https://www.coingecko.com/en/coins/{coin_id}",
            published_at=datetime.now(timezone.utc),
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "coin_id": coin_id,
                "usd_price": usd,
                "usd_24h_change": change,
                "market_cap": data.get("usd_market_cap"),
                "volume": data.get("usd_24h_vol"),
            },
            categories=["market", "crypto"],
            keywords=["crypto", coin_id],
            is_classified=True,
            classification_source="price_change",
        )


# ══════════════════════════════════════════════════════════════
# CyberNormalizer
# ══════════════════════════════════════════════════════════════

class CyberNormalizer:
    """
    网络威胁情报规范化器。
    支持: Feodo Tracker (C2) / URLhaus (恶意 URL) / C2IntelFeeds
    """

    def normalize_feodo(self, row: dict) -> Optional[CanonicalItem]:
        """
        Feodo Tracker CSV row → CanonicalItem。
        格式: ip_address, port, status, malware, as_number, as_name, country, first_seen, last_online
        """
        ip = row.get("ip_address") or row.get("Dst IP")
        if not ip:
            return None

        malware = row.get("malware", "Unknown")
        country = row.get("country", "")
        status = row.get("status", "")
        port = row.get("port", "")

        title = f"[C2] {malware} C2 Server: {ip}:{port} [{country}] ({status})"
        item_id = f"cyber.feodo:{hashlib.md5(f'{ip}:{port}'.encode()).hexdigest()[:16]}"

        severity = SeverityLevel.HIGH if status.lower() == "online" else SeverityLevel.MEDIUM

        first_seen_str = row.get("first_seen", "")
        published_at = None
        if first_seen_str:
            try:
                published_at = datetime.fromisoformat(first_seen_str.replace(" ", "T")).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return CanonicalItem(
            item_id=item_id,
            source_id="cyber.feodo",
            source_type=SourceType.CYBER,
            title=title,
            body=None,
            author="Feodo Tracker",
            url=f"https://feodotracker.abuse.ch/browse/host/{ip}/",
            published_at=published_at,
            geo_country=str(country).upper() if country else None,
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "ip": ip,
                "port": port,
                "malware": malware,
                "status": status,
                "asn": row.get("as_number"),
                "as_name": row.get("as_name"),
            },
            categories=["cyber", "c2", "threat"],
            keywords=["c2", malware.lower(), ip],
            is_classified=True,
            classification_source="feodo_status",
        )

    def normalize_urlhaus(self, entry: dict) -> Optional[CanonicalItem]:
        """
        URLhaus API entry → CanonicalItem。
        """
        url_str = entry.get("url")
        if not url_str:
            return None

        threat = entry.get("threat", "malware")
        tags = entry.get("tags", [])
        url_status = entry.get("url_status", "online")
        title = f"[URLhaus] {threat}: {url_str[:80]}"
        item_id = f"cyber.urlhaus:{hashlib.sha1(url_str.encode()).hexdigest()[:16]}"

        severity = SeverityLevel.HIGH if url_status == "online" else SeverityLevel.MEDIUM

        date_added = entry.get("date_added", "")
        published_at = None
        if date_added:
            try:
                published_at = datetime.fromisoformat(date_added.replace(" ", "T")).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        return CanonicalItem(
            item_id=item_id,
            source_id="cyber.urlhaus",
            source_type=SourceType.CYBER,
            title=title,
            body=None,
            author="URLhaus",
            url=url_str,
            published_at=published_at,
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "threat": threat,
                "url_status": url_status,
                "urlhaus_link": entry.get("urlhaus_link"),
                "payloads": entry.get("payloads"),
            },
            categories=["cyber", "malware", "threat"],
            keywords=["malware", threat] + (tags[:5] if isinstance(tags, list) else []),
            is_classified=True,
            classification_source="urlhaus_threat",
        )
