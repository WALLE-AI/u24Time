# -*- coding: utf-8 -*-
"""DataSource Registry — 4-Domain Architecture"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Literal
import httpx
from loguru import logger

SourceStatus = Literal["healthy", "degraded", "down", "unknown"]

@dataclass
class DataSourceConfig:
    source_id: str
    name: str
    source_type: str
    description: str
    crawl_method: str
    domain: str = ""
    sub_domain: str = ""
    health_url: Optional[str] = None
    api_key_required: bool = False
    is_enabled: bool = True
    tags: list[str] = field(default_factory=list)
    status: SourceStatus = "unknown"
    last_checked: Optional[datetime] = None
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None


def _s(sid, name, stype, desc, method, domain, sub, health=None, key=False, tags=None):
    return DataSourceConfig(
        source_id=sid, name=name, source_type=stype, description=desc,
        crawl_method=method, domain=domain, sub_domain=sub,
        health_url=health, api_key_required=key, tags=tags or [],
    )


ALL_SOURCES: list[DataSourceConfig] = [

    # ══════════════════════════════════════════════════════════════
    # 💹 DOMAIN: ECONOMY
    # ══════════════════════════════════════════════════════════════

    # ── stock ─────────────────────────────────────────────────────
    _s("economy.stock.akshare_a", "AKShare A股实时", "market", "AKShare stock_zh_a_spot (新浪/东方财富)", "lib", "economy", "stock", tags=["china","a-share","akshare"]),
    _s("economy.stock.tushare_daily", "Tushare A股日行情", "market", "Tushare daily() + stk_factor()", "lib", "economy", "stock", tags=["china","a-share","tushare"], key=True),
    _s("economy.stock.baostock_daily", "BaoStock A股", "market", "BaoStock query_history_k_data_plus()", "lib", "economy", "stock", tags=["china","a-share","baostock"]),
    _s("economy.stock.yfinance_us", "yfinance 美股", "market", "Yahoo Finance US stocks via yfinance", "lib", "economy", "stock", health="https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d", tags=["us","stock","yfinance"]),
    _s("economy.stock.alpha_vantage", "Alpha Vantage", "market", "Alpha Vantage 美股基本面+新闻", "api", "economy", "stock", health="https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol=IBM&interval=5min&apikey=demo", key=True, tags=["us","stock","fundamental"]),
    _s("economy.stock.finnhub", "Finnhub", "market", "Finnhub 美股备用数据源", "api", "economy", "stock", health="https://finnhub.io/api/v1/quote?symbol=AAPL&token=demo", key=True, tags=["us","stock"]),
    _s("economy.stock.hk_akshare", "AKShare 港股", "market", "AKShare stock_hk_spot()", "lib", "economy", "stock", tags=["hk","stock","akshare"]),
    _s("economy.stock.country_index", "全球股票指数 (Yahoo)", "market", "Yahoo Finance 40+国家主要指数 (S&P500/CSI300/Nikkei...)", "api", "economy", "stock", health="https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=1mo&interval=1d", tags=["global","index","yahoo"]),
    _s("economy.stock.sector_summary", "行业板块 (Yahoo ETF)", "market", "Yahoo Finance Sector ETF行情", "api", "economy", "stock", health="https://query1.finance.yahoo.com/v8/finance/chart/XLK?range=1mo&interval=1d", tags=["sector","etf","yahoo"]),
    _s("economy.stock.eastmoney_news", "东方财富股票新闻", "market", "EastMoney search-api-web 个股新闻", "api", "economy", "stock", health="https://www.eastmoney.com", tags=["china","news","eastmoney"]),
    _s("economy.stock.wallstreetcn", "华尔街见闻 (NewsNow)", "hotsearch", "华尔街见闻中文财经快讯", "api", "economy", "stock", health="https://newsnow.busiyi.world/api/s?id=wallstreetcn&latest", tags=["china","finance","news"]),
    _s("economy.stock.cls_hot", "财联社热榜 (NewsNow)", "hotsearch", "财联社国内财经资讯热榜", "api", "economy", "stock", health="https://newsnow.busiyi.world/api/s?id=cls-hot&latest", tags=["china","finance","market"]),
    _s("economy.stock.xueqiu", "雪球热帖 (NewsNow)", "hotsearch", "雪球股票投资社区热帖", "api", "economy", "stock", health="https://newsnow.busiyi.world/api/s?id=xueqiu&latest", tags=["china","finance","stock"]),

    # ── futures ───────────────────────────────────────────────────
    _s("economy.futures.akshare_shfe", "AKShare 上期所期货", "market", "AKShare futures_main_sina() 上海期货交易所", "lib", "economy", "futures", tags=["china","futures","shfe"]),
    _s("economy.futures.akshare_dce", "AKShare 大商所期货", "market", "AKShare 大连商品交易所行情", "lib", "economy", "futures", tags=["china","futures","dce"]),
    _s("economy.futures.akshare_czce", "AKShare 郑商所期货", "market", "AKShare 郑州商品交易所期货", "lib", "economy", "futures", tags=["china","futures","czce"]),
    _s("economy.futures.commodity_quotes", "大宗商品行情 (Yahoo)", "market", "Yahoo Finance GC/CL/SI/NG/HG/ZW=F...", "api", "economy", "futures", health="https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?range=1mo&interval=1d", tags=["commodity","gold","oil"]),
    _s("economy.futures.etf_flows", "ETF 资金流 (Yahoo)", "market", "Yahoo Finance SPY/QQQ/GLD/TLT ETF行情", "api", "economy", "futures", health="https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1mo&interval=1d", tags=["etf","flows","yahoo"]),

    # ── quant ─────────────────────────────────────────────────────
    _s("economy.quant.macro_signals", "宏观信号面板", "market", "worldmonitor 7信号宏观仪表盘 (JPY/BTC/QQQ/XLP/FGI/HashRate)", "api", "economy", "quant", health="https://query1.finance.yahoo.com/v8/finance/chart/QQQ?range=1y&interval=1d", tags=["macro","quant","signal"]),
    _s("economy.quant.fred_series", "FRED 宏观指标", "market", "FRED API api.stlouisfed.org 经济指标时间序列", "api", "economy", "quant", health="https://fred.stlouisfed.org", key=True, tags=["fred","macro","us"]),
    _s("economy.quant.bis_policy_rates", "BIS 央行利率", "market", "BIS stats.bis.org 各国央行政策利率", "api", "economy", "quant", health="https://stats.bis.org", tags=["bis","rate","central-bank"]),
    _s("economy.quant.bis_exchange_rates", "BIS 汇率数据", "market", "BIS FX 汇率历史", "api", "economy", "quant", health="https://stats.bis.org", tags=["bis","fx","exchange-rate"]),
    _s("economy.quant.bis_credit", "BIS 信贷数据", "market", "BIS 私人部门信贷占 GDP 比", "api", "economy", "quant", health="https://stats.bis.org", tags=["bis","credit","gdp"]),
    _s("economy.quant.worldbank_indicators", "World Bank 指标", "market", "World Bank API GDP/CPI/失业率等宏观指标", "api", "economy", "quant", health="https://api.worldbank.org/v2/country/CN/indicator/NY.GDP.MKTP.CD?format=json&mrv=5", tags=["worldbank","macro","gdp"]),
    _s("economy.quant.energy_prices", "EIA 能源价格", "market", "EIA/Yahoo Finance 原油/天然气/电力价格", "api", "economy", "quant", health="https://query1.finance.yahoo.com/v8/finance/chart/CL%3DF?range=1mo&interval=1d", tags=["energy","oil","eia"]),
    _s("economy.quant.mempool_hashrate", "Bitcoin 算力", "market", "mempool.space/api/v1/mining/hashrate/1m", "api", "economy", "quant", health="https://mempool.space/api/v1/mining/hashrate/1m", tags=["bitcoin","hashrate","mining"]),
    _s("economy.quant.fear_greed_index", "恐惧贪婪指数", "market", "alternative.me/fng/ 市场情绪指数", "api", "economy", "quant", health="https://api.alternative.me/fng/?limit=1&format=json", tags=["sentiment","fear","greed"]),

    # ── crypto ────────────────────────────────────────────────────
    _s("economy.crypto.coingecko", "CoinGecko 加密货币", "market", "CoinGecko BTC/ETH/SOL 等主流加密货币价格", "api", "economy", "crypto", health="https://api.coingecko.com/api/v3/ping", tags=["crypto","coingecko"]),
    _s("economy.crypto.stablecoin_markets", "稳定币市场 (CoinGecko)", "market", "CoinGecko USDT/USDC 稳定币市值", "api", "economy", "crypto", health="https://api.coingecko.com/api/v3/ping", tags=["crypto","stablecoin"]),

    # ── trade ─────────────────────────────────────────────────────
    _s("economy.trade.wto_flows", "WTO 贸易流数据", "market", "WTO API api.wto.org 进出口额双边贸易", "api", "economy", "trade", health="https://api.wto.org", tags=["wto","trade","export"]),
    _s("economy.trade.wto_barriers", "WTO 贸易壁垒", "market", "WTO 贸易壁垒数据库", "api", "economy", "trade", health="https://api.wto.org", tags=["wto","trade","barrier"]),
    _s("economy.trade.wto_tariffs", "WTO 关税趋势", "market", "WTO 关税水平历史趋势", "api", "economy", "trade", health="https://api.wto.org", tags=["wto","tariff"]),
    _s("economy.trade.wto_restrictions", "WTO 贸易限制", "market", "WTO 贸易措施数据库", "api", "economy", "trade", health="https://api.wto.org", tags=["wto","restriction"]),

    # ══════════════════════════════════════════════════════════════
    # 💻 DOMAIN: TECHNOLOGY
    # ══════════════════════════════════════════════════════════════

    # ── oss ───────────────────────────────────────────────────────
    _s("tech.oss.github_trending", "GitHub 每日趋势 (NewsNow)", "hotsearch", "GitHub每日 trending 项目聚合", "api", "technology", "oss", health="https://newsnow.busiyi.world/api/s?id=github-trending-today&latest", tags=["github","oss","tech"]),
    _s("tech.oss.hackernews", "Hacker News", "news", "HN Firebase API hacker-news.firebaseio.com", "api", "technology", "oss", health="https://hacker-news.firebaseio.com/v0/topstories.json", tags=["hackernews","tech","dev"]),
    _s("tech.oss.tech_events", "Tech 会议活动", "news", "worldmonitor list-tech-events 多来源技术会议聚合", "api", "technology", "oss", tags=["conference","tech","events"]),
    _s("tech.oss.trending_repos", "GitHub Trending (scraper)", "news", "GitHub trending页面爬虫", "playwright", "technology", "oss", health="https://github.com/trending", tags=["github","trending","oss"]),
    _s("tech.oss.techcrunch", "TechCrunch", "news", "TechCrunch Tech News RSS", "rss", "technology", "oss", health="https://techcrunch.com/feed/", tags=["english","tech","news"]),
    _s("tech.oss.coolapk", "酷安热榜 (NewsNow)", "hotsearch", "酷安 Android 应用社区热榜", "api", "technology", "oss", health="https://newsnow.busiyi.world/api/s?id=coolapk&latest", tags=["china","android","coolapk"]),
    _s("tech.oss.toutiao_tech", "今日头条科技 (NewsNow)", "hotsearch", "今日头条科技频道热榜", "api", "technology", "oss", health="https://newsnow.busiyi.world/api/s?id=toutiao&latest", tags=["china","toutiao","tech"]),

    # ── ai_service ────────────────────────────────────────────────
    _s("tech.ai.openai_status", "OpenAI 服务状态", "geo", "status.openai.com API服务健康", "api", "technology", "ai_service", health="https://status.openai.com/api/v2/status.json", tags=["openai","ai","status"]),
    _s("tech.ai.anthropic_status", "Anthropic 服务状态", "geo", "status.claude.com Claude服务健康", "api", "technology", "ai_service", health="https://status.claude.com/api/v2/status.json", tags=["anthropic","claude","ai","status"]),
    _s("tech.ai.replicate_status", "Replicate 服务状态", "geo", "replicatestatus.com API健康", "api", "technology", "ai_service", health="https://www.replicatestatus.com/api/v2/status.json", tags=["replicate","ai","status"]),
    _s("tech.ai.huggingface_papers", "HuggingFace Daily Papers", "news", "HuggingFace 每日AI论文推荐 (归属Academic)", "api", "academic", "paper", health="https://huggingface.co/api/daily_papers", tags=["huggingface","ai","paper"]),

    # ── cyber ─────────────────────────────────────────────────────
    _s("tech.cyber.feodo", "Feodo Tracker C2", "cyber", "Feodo Tracker C2服务器黑名单", "api", "technology", "cyber", health="https://feodotracker.abuse.ch/downloads/ipblocklist.csv", tags=["c2","botnet","threat"]),
    _s("tech.cyber.urlhaus", "URLhaus 恶意URL", "cyber", "URLhaus 恶意软件分发URL数据库", "api", "technology", "cyber", health="https://urlhaus-api.abuse.ch/v1/urls/recent/limit/1/", tags=["malware","phishing","threat"]),
    _s("tech.cyber.worldmonitor_threats", "威胁情报聚合 (WM)", "cyber", "worldmonitor cyber 多来源威胁情报", "api", "technology", "cyber", tags=["threat","intel","abuse"]),
    _s("tech.cyber.nvd_cve", "NVD CVE 漏洞库", "cyber", "NIST NVD CVSS漏洞数据库", "api", "technology", "cyber", health="https://services.nvd.nist.gov/rest/json/cves/2.0?resultsPerPage=1", tags=["cve","nvd","vuln"]),

    # ── infra ─────────────────────────────────────────────────────
    _s("tech.infra.internet_outages", "互联网断网事件", "geo", "NetBlocks/IODA ioda.caida.org 互联网中断", "api", "technology", "infra", tags=["internet","outage","netblocks"]),
    _s("tech.infra.cable_health", "海底光缆健康", "geo", "TeleGeography 海底电缆中断事件", "api", "technology", "infra", tags=["cable","submarine","infra"]),
    _s("tech.infra.cloud_aws", "AWS 服务状态", "geo", "health.aws.amazon.com", "api", "technology", "infra", health="https://health.aws.amazon.com/health/status", tags=["aws","cloud","status"]),
    _s("tech.infra.cloud_azure", "Azure 服务状态", "geo", "azure.status.microsoft RSS", "rss", "technology", "infra", health="https://azure.status.microsoft/en-us/status/feed/", tags=["azure","cloud","status"]),
    _s("tech.infra.cloud_gcp", "GCP 服务状态", "geo", "status.cloud.google.com/incidents.json", "api", "technology", "infra", health="https://status.cloud.google.com/incidents.json", tags=["gcp","cloud","status"]),
    _s("tech.infra.cloud_cloudflare", "Cloudflare 状态", "geo", "cloudflarestatus.com JSON", "api", "technology", "infra", health="https://www.cloudflarestatus.com/api/v2/status.json", tags=["cloudflare","cdn","status"]),
    _s("tech.infra.cloud_vercel", "Vercel 状态", "geo", "vercel-status.com JSON", "api", "technology", "infra", health="https://www.vercel-status.com/api/v2/status.json", tags=["vercel","cloud","status"]),
    _s("tech.infra.dev_github", "GitHub 服务状态", "geo", "githubstatus.com JSON", "api", "technology", "infra", health="https://www.githubstatus.com/api/v2/status.json", tags=["github","dev","status"]),
    _s("tech.infra.dev_npm", "npm 服务状态", "geo", "status.npmjs.org JSON", "api", "technology", "infra", health="https://status.npmjs.org/api/v2/status.json", tags=["npm","dev","status"]),
    _s("tech.infra.comm_slack", "Slack 服务状态", "geo", "slack-status.com API", "api", "technology", "infra", health="https://slack-status.com/api/v2.0.0/current", tags=["slack","comm","status"]),
    _s("tech.infra.comm_discord", "Discord 服务状态", "geo", "discordstatus.com JSON", "api", "technology", "infra", health="https://discordstatus.com/api/v2/status.json", tags=["discord","comm","status"]),
    _s("tech.infra.saas_stripe", "Stripe 服务状态", "geo", "status.stripe.com", "api", "technology", "infra", health="https://status.stripe.com/current", tags=["stripe","saas","status"]),
    _s("tech.infra.aviation_delays", "机场延误 (FlightAware)", "geo", "FAA/FlightAware机场延误数据", "api", "technology", "infra", tags=["aviation","airport","delay"]),

    # ══════════════════════════════════════════════════════════════
    # 🎓 DOMAIN: ACADEMIC
    # ══════════════════════════════════════════════════════════════

    # ── paper ─────────────────────────────────────────────────────
    _s("academic.arxiv.cs_ai", "arXiv cs.AI", "news", "arXiv Computer Science AI 论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/cs.AI", tags=["arxiv","ai","paper"]),
    _s("academic.arxiv.cs_lg", "arXiv cs.LG (机器学习)", "news", "arXiv 机器学习论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/cs.LG", tags=["arxiv","ml","paper"]),
    _s("academic.arxiv.cs_cv", "arXiv cs.CV (计算机视觉)", "news", "arXiv 计算机视觉论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/cs.CV", tags=["arxiv","cv","paper"]),
    _s("academic.arxiv.cs_cl", "arXiv cs.CL (NLP)", "news", "arXiv 自然语言处理论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/cs.CL", tags=["arxiv","nlp","paper"]),
    _s("academic.arxiv.econ", "arXiv econ", "news", "arXiv 经济学论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/econ.GN", tags=["arxiv","economics","paper"]),
    _s("academic.arxiv.physics", "arXiv Physics", "news", "arXiv 物理学论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/physics", tags=["arxiv","physics","paper"]),
    _s("academic.arxiv.q_bio", "arXiv q-bio", "news", "arXiv 量化生物论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/q-bio", tags=["arxiv","biology","paper"]),
    _s("academic.arxiv.math_st", "arXiv math.ST (统计)", "news", "arXiv 数理统计论文", "rss", "academic", "paper", health="https://rss.arxiv.org/rss/math.ST", tags=["arxiv","math","statistics"]),
    _s("academic.huggingface.papers", "HuggingFace Daily Papers", "news", "HuggingFace 每日AI论文精选", "api", "academic", "paper", health="https://huggingface.co/api/daily_papers", tags=["huggingface","ai","paper"]),
    _s("academic.semantic_scholar.trending", "Semantic Scholar 趋势论文", "news", "S2 API 高引用/趋势论文", "api", "academic", "paper", health="https://api.semanticscholar.org/graph/v1/paper/search?query=AI&limit=1", tags=["semantic-scholar","citation","paper"]),

    # ── conference ────────────────────────────────────────────────
    _s("academic.conf.tech_events", "Tech 学术会议 (WM)", "news", "worldmonitor list-tech-events NeurIPS/ICML/ICLR...", "api", "academic", "conference", tags=["neurips","icml","iclr","conference"]),

    # ── prediction ────────────────────────────────────────────────
    _s("academic.prediction.polymarket", "Polymarket 预测市场", "market", "Polymarket Gamma API gamma-api.polymarket.com", "api", "academic", "prediction", health="https://gamma-api.polymarket.com/markets?closed=false&limit=1", tags=["polymarket","prediction","market"]),

    # ══════════════════════════════════════════════════════════════
    # 🌍 DOMAIN: GLOBAL MONITORING
    # ══════════════════════════════════════════════════════════════

    # ── conflict ──────────────────────────────────────────────────
    _s("global.conflict.acled", "ACLED 冲突数据", "geo", "ACLED 武装冲突/抗议/暴力事件", "api", "global", "conflict", health="https://api.acleddata.com/acled/read/?limit=1", key=True, tags=["acled","conflict","protest"]),
    _s("global.conflict.ucdp", "UCDP 冲突数据库", "geo", "UCDP API ucdpapi.pcr.uu.se 武装冲突数据", "api", "global", "conflict", health="https://ucdpapi.pcr.uu.se/api/gedevents/22.1?pagesize=1", tags=["ucdp","conflict","war"]),
    _s("global.conflict.gdelt", "GDELT 全球事件", "geo", "GDELT v2 全球大事件数据库", "api", "global", "conflict", health="https://api.gdeltproject.org/api/v2/doc/doc?query=test&mode=artlist&maxrecords=1&format=json", tags=["gdelt","geopolitical","media"]),
    _s("global.conflict.gdelt_docs", "GDELT 文档搜索", "geo", "GDELT DOC API 新闻文档搜索与分析", "api", "global", "conflict", tags=["gdelt","news","search"]),
    _s("global.conflict.humanitarian", "ReliefWeb 人道救援", "geo", "ReliefWeb API api.reliefweb.int 人道主义危机", "api", "global", "conflict", health="https://api.reliefweb.int/v1/disasters?appname=u24time&limit=1", tags=["reliefweb","humanitarian","crisis"]),

    # ── unrest ────────────────────────────────────────────────────
    _s("global.unrest.acled_protests", "ACLED 抗议/社会动荡", "geo", "ACLED 抗议/暴乱过滤", "api", "global", "unrest", key=True, tags=["acled","protest","riot","unrest"]),

    # ── military ──────────────────────────────────────────────────
    _s("global.military.opensky", "OpenSky ADS-B", "military", "OpenSky Network 实时飞行ADS-B数据", "api", "global", "military", health="https://opensky-network.org/api/states/all?lamin=0&lomin=0&lamax=1&lomax=1", tags=["aviation","adsb","military"]),
    _s("global.military.military_flights", "军机飞行追踪 (WM)", "military", "worldmonitor 军机callsign过滤+识别", "api", "global", "military", tags=["military","aviation","flight"]),
    _s("global.military.theater_posture", "战区态势 (WM)", "military", "worldmonitor get-theater-posture OSINT战区分析", "api", "global", "military", tags=["military","theater","osint"]),
    _s("global.military.ais", "AIS 船舶追踪", "military", "AIS全球船舶位置数据", "api", "global", "military", tags=["maritime","ais","vessel"]),
    _s("global.military.vessel_snapshot", "AIS 船舶快照 (WM)", "military", "worldmonitor vessel snapshot 船舶快照", "api", "global", "military", tags=["maritime","vessel","snapshot"]),
    _s("global.military.nav_warnings", "航行警告 (NAVAREA)", "military", "NAVAREA 航行警告 RSS", "rss", "global", "military", tags=["maritime","navarea","warning"]),
    _s("global.military.usni_fleet", "USNI 舰队报告 (WM)", "news", "worldmonitor get-usni-fleet-report 美国海军舰队动态", "api", "global", "military", health="https://news.usni.org/feed", tags=["usni","navy","fleet"]),
    _s("global.military.usni_news", "USNI News RSS", "news", "US Naval Institute News RSS", "rss", "global", "military", health="https://news.usni.org/feed", tags=["usni","military","news"]),
    _s("global.military.defenseone", "Defense One", "news", "Defense One Military RSS", "rss", "global", "military", health="https://www.defenseone.com/rss/all/", tags=["military","defense","news"]),

    # ── diplomacy ─────────────────────────────────────────────────
    _s("global.diplomacy.bbc_world", "BBC World News", "news", "BBC World Service RSS", "rss", "global", "diplomacy", health="https://feeds.bbci.co.uk/news/world/rss.xml", tags=["bbc","english","geopolitical"]),
    _s("global.diplomacy.reuters", "Reuters 世界新闻", "news", "Reuters World News RSS", "rss", "global", "diplomacy", health="https://feeds.reuters.com/reuters/worldNews", tags=["reuters","english","news"]),
    _s("global.diplomacy.aljazeera", "Al Jazeera", "news", "Al Jazeera English RSS", "rss", "global", "diplomacy", health="https://www.aljazeera.com/xml/rss/all.xml", tags=["aljazeera","english","middle-east"]),
    _s("global.diplomacy.guardian", "The Guardian 世界", "news", "Guardian World News RSS", "rss", "global", "diplomacy", health="https://www.theguardian.com/world/rss", tags=["guardian","english","geopolitical"]),
    _s("global.diplomacy.scmp", "SCMP 南华早报", "news", "South China Morning Post Asia RSS", "rss", "global", "diplomacy", health="https://www.scmp.com/rss/91/feed", tags=["scmp","asia","china"]),
    _s("global.diplomacy.bellingcat", "Bellingcat OSINT", "news", "Bellingcat 开源情报调查", "rss", "global", "diplomacy", health="https://www.bellingcat.com/feed/", tags=["bellingcat","osint","investigation"]),
    _s("global.diplomacy.kyiv_independent", "基辅独立报", "news", "Kyiv Independent 乌克兰冲突报道", "rss", "global", "diplomacy", health="https://kyivindependent.com/feed/", tags=["ukraine","conflict","russia"]),
    _s("global.diplomacy.thepaper", "澎湃新闻 (NewsNow)", "hotsearch", "澎湃新闻国内事件热榜", "api", "global", "diplomacy", health="https://newsnow.busiyi.world/api/s?id=thepaper&latest", tags=["china","news","thepaper"]),
    _s("global.diplomacy.risk_scores", "国家风险评分 (WM)", "geo", "worldmonitor get-risk-scores OSINT国家风险模型", "api", "global", "diplomacy", tags=["risk","country","intelligence"]),
    _s("global.diplomacy.country_intel", "国家情报简报 (WM)", "geo", "worldmonitor get-country-intel-brief (GDELT+ACLED综合)", "api", "global", "diplomacy", tags=["intel","country","gdelt"]),
    _s("global.diplomacy.pizzint", "PizzInt 政治指数 (WM)", "geo", "worldmonitor get-pizzint-status 政治稳定性指数", "api", "global", "diplomacy", tags=["politics","stability","index"]),

    # ── disaster ──────────────────────────────────────────────────
    _s("global.disaster.usgs", "USGS 地震数据", "geo", "USGS 地震 M4.5+ 实时数据", "api", "global", "disaster", health="https://earthquake.usgs.gov/fdsnws/event/1/count?format=geojson", tags=["earthquake","usgs","disaster"]),
    _s("global.disaster.earthquakes_wm", "USGS 地震 (WM)", "geo", "worldmonitor USGS geojson实时地震列表", "api", "global", "disaster", health="https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson", tags=["earthquake","seismology","realtime"]),
    _s("global.disaster.nasa_firms", "NASA FIRMS 野火", "geo", "NASA卫星VIIRS/MODIS火点探测", "api", "global", "disaster", health="https://firms.modaps.eosdis.nasa.gov/", key=True, tags=["wildfire","nasa","fire"]),
    _s("global.disaster.climate_anomalies", "气候异常 (NOAA)", "climate", "NOAA CDO/Berkeley Earth 气温异常", "api", "global", "disaster", tags=["climate","noaa","temperature"]),
    _s("global.disaster.positive_events", "正面地缘事件 (WM)", "geo", "worldmonitor list-positive-geo-events GDELT积极行动", "api", "global", "disaster", tags=["positive","gdelt","peace"]),

    # ── displacement ──────────────────────────────────────────────
    _s("global.displacement.unhcr", "UNHCR 难民数据", "geo", "UNHCR API data.unhcr.org 全球难民统计", "api", "global", "displacement", health="https://data.unhcr.org/population/get/timeseries?widget_id=284580&lang=en&limit=1", tags=["unhcr","refugee","displacement"]),
    _s("global.displacement.idmc", "IDMC 内部流离失所", "geo", "IDMC API api.internal-displacement.org", "api", "global", "displacement", health="https://api.internal-displacement.org/countries", tags=["idmc","idp","displacement"]),

    # ── social (BettaFish全部) ────────────────────────────────────
    _s("global.social.weibo_newsnow", "微博热搜 (NewsNow)", "hotsearch", "微博实时热搜榜", "api", "global", "social", health="https://newsnow.busiyi.world/api/s?id=weibo&latest", tags=["china","weibo","hotsearch"]),
    _s("global.social.zhihu_newsnow", "知乎热榜 (NewsNow)", "hotsearch", "知乎每日热榜", "api", "global", "social", health="https://newsnow.busiyi.world/api/s?id=zhihu&latest", tags=["china","zhihu","hotsearch"]),
    _s("global.social.bilibili_newsnow", "B站热搜 (NewsNow)", "hotsearch", "B站实时热搜榜", "api", "global", "social", health="https://newsnow.busiyi.world/api/s?id=bilibili-hot-search&latest", tags=["china","bilibili","hotsearch"]),
    _s("global.social.douyin_newsnow", "抖音热榜 (NewsNow)", "hotsearch", "抖音实时热搜视频榜", "api", "global", "social", health="https://newsnow.busiyi.world/api/s?id=douyin&latest", tags=["china","douyin","hotsearch"]),
    _s("global.social.tieba_newsnow", "百度贴吧 (NewsNow)", "hotsearch", "百度贴吧热门话题聚合", "api", "global", "social", health="https://newsnow.busiyi.world/api/s?id=tieba&latest", tags=["china","tieba","hotsearch"]),
    _s("global.social.bilibili_playwright", "B站 (Playwright)", "social", "BettaFish MediaEngine B站视频+评论爬虫", "playwright", "global", "social", health="https://www.bilibili.com", tags=["china","bilibili","video"]),
    _s("global.social.weibo_playwright", "微博 (Playwright)", "social", "BettaFish MediaEngine 微博帖文+评论", "playwright", "global", "social", health="https://weibo.com", tags=["china","weibo","microblog"]),
    _s("global.social.douyin_playwright", "抖音 (Playwright)", "social", "BettaFish MediaEngine 抖音视频+评论", "playwright", "global", "social", health="https://www.douyin.com", tags=["china","douyin","video"]),
    _s("global.social.xhs_playwright", "小红书 (Playwright)", "social", "BettaFish MediaEngine 小红书图文笔记", "playwright", "global", "social", health="https://www.xiaohongshu.com", tags=["china","xhs","lifestyle"]),
    _s("global.social.kuaishou_playwright", "快手 (Playwright)", "social", "BettaFish MediaEngine 快手短视频+评论", "playwright", "global", "social", health="https://www.kuaishou.com", tags=["china","kuaishou","video"]),
    _s("global.social.zhihu_playwright", "知乎 (Playwright)", "social", "BettaFish MediaEngine 知乎问答+文章", "playwright", "global", "social", health="https://www.zhihu.com", tags=["china","zhihu","qa"]),
    _s("global.social.tieba_playwright", "百度贴吧 (Playwright)", "social", "BettaFish MediaEngine 贴吧帖子+评论", "playwright", "global", "social", health="https://tieba.baidu.com", tags=["china","tieba","forum"]),
]


class DataSourceRegistry:
    """数据源注册表 — 支持按 domain/sub_domain/source_type 查询"""

    def __init__(self, sources: list[DataSourceConfig] = ALL_SOURCES):
        self._sources: dict[str, DataSourceConfig] = {s.source_id: s for s in sources}

    def get(self, source_id: str) -> Optional[DataSourceConfig]:
        return self._sources.get(source_id)

    def all(self) -> list[DataSourceConfig]:
        return list(self._sources.values())

    def by_type(self, source_type: str) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.source_type == source_type]

    def by_domain(self, domain: str) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.domain == domain]

    def by_sub_domain(self, sub_domain: str) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.sub_domain == sub_domain]

    def enabled(self) -> list[DataSourceConfig]:
        return [s for s in self._sources.values() if s.is_enabled]

    def domain_summary(self) -> dict:
        """返回各域的源统计"""
        from collections import defaultdict
        result = defaultdict(lambda: {"count": 0, "sub_domains": defaultdict(int)})
        for s in self._sources.values():
            d = s.domain or "unclassified"
            result[d]["count"] += 1
            result[d]["sub_domains"][s.sub_domain or "none"] += 1
        return {k: {"count": v["count"], "sub_domains": dict(v["sub_domains"])} for k, v in result.items()}

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
                    "domain": s.domain,
                    "sub_domain": s.sub_domain,
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
