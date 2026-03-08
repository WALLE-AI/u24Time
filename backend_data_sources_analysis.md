# u24Time 后端数据源深度分析报告

> 生成时间：2026-03-08  
> 分析范围：`backend/crawler_engine`, `backend/data_alignment`, `backend/scheduler.py`, `backend/data_source/registry.py`

---

## 一、总体架构概览

```
外部数据源
   │
   ├── RSS Feeds (feedparser)
   ├── NewsNow BettaFish API (热搜聚合)
   ├── GitHub REST API (enrichment)
   ├── HuggingFace API
   ├── Semantic Scholar API
   ├── arXiv RSS
   └── 其他 API (USGS, CoinGecko, Yahoo Finance ...)
         │
         ▼
   CrawlerEngine (engine.py)          ← 统一调度入口
   ├── run_rss()                       ← RSS 采集
   ├── run_api()                       ← API 直连采集
   ├── run_hotsearch()                 ← 热搜批量采集 + GitHub 二次增强
   └── run_custom_adapter()            ← 自定义采集器包装
         │
         ▼
   AlignmentPipeline (pipeline.py)    ← 数据对齐管道
   ├── _dispatch()                     ← source_id 路由
   ├── Normalizer.*()                  ← 各域标准化
   ├── Deduplicator.deduplicate()      ← MD5 去重
   ├── LLM classify_items_batch()      ← 可选 LLM 分类（仅非已知域）
   └── CanonicalItemModel → SQLite DB ← 持久化
         │
         ▼
   DataScheduler (scheduler.py)       ← APScheduler 定时驱动
   └── SOURCE_SCHEDULE (TTL 分层)
```

---

## 二、数据源清单

### 2.1 GitHub 趋势 (tech.oss.github_trending)

| 属性 | 详情 |
|---|---|
| **source_id** | `tech.oss.github_trending` |
| **采集频率** | 每 5 分钟 (NEWS_INTERVAL_MIN) |
| **一级数据来源** | BettaFish NewsNow API (`newsnow.busiyi.world`) |
| **二级增强来源** | GitHub REST API v3 (`api.github.com`) |
| **所需凭证** | `GITHUB_TOKEN`（可选，无 token 时速率上限更低）|
| **域/子域** | `TECH` / `OSS` |
| **标准化器** | `TechNormalizer.normalize_github_trending()` |

#### 采集流程（双阶段）

```
Stage 1 — NewsNow 热榜列表
  NewsNowAdapter._fetch_one()
    GET https://newsnow.busiyi.world/api/s?id=github-trending-today&latest
    返回: { items: [{title, url, stars, description, extra{hover}} ...] }

Stage 2 — GitHub API 批量增强 (enrichen_trending_repos)
  GithubAdapter.enrichen_trending_repos(items)     ← asyncio.Semaphore(10) 并发
    ├── GET https://api.github.com/repos/{owner}/{repo}
    │     → stars, forks, pushed_at
    └── GET https://api.github.com/repos/{owner}/{repo}/commits?since=30d&per_page=1
          → Link Header rel="last" 解析 commits_30d
```

#### 数据对齐

```python
# tech_normalizer.py: normalize_github_trending()
score = stars_today + min(commits_30d, 100) * 5   # 活跃度评分
severity:
  score >= 1000 → CRITICAL
  score >= 600  → HIGH
  score >= 200  → MEDIUM
  else          → INFO

CanonicalItem:
  item_id   = MD5(source_id + name)[:16]
  domain    = TECH
  sub_domain = OSS
  title     = "⭐ {name} [{language}] — {description[:80]}"
  url       = GitHub repo URL
  published_at = last_commit_at（来自 GitHub API pushed_at）
  raw_engagement = {stars, stars_today, commits_30d, score}
```

---

### 2.2 HuggingFace 每日论文 (academic.huggingface.papers)

| 属性 | 详情 |
|---|---|
| **source_id** | `academic.huggingface.papers` |
| **采集频率** | 每 60 分钟 (MACRO_INTERVAL_MIN) |
| **数据来源** | HuggingFace 官方 API (`huggingface.co/api/daily_papers`) |
| **所需凭证** | 无（免费，无需 API Key）|
| **域/子域** | `ACADEMIC` / `PAPER` |
| **标准化器** | `AcademicNormalizer.normalize_huggingface_paper()` |

