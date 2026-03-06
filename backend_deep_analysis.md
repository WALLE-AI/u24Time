# U24Time Backend 全链路深度分析报告

> 生成时间: 2026-03-06  
> 分析范围: `data_source/` → `crawler_engine/` → `data_alignment/` → `db/` → `main.py` → Frontend SSE  
> 源文件总量: 30+ 文件, ~155K bytes 核心代码

---

## 目录

1. [系统全景架构](#1-系统全景架构)
2. [数据源层 — DataSource Registry](#2-数据源层--datasource-registry)
3. [调度层 — DataScheduler](#3-调度层--datascheduler)
4. [爬虫引擎层 — CrawlerEngine](#4-爬虫引擎层--crawlerengine)
5. [数据对齐层 — AlignmentPipeline](#5-数据对齐层--alignmentpipeline)
6. [去重层 — Deduplicator](#6-去重层--deduplicator)
7. [AI 增强层 — LLMClient](#7-ai-增强层--llmclient)
8. [数据库 & 持久层 — DB Models](#8-数据库--持久层--db-models)
9. [内存缓存层 — NewsFlash Cache](#9-内存缓存层--newsflash-cache)
10. [接口层 — Flask API & SSE](#10-接口层--flask-api--sse)
11. [前端消费模式](#11-前端消费模式)
12. [数据流全链路追踪](#12-数据流全链路追踪)
13. [架构强项与潜在风险](#13-架构强项与潜在风险)

---

## 1. 系统全景架构

```mermaid
flowchart TD
    subgraph 数据源层
        RSS[📡 RSS 订阅源<br/>40+ arXiv/BBC/Reuters...]
        API[🔌 REST API<br/>USGS/GDELT/CoinGecko/NASA...]
        NN[🔥 NewsNow 聚合热搜<br/>微博/知乎/B站/GitHub...]
        PW[🎭 Playwright<br/>B站/微博/抖音/知乎...]
    end

    subgraph 调度层 scheduler.py
        SCH[⏰ DataScheduler<br/>APScheduler 5层TTL]
    end

    subgraph 爬虫引擎层 crawler_engine/
        ENG[⚙️ CrawlerEngine<br/>run_rss / run_api / run_hotsearch]
        ADA[🔧 API Adapters<br/>adapters.py / extended_adapters.py]
        RSS_F[📰 RSSFetcher<br/>aiohttp + feedparser]
        GITH[🐙 GithubAdapter<br/>双阶段 Enrichment]
    end

    subgraph 对齐层 data_alignment/
        PIPE[🔄 AlignmentPipeline<br/>align_and_save]
        NORM[🏭 10种 Normalizer<br/>News/Social/Geo/Economy/Tech/Academic...]
        DEDUP[🔍 Deduplicator<br/>ID + Jaccard + 地理格点]
    end

    subgraph AI增强层
        LLM[🤖 LLMClient<br/>批量分类 + 摘要生成]
    end

    subgraph 持久层 db/
        ORM[SQLAlchemy ORM]
        SQLI[(SQLite WAL<br/>canonical_items<br/>raw_items<br/>crawl_tasks...)]
    end

    subgraph 内存层
        DEQUE[⚡ news_flash_cache<br/>deque maxlen=200]
    end

    subgraph API层 main.py
        FLASK[Flask + Flask-CORS]
        SSE[/stream SSE]
    end

    Frontend[🖥️ Vue/React 前端]

    SCH -->|时间触发| ENG
    ENG --> RSS_F
    ENG --> ADA
    ENG --> GITH
    RSS --> RSS_F
    API --> ADA
    NN --> ADA
    ADA -->|raw_data| PIPE
    RSS_F -->|feedparser entries| PIPE
    PIPE --> NORM
    NORM --> DEDUP
    DEDUP -->|CanonicalItem| LLM
    LLM -->|domain/sub_domain| ORM
    ORM --> SQLI
    PIPE -->|appendleft| DEQUE
    ENG -->|progress_cb| SSE
    SCH -->|broadcast| SSE
    FLASK -->|SQLAlchemy sync query| SQLI
    FLASK -->|list()| DEQUE
    SSE -.->|text/event-stream| Frontend
    FLASK -->|JSON| Frontend
```

---

## 2. 数据源层 — DataSource Registry

### 文件: `data_source/registry.py`

### 2.1 数据源规模

| 域 (Domain) | 子域数 | 数据源数 | 典型来源 |
|------------|--------|--------|---------|
| 💹 economy | stock / futures / quant / crypto / trade / finance | ~30 | AKShare, Yahoo Finance, CoinGecko, FRED, BIS, WTO |
| 💻 technology | oss / tech_news / cyber / infra / ai_service / ai_model | ~30 | GitHub, HackerNews, NVD, URLhaus, AWS/GCP/Azure Status, HuggingFace |
| 🎓 academic | paper / conference / prediction | ~12 | arXiv (8个RSS), HuggingFace Papers, Semantic Scholar, Polymarket |
| 🌍 global | conflict / military / diplomacy / disaster / displacement / social | ~30 | ACLED, GDELT, USGS, NASA FIRMS, BBC, Reuters, 微博/知乎/B站 |
| **合计** | | **~81** | |

### 2.2 数据源配置结构

```python
@dataclass
class DataSourceConfig:
    source_id: str        # 分层 ID: "economy.crypto.coingecko"
    source_type: str      # social/news/geo/military/market/cyber/climate/hotsearch
    crawl_method: str     # rss/api/lib/playwright/hotsearch
    domain: str           # economy/technology/academic/global
    sub_domain: str       # stock/cyber/paper/conflict...
    health_url: str       # 存活性探针 URL
    api_key_required: bool
```

**设计亮点**: `source_id` 采用三级命名 `{domain}.{sub_domain}.{platform}`，贯穿调度、爬虫、规范化、数据库全链路，实现零配置路由。

### 2.3 健康检查机制

`DataSourceRegistry.check_all_health()` 通过 `httpx.AsyncClient` 并发探测所有配置了 `health_url` 的数据源，测量延迟并记录 `healthy/degraded/down/unknown` 四态。

---

## 3. 调度层 — DataScheduler

### 文件: `scheduler.py`

### 3.1 五层 TTL 分层策略

```
REALTIME  1  min  → 价格/飞行/AI服务状态 (CoinGecko/OpenSky/AWS/GCP...)
NEWS      5  min  → 热搜/头条/HN/TechCrunch (15个源)
EVENT     30 min  → 冲突/CVE/火点/ReliefWeb (5个源)
MACRO     60 min  → 宏观指标/arXiv论文/ACLED (13个源)
SLOW      360 min → WTO贸易数据/WorldBank/IDMC (4个源)
```

**注**: 文档说15分钟新闻层，实际代码 `NEWS_INTERVAL_MIN = 5` 已优化至5分钟。

### 3.2 并发模型

```
Flask主线程
    │
    ├── @before_request → _ensure_scheduler()
    │       └── DataScheduler.start()
    │               ├── threading.Thread(scheduler-loop) - 独立事件循环
    │               └── APScheduler BackgroundScheduler - 定时任务触发
    │
    └── APScheduler ThreadPoolExecutor(4)
            └── _run_sync_wrapper(source_id)
                    └── asyncio.run_coroutine_threadsafe(_crawl(), loop)
                            └── 120s 超时
```

**关键设计**: Scheduler 运行在独立线程的 asyncio 事件循环中，与 Flask 主线程互不阻塞。失败时执行 **stale-while-revalidate** 模式：不清空 `_last_success` 缓存，前端 API 始终有数据兜底。

### 3.3 手动触发 API

```
POST /api/v1/scheduler/trigger/{source_id}  → 越过 TTL 立即抓取
POST /api/v1/scheduler/trigger-all          → 全量刷新 (81个源)
GET  /api/v1/scheduler/status               → 查看队列状态 + stale_cache
```

---

## 4. 爬虫引擎层 — CrawlerEngine

### 文件: `crawler_engine/engine.py`, `api_adapters/`, `news/`

### 4.1 三类采集模式

```
CrawlerEngine
├── run_rss(category?, feed_ids?)
│     └── RSSFetcher.fetch_feeds(feeds) → 并发 aiohttp + feedparser
│           └── AlignmentPipeline.align_and_save()
│
├── run_api(source_id, **kwargs)
│     ├── ACLEDAdapter
│     ├── GDELTAdapter
│     ├── USGSAdapter / NASAFIRMSAdapter
│     ├── OpenSkyAdapter
│     ├── CoinGeckoAdapter
│     ├── FeodoAdapter / URLhausAdapter
│     ├── YahooFinanceAdapter (lazy load)
│     ├── FearGreedAdapter / BtcHashrateAdapter
│     ├── HuggingFaceAdapter / SemanticScholarAdapter
│     └── NewsNowAdapter
│
└── run_hotsearch(source_ids?)
      ├── NewsNowAdapter.fetch_all() → 批量拉取 12个中文热搜
      ├── GitHub Trending 双阶段 Enrichment:
      │     NewsNow 热度 → GithubAdapter.enrichen_trending_repos() → Stars/语言/描述
      └── AlignmentPipeline.align_and_save()
```

### 4.2 任务生命周期追踪

每次采集创建一个 `CrawlerTask`（内存对象）并同时写入 `CrawlTaskModel`（数据库），记录：

| 字段 | 说明 |
|------|------|
| `task_id` | UUID4 唯一标识 |
| `status` | pending → running → done/failed |
| `items_fetched` | 原始数据条数 |
| `items_aligned` | 经 Pipeline 输出条数 |
| `started_at / finished_at` | 精确时间戳 |
| `error_message` | 失败时异常摘要 |

进度事件通过 `_emit()` → `_progress_cb()` → `_broadcast()` → SSE 实时推送至前端。

### 4.3 关键 Adapters

| Adapter | 文件 | 功能 |
|---------|------|------|
| `ACLEDAdapter` | adapters.py | ACLED武装冲突数据，支持国家/事件类型过滤 |
| `GDELTAdapter` | adapters.py | GDELT v2 全球事件，Goldstein量化冲突强度 |
| `USGSAdapter` | adapters.py | USGS M4.5+ 地震GeoJSON |
| `NASAFIRMSAdapter` | adapters.py | 卫星火点CSV解析 |
| `NewsNowAdapter` | adapters.py | BettaFish聚合热搜，支持批量并发拉取 |
| `YahooFinanceAdapter` | extended_adapters.py | 40+国家指数 + 大宗商品，Yahoo Chart API |
| `HuggingFaceAdapter` | extended_adapters.py | Daily Papers + Trending Models/Datasets |
| `SemanticScholarAdapter` | extended_adapters.py | 高引用/趋势论文搜索 |
| `CloudStatusAdapter` | extended_adapters.py | AWS/GCP/Azure/Cloudflare 等状态轮询 |
| `GithubAdapter` | github_adapter.py | Trending Repos 二阶段Enrichment (Stars/Fork/语言) |

---

## 5. 数据对齐层 — AlignmentPipeline

### 文件: `data_alignment/pipeline.py`, `normalizers/`

### 5.1 Pipeline 核心流程

```
align_and_save(source_id, raw_data, meta, db_session)
    │
    ├── 1. align(source_id, raw_data, meta)
    │       ├── registry.get(source_id) → DataSourceConfig
    │       ├── _dispatch() → 选择 Normalizer
    │       └── _dedup.deduplicate(items)
    │
    ├── 2. news_flash_cache.appendleft()  ← 内存直传，无论后续DB如何
    │
    ├── 3. 批量查询 existing item_ids (SELECT WHERE IN)
    │       ├── 已存在: UPSERT crawled_at + hotness_score
    │       └── 新条目: 进入 LLM 分类
    │
    ├── 4. LLM 分类 (仅新条目 + domain 为空 + 非跳过前缀)
    │       └── classify_items_batch() → {domain, sub_domain}
    │
    └── 5. 批量写入 CanonicalItemModel → db_session.flush()
```

### 5.2 分发路由机制 (_dispatch)

Pipeline 采用两级路由：**优先基于 config.crawl_method，回退到 source_id 启发式前缀匹配**。

```
_dispatch(source_id, rows, meta, config)
    │
    ├── config.crawl_method == "rss"
    │     ├── academic.arxiv.* → AcademicNormalizer.normalize_arxiv_paper()
    │     └── 其他 → NewsNormalizer.normalize_batch_from_feedparser()
    │
    ├── config.source_type == "hotsearch"
    │     ├── tech.oss.github_trending → TechNormalizer.normalize_github_trending()
    │     └── 其他 → HotSearchNormalizer.normalize_batch()
    │
    ├── 回退模式 (source_id 前缀):
    │     ├── social.*      → SocialNormalizer
    │     ├── economy.*     → _dispatch_economy() → EconomyNormalizer
    │     ├── tech.*        → _dispatch_tech() → TechNormalizer
    │     ├── academic.*    → AcademicNormalizer
    │     ├── global.conflict.acled → GeoEventNormalizer.normalize_acled()
    │     ├── global.disaster.usgs  → GeoEventNormalizer.normalize_usgs()
    │     ├── global.conflict.gdelt → GeoEventNormalizer.normalize_gdelt()
    │     ├── global.military.*     → MilitaryNormalizer
    │     ├── tech.infra.*          → TechNormalizer.normalize_service_status()
    │     └── tech.ai.*             → TechNormalizer.normalize_ai_service_status()
```

### 5.3 十种 Normalizer 职责

| Normalizer | 文件 | 处理的 source_id | 核心输出 |
|-----------|------|-----------------|---------|
| `NewsNormalizer` | news_normalizer.py | RSS 新闻 (BBC/Reuters/arXiv...) | title/body/url/published_at/hotness(时间衰减) |
| `SocialNormalizer` | social_normalizer.py | social.bilibili/weibo/zhihu... | title/author/raw_engagement/hotness(参与度加权) |
| `GeoEventNormalizer` | geo_event_normalizer.py | global.conflict.*/global.disaster.* | geo_lat/geo_lon/geo_country/severity |
| `MilitaryNormalizer` | combined_normalizers.py | global.military.opensky/ais | ICAO/callsign/alt/speed 飞行器状态 |
| `MarketNormalizer` | combined_normalizers.py | market.coingecko | EconomicMetadata: 价格/涨跌幅/市值 |
| `CyberNormalizer` | combined_normalizers.py | tech.cyber.feodo/urlhaus | IP/URL 威胁情报 |
| `HotSearchNormalizer` | hotsearch_normalizer.py | global.social.*_newsnow / economy.stock.* | rank/热度/平台标签 |
| `EconomyNormalizer` | economy_normalizer.py | economy.stock.*/quant.*/futures.* | EconomicMetadata + 量化信号 |
| `TechNormalizer` | tech_normalizer.py | tech.oss.*/cyber.*/infra.*/ai.* | GitHub stars/CVE评分/服务状态 |
| `AcademicNormalizer` | academic_normalizer.py | academic.arxiv.*/huggingface.*/semantic_scholar | 论文摘要/引用数/AI关键词 |

### 5.4 CanonicalItem 统一数据模型

```python
@dataclass
class CanonicalItem:
    # 身份
    item_id: str          # "{source_id}:{original_id}" 全局唯一
    source_id: str
    source_type: str

    # 内容
    title: str
    body: Optional[str]
    author: Optional[str]
    url: Optional[str]

    # 时间 (UTC aware)
    published_at: Optional[datetime]
    crawled_at: datetime   # 默认 utcnow()

    # 地理
    geo_lat/geo_lon/geo_country/geo_region

    # 量化
    hotness_score: float   # [0, 100] log压缩 or 指数衰减
    severity_level: str    # info/low/medium/high/critical
    sentiment: float       # [-1.0, 1.0] (预留)

    # 原始快照
    raw_engagement: dict   # likes/comments/shares/views
    raw_metadata: dict     # domain-specific fields

    # 分类
    domain: str
    sub_domain: str
    categories: list[str]
    keywords: list[str]
    is_classified: bool
    classification_source: str  # keyword/ml/llm
```

### 5.5 热度计算算法

**社交类** (参与度驱动):
```
raw = likes×1 + comments×5 + shares×10 + views×0.1 + favorites×10 + danmaku×0.5
hotness = log10(1 + raw) / log10(1 + 1,000,000) × 100
```

**新闻/事件类** (时间衰减驱动):
```
base = severity_base(level)  # critical=100 / high=80 / medium=55 / low=30 / info=15
bonus = 震级/伤亡/涨跌幅换算
age_hours = (now - published_at).total_seconds() / 3600
hotness = (base + bonus) × e^(-0.035 × age_hours)  # CRITICAL 半衰期≈20h
```

---

## 6. 去重层 — Deduplicator

### 文件: `data_alignment/deduplicator.py`

三策略级联去重，每次 `align()` 调用时无状态执行：

```
策略1: item_id 精确匹配 (O(1) set lookup)
     ↓ 通过
策略2: 地理格点去重 (仅 geo/military/climate 类型)
     - 0.1° × 0.1° 网格 + 日期 → 同格点同类型事件合并
     - 保留 severity_level 更高者
     ↓ 通过
策略3: 文本 Jaccard 相似度 (按 source_type 分桶)
     - 词集交并比 > 0.65 视为重复
     - 保留 published_at 更新者
```

---

## 7. AI 增强层 — LLMClient

### 文件: `utils/llm_client.py`

### 7.1 两大核心功能

**批量领域分类** `classify_items_batch(items_data)`:
- 一次最多 20 条，Prompt 格式化为 `Title + Body[:500]`
- LLM 返回严格 JSON: `{item_id: {domain, sub_domain}}`
- 自动容错: `tech→technology`, `finance→economy`, `science→academic`, `politics→global`
- 触发条件: **新条目** + **domain 为空** + **排除已知前缀** (`global.social.*`, `economy.stock.*`, `tech.*`, `academic.*`)

**领域摘要生成** `generate_summary(domain_groups, target_domain?)`:
- 支持全局综述 (4域各15条) 和单域深度分析 (300字以内)
- 系统 Prompt: "You are a professional intelligence analyst"
- 输出: Markdown 格式中文报告

### 7.2 LLM 跳过策略

以下源直接由 `registry` 或 `normalizer` 确定 domain，**不走 LLM**，避免无上下文误分类（中文内容被归为 technology）：

```python
_SKIP_LLM_PREFIXES = (
    "global.social.", "global.diplomacy.",
    "economy.stock.", "economy.crypto.", "economy.futures.",
    "tech.oss.", "tech.ai.", "tech.infra.", "tech.cyber.",
    "academic.",
)
```

---

## 8. 数据库 & 持久层 — DB Models

### 文件: `db/models.py`, `db/session.py`

### 8.1 四张核心表

```
canonical_items          ← 主数据表，所有对齐后条目
raw_items                ← 原始采集备份，支持离线重放对齐
crawl_tasks              ← 爬虫任务执行记录
data_source_health       ← 数据源健康检查历史
```

### 8.2 canonical_items 索引策略

| 索引 | 列 | 用途 |
|------|---|------|
| `uq_canonical_item_id` | item_id (UNIQUE) | 幂等 UPSERT 去重 |
| `ix_canonical_source_id` | source_id | 按源查询 |
| `ix_canonical_published_at` | published_at | 时间排序 |
| `ix_canonical_hotness` | hotness_score | 热度排序 |
| `ix_canonical_geo` | (geo_lat, geo_lon) | 地理范围查询 |
| `ix_canonical_domain` | domain | 域过滤 |
| `ix_canonical_sub_domain` | sub_domain | 子域过滤 |

### 8.3 UPSERT 写入策略 (pipeline.py)

```
1. SELECT WHERE item_id IN (ids)  → 区分新旧条目
2. 旧条目: UPDATE crawled_at=now (如有 hotness 则同时更新 hotness_score)
3. 新条目: → LLM 分类 → INSERT
4. db_session.flush()  (commit 由外层上下文管理)
```

**回滚保障**: 写入失败时 `rollback()`，但对 `news_flash_cache` 的更新已在 flush 之前完成（内存与 DB 可能短暂不一致）。

---

## 9. 内存缓存层 — NewsFlash Cache

### 文件: `memory_cache.py`, `pipeline.py`

```python
# memory_cache.py
from collections import deque
news_flash_cache = deque(maxlen=200)  # 固定大小循环队列，200条最新数据
```

**关键特性**:
- 位于 `align_and_save()` 中 DB 写入之前，**无论 DB 是否成功都更新**
- 每条记录队内去重: 先删同 `item_id` 的旧记录，再 `appendleft` 置顶
- 提供 0 延迟访问 (无 SQL 查询)，专供 `/api/v1/newsflash` 端点

**数据格式** (极简):
```json
{
  "item_id": "...", "title": "...", "url": "...",
  "domain": "economy", "sub_domain": "stock",
  "source_id": "...", "crawled_at": "ISO", "published_at": "ISO",
  "hotness_score": 42.3
}
```

---

## 10. 接口层 — Flask API & SSE

### 文件: `main.py`

### 10.1 完整 API 清单

| 方法 | 端点 | 功能 |
|------|------|------|
| GET | `/health` | 服务心跳 |
| GET | `/stream` | SSE 推送事件流 |
| GET | `/api/v1/domains` | 4域元信息 + 源统计 |
| GET | `/api/v1/domains/activity` | 各域条目数/24h新增/地区分布 |
| GET | `/api/v1/domains/{domain}/sources` | 域下所有数据源 |
| GET | `/api/v1/domains/{domain}/items` | 域下 CanonicalItem 分页 |
| GET | `/api/v1/items` | 全量查询（domain/sub_domain/sort/last_24h 过滤） |
| GET | `/api/v1/newsflash` | 0延迟内存热搜 (无DB) |
| GET | `/api/v1/sources` | 数据源注册列表 |
| GET | `/api/v1/sources/health` | 触发全量健康检查 |
| GET | `/api/v1/scheduler/status` | 调度器状态 + stale_cache |
| POST | `/api/v1/scheduler/trigger/{source_id}` | 手动触发特定源 |
| POST | `/api/v1/scheduler/trigger-all` | 全量刷新 |
| POST | `/api/v1/crawl/rss` | 触发 RSS 采集 |
| POST | `/api/v1/crawl/api` | 触发 API 采集 |
| POST | `/api/v1/crawl/hotsearch` | 触发热搜采集 |
| POST | `/api/v1/crawl/all` | 全量采集 |
| GET | `/api/v1/crawl/tasks` | 最近50条任务记录 |

### 10.2 Flask 异步桥接模式

Flask 是同步框架，异步任务通过以下方式运行：
```python
def _run_async(coro):
    """在独立线程 + 新事件循环中运行协程（不阻塞 Flask 线程）"""
    t = threading.Thread(target=_thread, daemon=True)
    t.start()
```

### 10.3 SSE 广播机制

```python
_sse_clients: list[queue.Queue]  # 所有在线 SSE 客户端的 Queue 列表

def _broadcast(event: dict):
    for q in _sse_clients:
        q.put_nowait(event)   # 非阻塞投递, Queue.Full 时移除死连接

# /stream 端点: 每个客户端独立 Queue(maxsize=50)
# 30秒无数据发送 keep-alive 心跳: ": keep-alive\n\n"
```

**SSE 事件类型**:
| event | 触发来源 | 数据 |
|-------|---------|------|
| `connected` | 客户端连接 | 欢迎消息 |
| `scheduler_start` | DataScheduler | source_id + domain + timestamp |
| `scheduler_done` | DataScheduler | source_id + items_count + items[:20] |
| `scheduler_error` | DataScheduler | source_id + error + stale_count |
| `task_start` | CrawlerEngine | task_id + type |
| `task_done` | CrawlerEngine | task_id + items_fetched + items_aligned |
| `align_start/done/error` | AlignmentPipeline | source_id + count |
| `health_check_done` | DataSourceRegistry | summary |

---

## 11. 前端消费模式

### 11.1 主动拉取 (HTTP Polling)

- `/api/v1/items?domain=economy&sort=heat&limit=50` — 热度排序数据卡片
- `/api/v1/newsflash?domain=global&limit=8` — 实时新闻滚动条 (内存，0延迟)
- `/api/v1/domains/activity` — 域活跃度仪表板数值

### 11.2 被动推送 (SSE EventSource)

```javascript
const es = new EventSource('/stream');
es.onmessage = e => {
  const data = JSON.parse(e.data);
  if (data.event === 'scheduler_done') {
    // 收到新数据通知 → 刷新对应域的卡片
    refreshDomain(data.domain);
  }
};
```

前端通过 SSE 事件的 `domain` 字段判断哪个域有更新，精准触发局部刷新，避免全页轮询。

---

## 12. 数据流全链路追踪

以 **CoinGecko 加密货币价格更新** 为例追踪完整链路：

```
T+0s  APScheduler 触发 economy.crypto.coingecko (REALTIME: 1min)
        └── DataScheduler._run_sync_wrapper("economy.crypto.coingecko")
                └── asyncio.run_coroutine_threadsafe(_crawl(), loop)

T+0.1s SSE broadcast: {event: "scheduler_start", source_id: "economy.crypto.coingecko", domain: "economy"}

T+0.5s _crawl() → _dispatch_crawl() → CrawlerEngine.run_api("economy.crypto.coingecko")
         └── CoinGeckoAdapter.fetch_prices(["bitcoin","ethereum","solana"])
               └── httpx GET https://api.coingecko.com/api/v3/simple/price?ids=...
                     → {bitcoin: {usd: 65000, usd_24h_change: 2.3}, ...}

T+1.2s raw_data → [{coin_id: "bitcoin", usd: 65000, ...}, ...]
         └── for each coin: pipeline.align_and_save(source_id, [row], meta={coin_id})

T+1.3s AlignmentPipeline.align()
         └── _dispatch() → economy.* → _dispatch_economy()
               └── EconomyNormalizer.normalize_coingecko(row, source_id)
                     → CanonicalItem {
                           item_id: "economy.crypto.coingecko:bitcoin",
                           title: "Bitcoin (BTC) — $65,000 (+2.30%)",
                           hotness_score: 75.2,  # severity=high + 时间衰减
                           raw_metadata: {economic: {price:65000, change_pct:2.3}}
                           domain: "economy", sub_domain: "crypto"
                        }
         └── Deduplicator → item_id 精确去重

T+1.4s news_flash_cache.appendleft(item_dict)  ← 内存立即可见

T+1.5s SELECT WHERE item_id IN [...]  → 已存在?
         ├── 是: UPDATE crawled_at=now, hotness_score=75.2
         └── 否: (新上市货币) INSERT CanonicalItemModel

T+1.6s db_session.flush() → SQLite WAL 写入

T+1.7s SSE broadcast: {
          event: "scheduler_done",
          source_id: "economy.crypto.coingecko",
          domain: "economy",
          items_count: 3,
          items: [{item_id, title, hotness_score, ...}]  // 前20条
        }

T+1.8s 前端 SSE 收到 → 刷新经济域加密货币卡片
         GET /api/v1/items?domain=economy&sub_domain=crypto&sort=heat

T+1.9s Flask 同步查询 canonical_items WHERE domain='economy' AND sub_domain='crypto'
         ORDER BY hotness_score DESC, crawled_at DESC LIMIT 50
         → 返回 JSON，前端渲染

总延迟: ~1.9秒 (采集 → 前端可见)
```

---

## 13. 架构强项与潜在风险

### 13.1 架构强项

| 优势 | 说明 |
|------|------|
| **统一数据模型** | CanonicalItem 贯穿全链路，81个异构源统一为单一 schema |
| **零停机更新** | stale-while-revalidate 模式，数据源出错不影响前端显示 |
| **0延迟内存层** | `news_flash_cache deque` 绕过 DB，NewsFlash 端点无 SQL 开销 |
| **三层去重** | ID精确 + 地理格点 + Jaccard 文本相似，多维防止数据噪声 |
| **LLM 智能分类** | 新条目自动补全 domain/sub_domain，降低人工维护成本 |
| **SSE 实时推送** | 前端不轮询，被动接收域更新通知，精准触发局部刷新 |
| **任务全追踪** | CrawlTaskModel + in-memory CrawlerTask 双层任务状态记录 |

### 13.2 潜在风险点

| 风险 | 位置 | 描述 | 建议 |
|------|------|------|------|
| **SQLite WAL 并发** | db/ | SQLite 在高并发写入时性能瓶颈，WAL 文件已 ~25MB | 考虑迁移 PostgreSQL |
| **内存与DB不一致** | pipeline.py:401 | news_flash_cache 先于 DB flush 更新，回滚时内存有脏数据 | 加事务完成后回调 |
| **SSE Queue 背压** | main.py:67 | Queue(maxsize=50) 满时静默丢弃事件，高频 REALTIME 源可能丢失 | 增加 size 或改异步 |
| **单点 asyncio 循环** | scheduler.py | 所有定时任务共享同一 asyncio 循环，单任务阻塞影响全局 | 限制每源 timeout=30s |
| **API Rate Limit** | extended_adapters.py | Yahoo Finance / CoinGecko 免费限额，REALTIME_INTERVAL_MIN=1 可能触发 429 | 实现重试指数退避 |
| **LLM 批量失败** | pipeline.py:523 | LLM 分类异常仅 logger.error，domain 留空条目入库 | 增加 fallback 关键词分类 |
| **Playwright 未实际运行** | registry.py | 社交平台 (B站/微博/抖音) 注册了 playwright 采集，但引擎代码中无 Playwright 实现 | 完善 SocialScraper |

---

## 附录: 关键参数速查

| 参数 | 值 | 位置 |
|------|---|------|
| 数据源总数 | 81 | registry.py |
| 调度 TTL 层数 | 5 (1/5/30/60/360 min) | scheduler.py |
| APScheduler 线程池 | 4 workers | scheduler.py:171 |
| 任务超时 | 120s | scheduler.py:214 |
| news_flash_cache 容量 | 200条 | memory_cache.py |
| SSE Queue 容量/客户端 | 50事件 | main.py:80 |
| SSE 心跳间隔 | 30s | main.py:89 |
| Jaccard 去重阈值 | 0.65 | deduplicator.py:53 |
| 地理格点精度 | 0.1° (~11km) | deduplicator.py:38 |
| 热度衰减系数 λ | 0.035 (半衰期≈20h CRITICAL) | schema.py:262 |
| LLM 分类批次大小 | 20条/次 | pipeline.py:506 |
| SQLite 数据库体积 | ~88MB + 25MB WAL | u24time.db |
