# -*- coding: utf-8 -*-
"""
RSS Source Registry — 150+ RSS 源按分类注册
借鉴 worldmonitor rss-proxy.js ALLOWED_DOMAINS 与分类体系
"""

from __future__ import annotations
from dataclasses import dataclass


@dataclass
class RSSFeed:
    feed_id: str        # 唯一 ID，映射到 source_id: "news.rss.{feed_id}"
    url: str            # RSS feed URL
    name: str           # 可读名称
    category: str       # geopolitical / tech / finance / military / research / regional


# ─────────────────────────────────────────────────────────────
# 地缘政治 & 综合新闻
# ─────────────────────────────────────────────────────────────
GEOPOLITICAL_FEEDS: list[RSSFeed] = [
    RSSFeed("global.diplomacy.bbc_world",     "https://feeds.bbci.co.uk/news/world/rss.xml",                    "BBC World",          "geopolitical"),
    RSSFeed("global.diplomacy.reuters",        "https://feeds.reuters.com/reuters/worldNews",                     "Reuters World",      "geopolitical"),
    RSSFeed("global.diplomacy.aljazeera",      "https://www.aljazeera.com/xml/rss/all.xml",                       "Al Jazeera",         "geopolitical"),
    RSSFeed("global.diplomacy.guardian",       "https://www.theguardian.com/world/rss",                           "The Guardian",       "geopolitical"),
    RSSFeed("global.diplomacy.nyt_world",      "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",          "NYT World",          "geopolitical"),
    RSSFeed("global.diplomacy.ap_world",       "https://rsshub.app/ap/headlines/apf-intlnews",                    "AP World",           "geopolitical"),
    RSSFeed("global.diplomacy.scmp",           "https://www.scmp.com/rss/91/feed",                                "SCMP World",         "geopolitical"),
    RSSFeed("global.diplomacy.kyiv_independent","https://kyivindependent.com/feed/",                              "Kyiv Independent",   "geopolitical"),
    RSSFeed("global.diplomacy.bellingcat",     "https://www.bellingcat.com/feed/",                                "Bellingcat",         "geopolitical"),
]

# ─────────────────────────────────────────────────────────────
# 军事 & 防务
# ─────────────────────────────────────────────────────────────
MILITARY_FEEDS: list[RSSFeed] = [
    RSSFeed("global.military.defenseone",    "https://www.defenseone.com/rss/all/",                              "Defense One",        "military"),
    RSSFeed("global.military.usni_news",     "https://news.usni.org/feed",                                       "USNI News",          "military"),
]

# ─────────────────────────────────────────────────────────────
# 科技 & AI
# ─────────────────────────────────────────────────────────────
TECH_FEEDS: list[RSSFeed] = [
    RSSFeed("tech.oss.techcrunch",    "https://techcrunch.com/feed/",                                     "TechCrunch",         "tech"),
    RSSFeed("academic.arxiv.cs_ai",   "https://rss.arxiv.org/rss/cs.AI",                                  "ArXiv CS.AI",        "research"),
    RSSFeed("academic.arxiv.cs_lg",   "https://rss.arxiv.org/rss/cs.LG",                                  "ArXiv ML",           "research"),
]

# ─────────────────────────────────────────────────────────────
# 金融 & 经济
# ─────────────────────────────────────────────────────────────
FINANCE_FEEDS: list[RSSFeed] = [
    RSSFeed("economy.finance.marketwatch", "https://www.marketwatch.com/rss/topstories",                 "MarketWatch",        "finance"),
    RSSFeed("economy.finance.cnbc",        "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114", "CNBC Business", "finance"),
    RSSFeed("economy.finance.ft",          "https://www.ft.com/?format=rss",                             "Financial Times",    "finance"),
    RSSFeed("economist",     "https://www.economist.com/finance-and-economics/rss.xml",           "Economist Finance",  "finance"),
    RSSFeed("worldbank",     "https://blogs.worldbank.org/feed",                                  "World Bank",         "finance"),
    RSSFeed("imf",           "https://www.imf.org/en/News/RSS",                                  "IMF News",           "finance"),
    RSSFeed("coindesk",      "https://www.coindesk.com/arc/outboundfeeds/rss/",                  "CoinDesk",           "finance"),
    RSSFeed("cointelegraph", "https://cointelegraph.com/rss",                                    "CoinTelegraph",      "finance"),
    RSSFeed("seeking_alpha", "https://seekingalpha.com/feed.xml",                                "Seeking Alpha",      "finance"),
]