#### 采集流程

```
HuggingFaceAdapter.fetch(limit=30)
  GET https://huggingface.co/api/daily_papers?limit=30
  返回: list[{
    paper: {id, title, summary, publishedAt, ...},
    numComments,
    upvotes
  }]
```

#### 数据对齐

```python
# academic_normalizer.py: normalize_huggingface_paper()
upvotes = paper.get("numComments") or paper.get("upvotes", 0)
hotness = min(100.0, max(5.0, 20.0 * math.log1p(upvotes + 1)))
  # 1 vote=5, 10=40, 100=70, 1000=100（对数归一化）

CanonicalItem:
  item_id   = MD5("hf_paper" + paper_id + title[:20])[:16]
  source_id = "academic.huggingface.papers"
  domain    = ACADEMIC
  sub_domain = PAPER
  severity  = MEDIUM（HF 论文全为 AI 相关，固定 MEDIUM）
  hotness_score = log(upvotes)归一化，5~100
  published_at  = paper.publishedAt (ISO 8601)
  url       = "https://huggingface.co/papers/{paper_id}"
  raw_engagement = {comments: upvotes}
```

---

### 2.3 HuggingFace 热门模型/数据集 (tech.ai.hf_models / hf_datasets)

| 属性 | 详情 |
|---|---|
| **source_id** | `tech.ai.hf_models`, `tech.ai.hf_datasets` |
| **采集频率** | 每 5 分钟 (NEWS_INTERVAL_MIN) |
| **数据来源** | HuggingFace API (`/api/models?sort=trending`, `/api/datasets?sort=trending`) |
| **所需凭证** | 无 |
| **域/子域** | `TECH` / `OSS` |
| **标准化器** | `TechNormalizer.normalize_hf_trend()` |

#### 采集流程

```
HuggingFaceAdapter.fetch_trending_models(limit=20)
  GET https://huggingface.co/api/models?sort=trending&limit=20&direction=-1
  返回: [{id, author, likes, downloads, tags, ...}]

HuggingFaceAdapter.fetch_trending_datasets(limit=20)
  GET https://huggingface.co/api/datasets?sort=trending&limit=20&direction=-1
```

#### 数据对齐

```python
# tech_normalizer.py: normalize_hf_trend()
CanonicalItem:
  title  = "🤗 {name} [⬇️ {downloads}]"
  body   = "Author: {author} | Likes: {likes}\nTags: {tags[:5]}"
  severity = HIGH if downloads > 1000 else INFO
  url    = "https://huggingface.co/{model_id}"
```

---

### 2.4 Semantic Scholar 趋势论文 (academic.semantic_scholar.trending)

| 属性 | 详情 |
|---|---|
| **source_id** | `academic.semantic_scholar.trending` |
| **采集频率** | 每 60 分钟 (MACRO_INTERVAL_MIN) |
| **数据来源** | Semantic Scholar Graph API v1 |
| **所需凭证** | 无（有严格限速：2 req/s，实现中加 2s 延迟）|
| **域/子域** | `ACADEMIC` / `PAPER` |
| **标准化器** | `AcademicNormalizer.normalize_semantic_scholar()` |

#### 采集流程

```
SemanticScholarAdapter.fetch_trending(query="AI", limit=30)
  await asyncio.sleep(2)   ← 主动降速避免 429
  GET https://api.semanticscholar.org/graph/v1/paper/search
    ?query=AI&limit=30&fields=title,abstract,url,year,citationCount,authors
    &sort=citationCount:desc       ← 以引用量近似"趋势"
  返回: {data: [{paperId, title, abstract, url, year, citationCount, authors[]}]}

  on HTTP 429: 直接返回 [] 不抛出异常（429 单独处理）
```

#### 数据对齐

```python
# academic_normalizer.py: normalize_semantic_scholar()
citations = paper.get("citationCount", 0)
hotness = min(100.0, max(5.0, 15.0 * math.log1p(citations + 1)))
  # 0 cite=5, 10=30, 100=55, 1000=85, 10000=100

CanonicalItem:
  domain    = ACADEMIC
  sub_domain = PAPER
  severity  = INFO
  hotness_score = log(citations) 归一化
  published_at  = year 字段（仅年份精度，dateutil 宽松解析）
```

---

