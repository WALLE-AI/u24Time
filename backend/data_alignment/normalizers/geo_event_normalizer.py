# -*- coding: utf-8 -*-
"""
GeoEventNormalizer — ACLED / GDELT / USGS 地理事件规范化器

数据对齐策略:
- ACLED: 提供 fatalities 决定 severity，提供精确纬经度
- GDELT: 提供 ActionGeo_Lat / ActionGeo_Long + 事件码(CAMEO)
- USGS: magnitude → severity mapping
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
    classify_severity_by_keywords,
)


def _severity_from_fatalities(fatalities: Any) -> str:
    try:
        n = int(float(fatalities or 0))
    except (ValueError, TypeError):
        n = 0
    if n >= 50:
        return SeverityLevel.CRITICAL
    if n >= 10:
        return SeverityLevel.HIGH
    if n > 0:
        return SeverityLevel.MEDIUM
    return SeverityLevel.LOW


def _severity_from_magnitude(magnitude: Any) -> str:
    try:
        m = float(magnitude or 0)
    except (ValueError, TypeError):
        m = 0.0
    if m >= 8.0:
        return SeverityLevel.CRITICAL
    if m >= 7.0:
        return SeverityLevel.HIGH
    if m >= 6.0:
        return SeverityLevel.MEDIUM
    if m >= 4.5:
        return SeverityLevel.LOW
    return SeverityLevel.INFO


def _parse_iso_date(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


class GeoEventNormalizer:
    """地理事件规范化器（ACLED / GDELT / USGS）"""

    def normalize_acled(self, event: dict) -> Optional[CanonicalItem]:
        """
        ACLED API 响应中单个事件对象 → CanonicalItem。
        文档: https://acleddata.com/resources/general-guides/
        """
        event_id = event.get("data_id") or event.get("event_id_cnty")
        if not event_id:
            return None

        source_id = "geo.acled"
        item_id = f"{source_id}:{event_id}"
        country = event.get("country", "")
        location = event.get("location", "")
        event_type = event.get("event_type", "")
        sub_type = event.get("sub_event_type", "")
        notes = event.get("notes", "")
        title = f"[{event_type}] {location}, {country}: {sub_type}"

        lat = event.get("latitude")
        lon = event.get("longitude")
        iso = event.get("iso_code") or event.get("country_code")

        fatalities = event.get("fatalities", 0)
        severity = _severity_from_fatalities(fatalities)

        # 补充关键词分类
        kw_sev, _ = classify_severity_by_keywords(f"{event_type} {sub_type} {notes}")
        # 取更高者
        from data_alignment.schema import SeverityLevel as SL
        severity = SL.higher(severity, kw_sev)

        event_date = _parse_iso_date(event.get("event_date") or "")

        return CanonicalItem(
            item_id=item_id,
            source_id=source_id,
            source_type=SourceType.GEO,
            title=title,
            body=notes or None,
            author=event.get("source"),
            url=None,
            published_at=event_date,
            geo_lat=float(lat) if lat is not None else None,
            geo_lon=float(lon) if lon is not None else None,
            geo_country=str(iso).upper() if iso else None,
            geo_region=location,
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "event_type": event_type,
                "sub_event_type": sub_type,
                "fatalities": fatalities,
                "actors": [event.get("actor1"), event.get("actor2")],
            },
            categories=["conflict", "geopolitical"],
            keywords=[event_type, sub_type, country],
            is_classified=True,
            classification_source="acled_fatalities",
        )

    def normalize_usgs(self, feature: dict) -> Optional[CanonicalItem]:
        """
        USGS Earthquake API GeoJSON feature → CanonicalItem。
        文档: https://earthquake.usgs.gov/fdsnws/event/1/
        """
        props = feature.get("properties", {})
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates", [None, None, None])

        eq_id = feature.get("id") or props.get("ids", "unknown")
        mag = props.get("mag")
        place = props.get("place", "Unknown location")
        title = f"M{mag} Earthquake — {place}"

        lon = coords[0] if len(coords) > 0 else None
        lat = coords[1] if len(coords) > 1 else None
        depth = coords[2] if len(coords) > 2 else None

        ts = props.get("time")
        published_at = None
        if ts:
            try:
                published_at = datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc)
            except (ValueError, TypeError, OverflowError):
                pass

        severity = _severity_from_magnitude(mag)

        return CanonicalItem(
            item_id=f"geo.usgs:{eq_id}",
            source_id="geo.usgs",
            source_type=SourceType.GEO,
            title=title,
            body=props.get("detail"),
            author="USGS",
            url=props.get("url"),
            published_at=published_at,
            geo_lat=float(lat) if lat is not None else None,
            geo_lon=float(lon) if lon is not None else None,
            geo_country=None,
            geo_region=place,
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "magnitude": mag,
                "depth_km": depth,
                "felt": props.get("felt"),
                "tsunami": props.get("tsunami"),
            },
            categories=["seismology", "disaster"],
            keywords=["earthquake", f"M{mag}"],
            is_classified=True,
            classification_source="usgs_magnitude",
        )

    def normalize_gdelt(self, row: dict) -> Optional[CanonicalItem]:
        """
        GDELT API CSV row (dict) → CanonicalItem。
        使用 GDELT 2.0 GKG 或 Events API 字段。
        """
        event_id = row.get("GLOBALEVENTID") or row.get("event_id")
        if not event_id:
            return None

        source_id = "geo.gdelt"
        title_raw = row.get("title") or row.get("SOURCEURL", "")
        if not title_raw:
            title_raw = f"GDELT Event {event_id}"

        lat = row.get("ActionGeo_Lat") or row.get("lat")
        lon = row.get("ActionGeo_Long") or row.get("lon")
        country = row.get("ActionGeo_CountryCode") or row.get("country_code")
        geo_name = row.get("ActionGeo_FullName") or row.get("geo_name")

        event_date_str = row.get("SQLDATE") or row.get("date") or ""
        published_at = None
        if event_date_str:
            try:
                published_at = datetime.strptime(str(event_date_str), "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        full_text = f"{title_raw} {row.get('SOURCEURL', '')}"
        severity, cls_src = classify_severity_by_keywords(full_text)

        return CanonicalItem(
            item_id=f"{source_id}:{event_id}",
            source_id=source_id,
            source_type=SourceType.GEO,
            title=title_raw[:512],
            body=None,
            author="GDELT",
            url=row.get("SOURCEURL"),
            published_at=published_at,
            geo_lat=float(lat) if lat else None,
            geo_lon=float(lon) if lon else None,
            geo_country=str(country).upper() if country else None,
            geo_region=geo_name,
            hotness_score=0.0,
            severity_level=severity,
            raw_engagement={},
            raw_metadata={
                "cameo_code": row.get("EventCode"),
                "root_code": row.get("EventRootCode"),
                "goldstein_scale": row.get("GoldsteinScale"),
            },
            categories=["geopolitical"],
            keywords=[str(row.get("EventCode", ""))],
            is_classified=True,
            classification_source=cls_src,
        )