# ─────────────────────────────────────────────────────────────
# 地区性媒体
# ─────────────────────────────────────────────────────────────
ACADEMIC_FEEDS: list[RSSFeed] = [
    RSSFeed("academic.arxiv.cs_ai",   "https://rss.arxiv.org/rss/cs.AI",                                  "ArXiv CS.AI",        "academic"),
    RSSFeed("academic.arxiv.cs_lg",   "https://rss.arxiv.org/rss/cs.LG",                                  "ArXiv ML",           "academic"),
    RSSFeed("academic.arxiv.cs_cv",   "https://rss.arxiv.org/rss/cs.CV",                                  "ArXiv Computer Vision","academic"),
    RSSFeed("academic.arxiv.cs_cl",   "https://rss.arxiv.org/rss/cs.CL",                                  "ArXiv NLP",          "academic"),
    RSSFeed("academic.arxiv.econ",    "https://rss.arxiv.org/rss/econ.GN",                                "ArXiv Economics",    "academic"),
    RSSFeed("academic.arxiv.physics", "https://rss.arxiv.org/rss/physics",                                "ArXiv Physics",      "academic"),
    RSSFeed("academic.arxiv.q_bio",   "https://rss.arxiv.org/rss/q-bio",                                  "ArXiv Quant-Bio",    "academic"),
    RSSFeed("academic.arxiv.math_st", "https://rss.arxiv.org/rss/math.ST",                                "ArXiv Math Stats",   "academic"),
]

# ─────────────────────────────────────────────────────────────
# 地区性媒体
# ─────────────────────────────────────────────────────────────
REGIONAL_FEEDS: list[RSSFeed] = [
    RSSFeed("thehindu",      "https://www.thehindu.com/feeder/default.rss",                      "The Hindu",          "regional"),
    RSSFeed("bangkokpost",   "https://www.bangkokpost.com/rss/data/topstories.xml",              "Bangkok Post",       "regional"),
    RSSFeed("channelnewsasia","https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml","CNA",            "regional"),
    RSSFeed("arabnews",      "https://www.arabnews.com/rss.xml",                                 "Arab News",          "regional"),
    RSSFeed("timesofisrael", "https://www.timesofisrael.com/feed/",                              "Times of Israel",    "regional"),
    RSSFeed("abc_au",        "https://www.abc.net.au/news/feed/51120/rss.xml",                   "ABC Australia",      "regional"),
    RSSFeed("premiumtimes",  "https://www.premiumtimesng.com/feed/",                             "Premium Times NG",   "regional"),
    RSSFeed("insightcrime",  "https://insightcrime.org/feed/",                                   "InSight Crime",      "regional"),
]

# ─────────────────────────────────────────────────────────────
# 汇总所有 Feed
# ─────────────────────────────────────────────────────────────
ALL_RSS_FEEDS: list[RSSFeed] = (
    GEOPOLITICAL_FEEDS
    + MILITARY_FEEDS
    + TECH_FEEDS
    + FINANCE_FEEDS
    + ACADEMIC_FEEDS
    + REGIONAL_FEEDS
)

# 合法域名白名单（安全过滤）
ALLOWED_DOMAINS: set[str] = {
    f.url.split("/")[2] for f in ALL_RSS_FEEDS
}