### 2.5 arXiv 论文 (academic.arxiv.*)

| 属性 | 详情 |
|---|---|
| **source_id** | `academic.arxiv.cs_ai`, `cs_lg`, `cs_cv`, `cs_cl`, `econ`, `physics`, `q_bio`, `math_st` |
| **采集频率** | 每 60 分钟 |
| **数据来源** | arXiv RSS Feed（通过 `RSSFetcher + feedparser`）|
| **所需凭证** | 无 |
| **域/子域** | `ACADEMIC` / `PAPER` |
| **标准化器** | `AcademicNormalizer.normalize_arxiv_paper()` |

#### 热度计算

```python
# 基于时效性的指数衰减
age_hours = (now - published).total_seconds() / 3600
recency_score = max(5.0, 80.0 * math.exp(-age_hours / 48.0))  # 半衰期 48h
# AI热词加成 1.3x：llm, gpt, transformer, diffusion, agent, reasoning
```

---

### 2.6 ModelScope (tech.ai.ms_models / ms_datasets)

| 属性 | 详情 |
|---|---|
| **source_id** | `tech.ai.ms_models`, `tech.ai.ms_datasets` |
| **采集频率** | 每 5 分钟（已注册但**当前未实现**）|
| **状态** | ⚠️ `ModelScopeAdapter` 存在于 `extended_adapters.py`，但 `scheduler.py` 中标注为"未实现，跳过" |
| **标准化器** | `TechNormalizer.normalize_ms_trend()` （已实现，待接入）|

---

## 三、其他数据源汇总

| 域 | source_id | 采集来源 | 频率 |
|---|---|---|---|
| **Economy** | `economy.crypto.coingecko` | CoinGecko API v3 | 1 min |
| **Economy** | `economy.stock.country_index` | Yahoo Finance Chart API v8 | 1 min |
| **Economy** | `economy.futures.commodity_quotes` | Yahoo Finance (GC=F, CL=F...) | 1 min |
| **Economy** | `economy.quant.fear_greed_index` | alternative.me/crypto/fear-and-greed | 1 min |
| **Economy** | `economy.quant.mempool_hashrate` | mempool.space API | 1 min |
| **Social** | `global.social.weibo_newsnow` | NewsNow API (BettaFish) | 5 min |
| **Tech** | `tech.oss.hackernews` | HN Firebase REST API | 5 min |
| **Tech** | `tech.infra.*` / `tech.ai.*_status` | StatusPage.io v2 JSON API | 1 min |
| **Tech** | `tech.cyber.nvd_cve` | NIST NVD CVE API 2.0 | 30 min |
| **Tech** | `tech.cyber.feodo` | Feodo Tracker CSV | 30 min |
| **Tech** | `tech.cyber.urlhaus` | URLhaus CSV | 30 min |
| **Geo** | `global.disaster.usgs` | USGS Earthquake API | 30 min |
| **Geo** | `global.disaster.nasa_firms` | NASA FIRMS VIIRS SNPP | 30 min |
| **Geo** | `global.conflict.gdelt` | GDELT v2 Events CSV (15min 更新) | 30 min |
| **Geo** | `global.conflict.acled` | ACLED API v1 | 60 min |
| **Geo** | `global.conflict.humanitarian` | ReliefWeb API | 30 min |
| **Military** | `global.military.opensky` | OpenSky Network ADS-B API | 1 min |
| **Academic** | `academic.prediction.polymarket` | Polymarket Gamma API | 30 min |

---

## 四、数据对齐机制 (AlignmentPipeline)

### 4.1 路由逻辑

```
AlignmentPipeline.align(source_id, raw_data, meta)
    │
    ├── Step 1: registry.get(source_id) → DataSourceConfig
    │     └── 若 config.crawl_method == "rss" → NewsNormalizer / AcademicNormalizer
    │    
    ├── Step 2: source_id 前缀/精确匹配 _dispatch()
    │     ├── "tech.oss.github_trending"     → TechNormalizer.normalize_github_trending()
    │     ├── "academic.huggingface.papers"  → AcademicNormalizer.normalize_huggingface_paper()
    │     ├── "academic.semantic_scholar.*"  → AcademicNormalizer.normalize_semantic_scholar()
    │     ├── "academic.arxiv.*"             → AcademicNormalizer.normalize_arxiv_paper()
    │     ├── "economy.*"                    → _dispatch_economy()
    │     └── "tech.*"                       → _dispatch_tech()
    │
    └── Step 3: Deduplicator.deduplicate()
          └── 按 item_id (MD5 hash) 去重
```

