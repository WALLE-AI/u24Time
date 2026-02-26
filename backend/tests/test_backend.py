# -*- coding: utf-8 -*-
"""
Unit tests for DataAlignmentModel schema, normalizers, and deduplicator.
Run: uv run pytest tests/ -v
"""

import math
from datetime import datetime, timezone

import pytest

# ── Schema & HotnessCalculator ──────────────────────────────

def test_hotness_zero_engagement():
    from data_alignment.schema import HotnessCalculator
    score = HotnessCalculator.score({})
    assert score == 0.0


def test_hotness_positive():
    from data_alignment.schema import HotnessCalculator
    engagement = {"likes": 10000, "comments": 1000, "shares": 500, "views": 500000}
    score = HotnessCalculator.score(engagement)
    assert 0.0 < score <= 100.0


def test_hotness_capped_at_100():
    from data_alignment.schema import HotnessCalculator
    engagement = {"likes": 9_999_999, "shares": 9_999_999, "comments": 9_999_999}
    score = HotnessCalculator.score(engagement, max_score=1_000_000.0)
    assert score == 100.0


def test_canonical_item_to_dict():
    from data_alignment.schema import CanonicalItem, SourceType, SeverityLevel
    item = CanonicalItem(
        item_id="social.bilibili:12345",
        source_id="social.bilibili",
        source_type=SourceType.SOCIAL,
        title="测试标题",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    d = item.to_dict()
    assert d["item_id"] == "social.bilibili:12345"
    assert d["source_type"] == "social"
    assert d["published_at"] == "2026-01-01T00:00:00+00:00"
    assert d["hotness_score"] == 0.0


def test_severity_keywords_critical():
    from data_alignment.schema import classify_severity_by_keywords, SeverityLevel
    sev, src = classify_severity_by_keywords("Nuclear weapon facility detected")
    assert sev == SeverityLevel.CRITICAL
    assert src == "keyword"


def test_severity_keywords_info():
    from data_alignment.schema import classify_severity_by_keywords, SeverityLevel
    sev, src = classify_severity_by_keywords("A beautiful sunny day in the park")
    assert sev == SeverityLevel.INFO


# ── SocialNormalizer ─────────────────────────────────────────

def test_social_normalizer_bilibili():
    from data_alignment.normalizers.social_normalizer import SocialNormalizer
    normalizer = SocialNormalizer()
    row = {
        "id": "bv123456",
        "title": "Python 教程 2026",
        "liked_count": 50000,
        "video_comment": 3000,
        "video_share_count": 1200,
        "video_play_count": 1_000_000,
        "create_time": 1740000000,
    }
    item = normalizer.normalize(row, "bilibili")
    assert item is not None
    assert item.source_id == "social.bilibili"
    assert item.source_type == "social"
    assert item.hotness_score > 0
    assert item.published_at is not None
    assert item.raw_engagement["likes"] == 50000


def test_social_normalizer_empty_title_returns_none():
    from data_alignment.normalizers.social_normalizer import SocialNormalizer
    normalizer = SocialNormalizer()
    item = normalizer.normalize({"liked_count": 100}, "weibo")
    assert item is None


# ── NewsNormalizer ───────────────────────────────────────────

def test_news_normalizer_feedparser_entry():
    from data_alignment.normalizers.news_normalizer import NewsNormalizer
    normalizer = NewsNormalizer()
    entry = {
        "title": "Ukraine ceasefire talks collapse",
        "link": "https://www.bbc.co.uk/news/12345",
        "summary": "Negotiations have broken down again.",
        "published_parsed": (2026, 1, 15, 12, 0, 0, 2, 15, 0),
    }
    item = normalizer.normalize_from_feedparser(entry, "news.rss.bbc", "geopolitical")
    assert item is not None
    assert item.source_id == "news.rss.bbc"
    assert item.source_type == "news"
    assert "news" in item.categories
    assert item.severity_level in ("info", "low", "medium", "high", "critical")


# ── GeoEventNormalizer ───────────────────────────────────────

def test_usgs_normalizer():
    from data_alignment.normalizers.geo_event_normalizer import GeoEventNormalizer
    normalizer = GeoEventNormalizer()
    feature = {
        "id": "us7000test",
        "properties": {
            "mag": 7.2,
            "place": "100km SE of Tokyo, Japan",
            "time": 1740000000000,
            "url": "https://earthquake.usgs.gov/earthquakes/eventpage/us7000test",
        },
        "geometry": {"coordinates": [139.7, 35.5, 10.0]},
    }
    item = normalizer.normalize_usgs(feature)
    assert item is not None
    assert item.source_id == "geo.usgs"
    assert item.geo_lat == 35.5
    assert item.geo_lon == 139.7
    assert item.severity_level == "high"  # M7.2 → HIGH


def test_acled_normalizer():
    from data_alignment.normalizers.geo_event_normalizer import GeoEventNormalizer
    normalizer = GeoEventNormalizer()
    event = {
        "data_id": "1234",
        "event_date": "2026-01-15",
        "event_type": "Protests",
        "sub_event_type": "Peaceful protest",
        "country": "India",
        "location": "New Delhi",
        "latitude": 28.6,
        "longitude": 77.2,
        "fatalities": 0,
        "notes": "Large protest outside parliament",
        "source": "The Hindu",
    }
    item = normalizer.normalize_acled(event)
    assert item is not None
    assert item.source_id == "geo.acled"
    assert item.geo_lat == 28.6
    assert item.categories[0] == "conflict"


# ── CyberNormalizer ──────────────────────────────────────────

def test_feodo_normalizer():
    from data_alignment.normalizers.combined_normalizers import CyberNormalizer
    normalizer = CyberNormalizer()
    row = {
        "first_seen": "2026-01-10 12:00:00",
        "ip_address": "192.168.1.100",
        "port": "443",
        "status": "online",
        "as_number": "12345",
        "as_name": "ACME-ISP",
        "country": "RU",
        "malware": "Emotet",
    }
    item = normalizer.normalize_feodo(row)
    assert item is not None
    assert item.source_id == "tech.cyber.feodo"
    assert item.source_type == "cyber"
    assert item.severity_level == "high"  # status=online → HIGH
    assert "c2" in item.categories
    assert item.domain == "technology"
    assert item.sub_domain == "cyber"


# ── Deduplicator ─────────────────────────────────────────────

def test_deduplicator_exact_id():
    from data_alignment.deduplicator import Deduplicator
    from data_alignment.schema import CanonicalItem, SourceType
    dedup = Deduplicator()
    item = CanonicalItem(item_id="social.wb:1", source_id="social.weibo", source_type=SourceType.SOCIAL, title="test")
    result = dedup.deduplicate([item, item])  # 重复
    assert len(result) == 1


def test_deduplicator_jaccard():
    from data_alignment.deduplicator import Deduplicator
    from data_alignment.schema import CanonicalItem, SourceType
    dedup = Deduplicator()
    a = CanonicalItem(item_id="news:1", source_id="news.rss.bbc", source_type=SourceType.NEWS,
                      title="Ukraine ceasefire talks collapse in Geneva")
    b = CanonicalItem(item_id="news:2", source_id="news.rss.reuters", source_type=SourceType.NEWS,
                      title="Ukraine ceasefire talks collapse in geneva city")
    result = dedup.deduplicate([a, b])
    assert len(result) == 1  # Jaccard 高度相似 → 去重


def test_deduplicator_different_titles_kept():
    from data_alignment.deduplicator import Deduplicator
    from data_alignment.schema import CanonicalItem, SourceType
    dedup = Deduplicator()
    a = CanonicalItem(item_id="news:1", source_id="news.rss.bbc", source_type=SourceType.NEWS,
                      title="Stock market rallies on Fed decision")
    b = CanonicalItem(item_id="news:2", source_id="news.rss.reuters", source_type=SourceType.NEWS,
                      title="Earthquake M6.8 hits Turkey eastern province")
    result = dedup.deduplicate([a, b])
    assert len(result) == 2


# ── DataSource Registry ──────────────────────────────────────

def test_registry_has_sources():
    from data_source.registry import registry
    sources = registry.all()
    assert len(sources) >= 20


def test_registry_by_type():
    from data_source.registry import registry
    social = registry.by_type("social")
    assert len(social) >= 7
    assert all(s.source_type == "social" for s in social)


def test_registry_get():
    from data_source.registry import registry
    s = registry.get("global.disaster.usgs")
    assert s is not None
    assert "USGS" in s.name
    assert s.api_key_required is False
    assert s.domain == "global"
    assert s.sub_domain == "disaster"


# ── RSS Sources ───────────────────────────────────────────────

def test_rss_sources_count():
    from crawler_engine.news.rss_sources import ALL_RSS_FEEDS, GEOPOLITICAL_FEEDS
    assert len(ALL_RSS_FEEDS) >= 50
    assert len(GEOPOLITICAL_FEEDS) >= 20


def test_rss_sources_allowed_domains():
    from crawler_engine.news.rss_sources import ALL_RSS_FEEDS, ALLOWED_DOMAINS
    for feed in ALL_RSS_FEEDS:
        domain = feed.url.split("/")[2]
        assert domain in ALLOWED_DOMAINS, f"{feed.feed_id} domain not in allowlist"
