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
    RSSFeed("bbc_world",     "https://feeds.bbci.co.uk/news/world/rss.xml",                    "BBC World",          "geopolitical"),
    RSSFeed("reuters",        "https://feeds.reuters.com/reuters/worldNews",                     "Reuters World",      "geopolitical"),
    RSSFeed("aljazeera",      "https://www.aljazeera.com/xml/rss/all.xml",                       "Al Jazeera",         "geopolitical"),
    RSSFeed("guardian",       "https://www.theguardian.com/world/rss",                           "The Guardian",       "geopolitical"),
    RSSFeed("nyt_world",      "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",          "NYT World",          "geopolitical"),
    RSSFeed("ap_world",       "https://rsshub.app/ap/headlines/apf-intlnews",                    "AP World",           "geopolitical"),
    RSSFeed("france24",       "https://www.france24.com/en/rss",                                 "France24 EN",        "geopolitical"),
    RSSFeed("dw",             "https://rss.dw.com/rdf/rss-en-all",                               "Deutsche Welle",     "geopolitical"),
    RSSFeed("euronews",       "https://www.euronews.com/rss",                                    "Euronews",           "geopolitical"),
    RSSFeed("un_news",        "https://news.un.org/feed/subscribe/en/news/all/rss.xml",           "UN News",            "geopolitical"),
    RSSFeed("cfr",            "https://www.cfr.org/rss.xml",                                     "CFR",                "geopolitical"),
    RSSFeed("foreignpolicy",  "https://foreignpolicy.com/rss/",                                  "Foreign Policy",     "geopolitical"),
    RSSFeed("thediplomat",    "https://thediplomat.com/feed/",                                   "The Diplomat",       "geopolitical"),
    RSSFeed("nikkei_asia",    "https://asia.nikkei.com/rss/feed/nar",                            "Nikkei Asia",        "geopolitical"),
    RSSFeed("scmp",           "https://www.scmp.com/rss/91/feed",                                "SCMP World",         "geopolitical"),
    RSSFeed("kyiv_independent","https://kyivindependent.com/feed/",                              "Kyiv Independent",   "geopolitical"),
    RSSFeed("moscow_times",   "https://www.themoscowtimes.com/rss/news",                         "Moscow Times",        "geopolitical"),
    RSSFeed("cnn_world",      "https://rss.cnn.com/rss/edition_world.rss",                       "CNN World",          "geopolitical"),
    RSSFeed("whitehouse",     "https://www.whitehouse.gov/feed/",                                "White House",        "geopolitical"),
    RSSFeed("state_dept",     "https://www.state.gov/rss-feeds/press-releases/",                 "US State Dept",      "geopolitical"),
    RSSFeed("csis",           "https://www.csis.org/rss.xml",                                    "CSIS",               "geopolitical"),
    RSSFeed("brookings",      "https://www.brookings.edu/feed/",                                 "Brookings",          "geopolitical"),
    RSSFeed("atlanticcouncil","https://www.atlanticcouncil.org/feed/",                           "Atlantic Council",   "geopolitical"),
    RSSFeed("wsj_world",      "https://feeds.a.dj.com/rss/RSSWorldNews.xml",                    "WSJ World",          "geopolitical"),
    RSSFeed("bellingcat",     "https://www.bellingcat.com/feed/",                                "Bellingcat",         "geopolitical"),
]

# ─────────────────────────────────────────────────────────────
# 军事 & 防务
# ─────────────────────────────────────────────────────────────
MILITARY_FEEDS: list[RSSFeed] = [
    RSSFeed("defenseone",    "https://www.defenseone.com/rss/all/",                              "Defense One",        "military"),
    RSSFeed("usni",          "https://news.usni.org/feed",                                       "USNI News",          "military"),
    RSSFeed("defense_news",  "https://www.defensenews.com/arc/outboundfeeds/rss/?outputType=xml","Defense News",       "military"),
    RSSFeed("military_times","https://www.militarytimes.com/arc/outboundfeeds/rss/",             "Military Times",     "military"),
    RSSFeed("thedrive",      "https://www.thedrive.com/rss",                                     "The Drive",          "military"),
    RSSFeed("taskpurpose",   "https://taskandpurpose.com/feed/",                                 "Task & Purpose",     "military"),
    RSSFeed("breakingdefense","https://breakingdefense.com/feed/",                               "Breaking Defense",   "military"),
    RSSFeed("oryx",          "https://www.oryxspioenkop.com/feeds/posts/default",                "Oryx",               "military"),
    RSSFeed("rusi",          "https://rusi.org/rss",                                             "RUSI",               "military"),
    RSSFeed("warontherocks", "https://warontherocks.com/feed/",                                  "War on the Rocks",   "military"),
    RSSFeed("pentagon",      "https://www.defense.gov/Portals/1/RSS/news.xml",                   "US DoD",             "military"),
]