### 4.2 CanonicalItem 统一模式 (schema.py)

所有数据源经 Normalizer 后输出 `CanonicalItem`，字段统一如下：

```
CanonicalItem:
  item_id           str    # MD5[:16]，业务主键
  source_id         str    # 数据源注册 ID
  source_type       enum   # NEWS / SOCIAL / MARKET / CYBER / GEO
  domain            enum   # TECH / ACADEMIC / ECONOMY / GLOBAL / MILITARY
  sub_domain        enum   # OSS / PAPER / CYBER / INFRA / ...
  title             str    # 标准化标题
  body              str    # 摘要/描述
  url               str    # 原始链接
  author            str    # 作者（学术/新闻类）
  published_at      datetime
  crawled_at        datetime
  geo_lat/lon       float  # 地理事件专用
  hotness_score     float  # 0~100，热度归一化
  severity_level    enum   # INFO / LOW / MEDIUM / HIGH / CRITICAL
  raw_engagement    dict   # {stars, upvotes, citations, ...} 原始互动数据
  raw_metadata      dict   # 源特定元数据
  categories        list   # 标签分类
  is_classified     bool   # 是否经 LLM 补充分类
  classification_source str
```

### 4.3 热度评分算法对比

| 数据源 | 热度公式 | 范围 |
|---|---|---|
| **HuggingFace Papers** | `20 * log(upvotes + 1)` clamp(5,100) | 0~100 |
| **Semantic Scholar** | `15 * log(citations + 1)` clamp(5,100) | 0~100 |
| **arXiv RSS** | `80 * exp(-age_hours / 48)` × 1.3 (AI 词) | 5~100 |
| **GitHub Trending** | `stars_today + min(commits_30d,100) × 5` → severity 分级 | N/A (4级) |

### 4.4 去重机制

```python
# deduplicator.py
item_id = MD5(source_id + 关键字段)[:16]
```

- `GitHub repo`：`MD5(source_id + repo_name)`
- `HF Paper`：`MD5("hf_paper" + paper_id + title[:20])`
- `arXiv`：`MD5("arxiv" + arxiv_id + category)`
- `Semantic Scholar`：`MD5("ss_paper" + paper_id + title[:20])`

数据库 UPSERT 策略：
- **已存在条目**：仅更新 `crawled_at`（有 hotness 则一并更新 `hotness_score`）
- **新条目**：完整写入，可选触发 LLM 域分类

---

## 五、调度策略 (DataScheduler)

### TTL 分层（WorldMonitor stale-while-revalidate 模式）

```
REALTIME_INTERVAL  =  1 min  ← 价格/飞行/服务状态/BTC算力
NEWS_INTERVAL      =  5 min  ← 热搜/HN/GitHub Trending/HF模型
EVENT_INTERVAL     = 30 min  ← 冲突/CVE/火点/ReliefWeb
MACRO_INTERVAL     = 60 min  ← 宏观指标/HF论文/Semantic Scholar/arXiv
SLOW_INTERVAL      =360 min  ← WTO贸易/世界银行
```

### 关键调度特性

1. **独立事件循环线程**：APScheduler 启动独立 asyncio 线程，不阻塞 FastAPI 主循环
2. **stale-while-revalidate**：采集失败时保留上次成功的 `_last_success` 记录，前端 API 永远有数据
3. **120s 超时保护**：每个调度任务 `future.result(timeout=120)`
4. **SSE 实时推送**：每次采集完成通过 `broadcast_cb` 推送 `scheduler_done` 事件（前 20 条 item）
5. **SQLite WAL Checkpoint**：每 30 分钟执行 `PRAGMA wal_checkpoint(TRUNCATE)` 防止 WAL 文件膨胀

---

## 六、GitHub Trending 双阶段增强详解

这是整个系统最具特色的数据采集设计：

