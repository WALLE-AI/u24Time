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
    HotnessCalculator,
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

        # 伤亡人数加分：每人 +0.5，上限 +20
        fatality_bonus = min(float(fatalities or 0) * 0.5, 20.0)
        hotness = HotnessCalculator.time_decay_score(severity, event_date, bonus=fatality_bonus)

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
            hotness_score=hotness,
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

        # 震级加分：M4.5以上每0.5级 +2.5，上限 +20（M6.5 ≈ +10，M8.5 ≈ +20）
        try:
            mag_f = float(mag or 0)
        except (ValueError, TypeError):
            mag_f = 0.0
        mag_bonus = min(max(0.0, (mag_f - 4.5) * 5.0), 20.0)
        hotness = HotnessCalculator.time_decay_score(severity, published_at, bonus=mag_bonus)

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
            hotness_score=hotness,
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

        hotness = HotnessCalculator.time_decay_score(severity, published_at)

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
            hotness_score=hotness,
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

    def normalize_reliefweb(self, item: dict, source_id: str = "global.conflict.humanitarian") -> Optional[CanonicalItem]:
        """
        ReliefWeb API /v1/disasters or /v1/reports item → CanonicalItem.
        文档: https://api.reliefweb.int/v1/disasters
        """
        try:
            from data_alignment.schema import DomainType, SubDomainType
            fields = item.get("fields", item)
            rw_id = str(item.get("id", fields.get("id", "")))
            title = fields.get("name", fields.get("title", {}).get("value", ""))
            if not title:
                return None
            url = fields.get("url", f"https://reliefweb.int/disaster/{rw_id}")
            date_str = fields.get("date", {}).get("event") or fields.get("date", {}).get("created", "")
            published_at = _parse_iso_date(date_str) if date_str else None
            status = fields.get("status", "")
            country_list = fields.get("country", [])
            geo_country = country_list[0].get("iso3") if country_list else None

            severity_map = {"alert": SeverityLevel.HIGH, "ongoing": SeverityLevel.MEDIUM, "past": SeverityLevel.LOW}
            severity = severity_map.get(status.lower(), SeverityLevel.INFO)
            kw_sev, _ = classify_severity_by_keywords(title)
            from data_alignment.schema import SeverityLevel as SL
            severity = SL.higher(severity, kw_sev)

            hotness = HotnessCalculator.time_decay_score(severity, published_at)
            return CanonicalItem(
                item_id=f"{source_id}:{rw_id}",
                source_id=source_id,
                source_type=SourceType.GEO,
                domain=DomainType.GLOBAL,
                sub_domain=SubDomainType.CONFLICT,
                title=f"[人道危机] {title}",
                url=url,
                published_at=published_at,
                geo_country=geo_country,
                hotness_score=hotness,
                severity_level=severity,
                raw_metadata={"rw_id": rw_id, "status": status, "countries": country_list},
                categories=["humanitarian", "crisis", "reliefweb"],
                is_classified=True,
                classification_source="reliefweb_status",
            )
        except Exception as e:
            logger.warning(f"normalize_reliefweb failed: {e}")
            return None

    def normalize_nasa_firms(self, row: dict, source_id: str = "global.disaster.nasa_firms") -> Optional[CanonicalItem]:
        """
        NASA FIRMS CSV row dict → CanonicalItem.
        文档: https://firms.modaps.eosdis.nasa.gov/api/
        """
        try:
            from data_alignment.schema import DomainType, SubDomainType
            lat = row.get("latitude")
            lon = row.get("longitude")
            if lat is None or lon is None:
                return None

            bright_t = float(row.get("bright_t31", row.get("brightness", 300)))
            frp = float(row.get("frp", 0))
            acq_date = row.get("acq_date", "")
            acq_time = row.get("acq_time", "")
            country_id = row.get("country_id", "")
            satellite = row.get("satellite", "VIIRS")

            # FRP (Fire Radiative Power, MW) → severity
            severity = SeverityLevel.CRITICAL if frp >= 1000 else \
                       SeverityLevel.HIGH if frp >= 100 else \
                       SeverityLevel.MEDIUM if frp >= 10 else SeverityLevel.LOW

            title = f"[野火] {satellite} 火点检测 FRP={frp:.0f}MW @ ({float(lat):.2f},{float(lon):.2f})"
            if country_id:
                title += f" [{country_id}]"

            import hashlib
            raw = f"{lat}:{lon}:{acq_date}:{acq_time}"
            item_id = hashlib.md5(raw.encode()).hexdigest()[:16]

            # FRP 加分：每 100MW +2，上限 +20（FRP≥1000MW ≈ +20）
            frp_bonus = min(frp / 50.0, 20.0)
            pub_dt = _parse_iso_date(acq_date)
            hotness = HotnessCalculator.time_decay_score(severity, pub_dt, bonus=frp_bonus)
            return CanonicalItem(
                item_id=item_id,
                source_id=source_id,
                source_type=SourceType.GEO,
                domain=DomainType.GLOBAL,
                sub_domain=SubDomainType.DISASTER,
                title=title,
                published_at=pub_dt,
                geo_lat=float(lat),
                geo_lon=float(lon),
                geo_country=country_id or None,
                hotness_score=hotness,
                severity_level=severity,
                raw_metadata={
                    "frp_mw": frp,
                    "brightness": bright_t,
                    "satellite": satellite,
                    "acq_date": acq_date,
                    "acq_time": acq_time,
                },
                categories=["wildfire", "nasa", "fire"],
                is_classified=True,
                classification_source="frp_threshold",
            )
        except Exception as e:
            logger.warning(f"normalize_nasa_firms failed: {e}")
            return None