# ─────────────────────────────────────────────────────────────
# 科技 & AI
# ─────────────────────────────────────────────────────────────
TECH_FEEDS: list[RSSFeed] = [
    RSSFeed("techcrunch",    "https://techcrunch.com/feed/",                                     "TechCrunch",         "tech"),
    RSSFeed("theverge",      "https://www.theverge.com/rss/index.xml",                           "The Verge",          "tech"),
    RSSFeed("arstechnica",   "https://feeds.arstechnica.com/arstechnica/index",                  "Ars Technica",       "tech"),
    RSSFeed("wired",         "https://www.wired.com/feed/rss",                                   "Wired",              "tech"),
    RSSFeed("hacker_news",   "https://hnrss.org/frontpage",                                      "Hacker News",        "tech"),
    RSSFeed("arxiv_cs_ai",   "https://rss.arxiv.org/rss/cs.AI",                                  "ArXiv CS.AI",        "research"),
    RSSFeed("arxiv_cs_lg",   "https://rss.arxiv.org/rss/cs.LG",                                  "ArXiv ML",           "research"),
    RSSFeed("huggingface",   "https://huggingface.co/blog/feed.xml",                             "HuggingFace Blog",   "tech"),
    RSSFeed("openai_blog",   "https://openai.com/blog/rss/",                                     "OpenAI Blog",        "tech"),
    RSSFeed("mittech",       "https://www.technologyreview.com/feed/",                           "MIT Tech Review",    "tech"),
    RSSFeed("zdnet",         "https://www.zdnet.com/news/rss.xml",                               "ZDNet",              "tech"),
    RSSFeed("darkreading",   "https://www.darkreading.com/rss.xml",                              "Dark Reading",       "tech"),
    RSSFeed("schneier",      "https://www.schneier.com/blog/atom.xml",                           "Schneier on Security","tech"),
    RSSFeed("krebsonsecurity","https://krebsonsecurity.com/feed/",                               "Krebs on Security",  "tech"),
    RSSFeed("venturebeat",   "https://venturebeat.com/feed/",                                    "VentureBeat",        "tech"),
    RSSFeed("infoq",         "https://feed.infoq.com/",                                          "InfoQ",              "tech"),
    RSSFeed("thenewstack",   "https://thenewstack.io/feed/",                                     "The New Stack",      "tech"),
    RSSFeed("axios_tech",    "https://www.axios.com/feeds/feed.rss",                             "Axios",              "tech"),
    RSSFeed("github_blog",   "https://github.blog/feed/",                                        "GitHub Blog",        "tech"),
]

# ─────────────────────────────────────────────────────────────
# 金融 & 经济
# ─────────────────────────────────────────────────────────────
FINANCE_FEEDS: list[RSSFeed] = [
    RSSFeed("marketwatch",   "https://feeds.marketwatch.com/marketwatch/topstories/",             "MarketWatch",        "finance"),
    RSSFeed("cnbc",          "https://www.cnbc.com/id/100003114/device/rss/rss.html",             "CNBC Business",      "finance"),
    RSSFeed("ft",            "https://www.ft.com/?format=rss",                                   "Financial Times",    "finance"),
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
    + REGIONAL_FEEDS
)

# 合法域名白名单（安全过滤）
ALLOWED_DOMAINS: set[str] = {
    f.url.split("/")[2] for f in ALL_RSS_FEEDS
}