```
┌─────────────────────────────────────────────────────────────┐
│                  Stage 1: NewsNow 基础数据                    │
│  GET /api/s?id=github-trending-today&latest                 │
│  → items[]: {title:"owner/repo", url, stars, extra{hover}} │
└───────────────────────────┬─────────────────────────────────┘
                            │ enrichen_trending_repos()
                            │ asyncio.Semaphore(10) 并发
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Stage 2: GitHub API 补全                    │
│  GET /repos/{owner}/{repo}                                  │
│  → stars(实时), forks, pushed_at                            │
│  GET /repos/{owner}/{repo}/commits?since=30d&per_page=1     │
│  → Link: <...?page=N>; rel="last"  → commits_30d=N         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
                   normalize_github_trending()
                   score = stars_today + commits_30d*5
                   severity = CRITICAL/HIGH/MEDIUM/INFO
```

**设计意图**：NewsNow API 提供"快"（5分钟级热榜），GitHub API 提供"准"（真实活跃度），两者融合得到既热门又活跃的仓库列表。

---

## 七、LLM 辅助分类

对于无法通过 source_id 确定域分类的新条目，`pipeline.py` 会调用 `LLMClient.classify_items_batch()` 进行批量分类（批大小=20条）。

**跳过 LLM 的前缀**（已有确证 domain）：
```
global.social.*, global.diplomacy.*,
economy.stock.*, economy.crypto.*, economy.futures.*,
tech.oss.*, tech.ai.*, tech.infra.*, tech.cyber.*,
academic.*
```

即：GitHub Trending、HuggingFace 相关源**全部跳过 LLM**，直接使用 Normalizer 输出的固定 domain。

---

## 八、数据流完整链路（以 GitHub Trending 为例）

```
DataScheduler (每5分钟)
  │
  │  _dispatch_crawl("tech.oss.github_trending")
  │    └── run_hotsearch(["tech.oss.github_trending"])
  │
  ├── NewsNowAdapter.fetch_all(["tech.oss.github_trending"])
  │     └── GET newsnow.busiyi.world/api/s?id=github-trending-today&latest
  │           → {items: [...30 repos...]}
  │
  ├── [检测到 "tech.oss.github_trending" in batch]
  │     └── GithubAdapter.enrichen_trending_repos(items)
  │           ├── asyncio.Semaphore(10) 并发
  │           └── 每个 repo: GET api.github.com/repos/{owner}/{repo}
  │                          GET /commits?since=30d&per_page=1
  │
  ├── AlignmentPipeline.align_and_save()
  │     ├── _dispatch → _dispatch_tech → normalize_github_trending()
  │     ├── Deduplicator.deduplicate()   ← MD5 去重
  │     ├── DB UPSERT (CanonicalItemModel)
  │     ├── _update_news_flash_cache()   ← 内存队列 appendleft
  │     └── [skip LLM as source starts with "tech.oss."]
  │
  └── broadcast_cb({event:"scheduler_done", items:[...20...]})  ← SSE 推送
```

---

## 九、发现的问题与改进建议

### 9.1 已知问题

| 问题 | 位置 | 说明 |
|---|---|---|
| ModelScope 未接入 | `scheduler.py:394-396` | `tech.ai.ms_models/ms_datasets` 已注册调度但直接 `return []` |
| Semantic Scholar 准确度 | `extended_adapters.py:525` | 用 `citationCount:desc` 代替真实趋势，只反映历史累计引用非当下热度 |
| HF Paper upvotes 字段优先级 | `academic_normalizer.py:112` | `numComments` 优先于 `upvotes`，可能语义混淆 |
| GitHub Token 缺失时限速严重 | `github_adapter.py:27` | 无 token 时 GitHub API 60 req/h，10 个并发仓库详情会快速耗尽 |
| GDELT 数量截断 | `adapters.py:175` | `return events[:500]` 硬截断，可能丢失重要事件 |

### 9.2 改进建议

1. **补全 ModelScope 适配器接入**：`ModelScopeAdapter` 已实现，仅需在 `scheduler._dispatch_crawl` 中添加路由
2. **Semantic Scholar 改用 Recommendations API**：`/recommendations/v1` 提供真实个性化推荐，比 search by citationCount 更能反映趋势
3. **GitHub Token Rotation**：多 token 轮换避免 enrichment 阶段限速
4. **HuggingFace Papers 增量采集**：API 支持 `page` 参数，可实现增量采集而非每次全量 30 条

---

*本报告由 Antigravity AI Agent 自动分析生成，覆盖后端数据源架构的全部关键层次。*
