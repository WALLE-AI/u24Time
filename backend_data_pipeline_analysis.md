# WALL-AI u24Time Backend 数据管道全栈分析报告

> 分析范围：`data_source/` → `crawler_engine/` → `data_alignment/` → `scheduler.py` → `main.py` → 前端 `App.tsx`
> 涵盖：领域架构 / 数据获取机制 / 定时任务生命周期 / 前端实时推送

---

## 第一章：领域分层架构

### 1.1 整体数据流

```
data_source/registry.py       ← 数据源注册表（声明式配置）
        ↓  source_id 命名约定
crawler_engine/               ← 数据获取层（API Adapter / RSS / NewsNow）
        ↓  raw_data (list[dict])
data_alignment/pipeline.py    ← 调度总线（根据 source_id 分发）
        ↓
data_alignment/normalizers/   ← 领域 Normalizer（输出 CanonicalItem）
        ↓
DB (SQLite) + memory_cache    ← 持久化 & 实时缓存
```

### 1.2 四大领域定义

| Domain      | 中文     | source_id 前缀   |
|-------------|----------|-----------------|
| economy     | 经济域   | `economy.*`      |
| technology  | 技术域   | `tech.*`         |
| academic    | 学术域   | `academic.*`     |
| global      | 全球监控 | `global.*`       |

### 1.3 source_id 命名约定（领域区分的核心锚点）

格式：`{domain}.{sub_domain}.{provider}`

```
economy.stock.akshare_a        → 经济域 / 股票 / AKShare A股
economy.quant.fred_series      → 经济域 / 量化宏观 / FRED 指标
tech.oss.github_trending       → 技术域 / 开源 / GitHub Trending
tech.cyber.nvd_cve             → 技术域 / 网络安全 / NVD CVE
academic.arxiv.cs_ai           → 学术域 / 论文 / arXiv cs.AI
academic.prediction.polymarket → 学术域 / 预测市场 / Polymarket
global.conflict.acled          → 全球域 / 武装冲突 / ACLED
global.disaster.usgs           → 全球域 / 自然灾害 / USGS 地震
global.social.weibo_newsnow    → 全球域 / 中文社交 / 微博热搜
```

### 1.4 各领域数据源统计

| 领域       | 子域                                              | 接入数量 |
|------------|---------------------------------------------------|----------|
| economy    | stock / futures / quant / crypto / trade / finance | ~25条   |
| technology | oss / tech_news / cyber / infra / ai_service       | ~22条   |
| academic   | paper / conference / prediction                   | ~12条   |
| global     | conflict / military / diplomacy / disaster / social | ~35条  |

### 1.5 统一数据模型（CanonicalItem）

所有领域最终输出同一结构：

```python
@dataclass
class CanonicalItem:
    item_id: str          # "{source_id}:{original_id}"
    domain: str           # DomainType（领域）
    sub_domain: str       # SubDomainType（子领域）
    source_id: str        # 数据源 ID
    source_type: str      # news/market/geo/social/cyber/military
    title: str
    hotness_score: float  # [0, 100] 统一热度分
    severity_level: str   # info/low/medium/high/critical
    geo_lat/lon/country   # 地理信息
    raw_engagement: dict  # 原始互动数据
    raw_metadata: dict    # 领域专属元数据
```

### 1.6 领域区分的完整保障机制（三层叠加）

```
第1层：source_id 命名（economy./tech./academic./global.）
    ↓ Normalizer 内部设置 domain=DomainType.ECONOMY 等
第2层：pipeline.align() 中 registry 兜底
    if not item.domain:
        item.domain = config.domain  # 从注册表填充
第3层（仅新条目）：LLM 分类（align_and_save 中）
    只对 domain 确实为空的条目调用 LLM classify
    已有明确前缀的来源（economy./tech./academic.）跳过 LLM
```

---

## 第二章：数据获取机制

### 2.1 四种采集方式

#### 方式 1：RSS Feed（feedparser）

适用：arXiv 论文、BBC/Reuters 新闻、TechCrunch、军事媒体等

```
engine.run_rss(category)
    → RSSFetcher.fetch_feeds(feeds)
        → asyncio.Semaphore(concurrency) 并发控制
        → httpx.AsyncClient + feedparser.parse()
    → pipeline.align_and_save(source_id, entries)
```

特点：HTTP/2、ALLOWED_DOMAINS 白名单、tenacity 重试（3次 1~8s 退避）

#### 方式 2：专用 API Adapter（httpx 异步）

| Adapter               | 数据源      | 特殊处理                       |
|-----------------------|-------------|-------------------------------|
| ACLEDAdapter          | 武装冲突    | API Key 认证                   |
| GDELTAdapter          | 全球事件    | CSV 解析                       |
| USGSAdapter           | 地震数据    | GeoJSON features               |
| NASAFIRMSAdapter      | 野火卫星    | CSV 解析                       |
| OpenSkyAdapter        | ADS-B 飞行  | 状态向量列表                   |
| CoinGeckoAdapter      | 加密货币价格 | 多币种并发                    |
| FeodoAdapter          | C2黑名单    | CSV 解析                       |
| URLhausAdapter        | 恶意URL     | CSV 解析                       |
| YahooFinanceAdapter   | 股票/指数   | 串行+sleep(0.3s) 避免限速       |
| HackerNewsAdapter     | HN 热帖     | 两阶段：ID列表→并发详情(Sem=5) |
| CloudStatusAdapter    | 云服务状态  | 纯并发 asyncio.gather          |
| HuggingFaceAdapter    | AI论文/模型 | 无需 API Key                   |
| SemanticScholarAdapter| 学术论文    | 有限额，sleep(2s) 保护         |
| FearGreedAdapter      | FGI 指数    | alternative.me API             |
| BtcHashrateAdapter    | BTC 算力    | mempool.space API              |
| NVDAdapter            | CVE 漏洞    | CVSS≥7.0 过滤                  |
| ReliefWebAdapter      | 人道危机    | ongoing 状态过滤               |
| PolymarketAdapter     | 预测市场    | Gamma API                      |

#### 方式 3：NewsNow 热搜聚合（NewsNowAdapter）

```
engine.run_hotsearch(source_ids)
    → NewsNowAdapter.fetch_all()
        → asyncio.gather 并发拉取 12 个平台
    # 特殊：GitHub Trending 二阶段 enrichment
    if "tech.oss.github_trending" in batch:
        enriched = await GithubAdapter().enrichen_trending_repos()
    → pipeline.align_and_save(sid, [response])
```

平台映射（`NEWSNOW_SOURCE_MAP`）：
```
global.social.weibo_newsnow  → 微博热搜
economy.stock.wallstreetcn   → 华尔街见闻
tech.oss.github_trending     → GitHub Trending
... (共12个平台)
```

#### 方式 4：Python 库直接调用（lib crawl_method）

适用：AKShare（A股）、Tushare（日行情）等，直接 import 调用，无 HTTP 请求。

---

## 第三章：定时任务生命周期

### 3.1 调度分层（WorldMonitor TTL 策略）

| 层级    | 间隔  | 典型数据源                              |
|---------|-------|-----------------------------------------|
| REALTIME | 1分钟 | 股价/加密/云服务状态/ADS-B/FGI/算力   |
| NEWS    | 5分钟 | 热搜12平台/HN/TechCrunch/arXiv         |
| EVENT   | 30分钟 | USGS地震/野火/GDELT/CVE/Polymarket    |
| MACRO   | 60分钟 | FRED/BIS利率/arXiv论文/HF论文/ACLED   |
| SLOW    | 360分钟 | WTO贸易/WorldBank/IDMC难民           |

### 3.2 启动流程

```
uv run python main.py（Flask 进程启动）
    ↓ 模块级：
    _engine = CrawlerEngine()
    _scheduler = DataScheduler(engine, db_factory=None)
    _engine.set_progress_callback(_broadcast)
    atexit.register(_scheduler.shutdown)
    ↓
第一个 HTTP 请求 → @app.before_request → _ensure_scheduler()
    _scheduler._db_factory = get_async_session
    _scheduler.start()
        ├── asyncio.new_event_loop() → daemon 线程运行
        ├── APScheduler.BackgroundScheduler 启动
        ├── _register_jobs()：注册所有 source_id 定时任务
        └── trigger_all_now()：立即全量首次采集
```

**线程模型：**
```
主线程（Flask HTTP）
    ├── APScheduler 线程（ThreadPoolExecutor 4 workers）
    │       ↓ interval 触发 → asyncio.run_coroutine_threadsafe()
    └── scheduler-loop daemon 线程（asyncio 事件循环）
            ↓ 执行 async 采集 + DB 写入 + SSE 广播
```

### 3.3 单次任务执行流程

```
APScheduler 触发 _run_sync_wrapper(source_id)
    ↓ future.result(timeout=120)
    ↓
_crawl(source_id):
    1. SSE 广播 scheduler_start 事件
    2. _dispatch_crawl(source_id)：
           Adapter.fetch_*() → raw_data
           pipeline.align_and_save() → DB + memory_cache
    3. 更新 stale_cache（_last_success / _last_count）
    4. SSE 广播 scheduler_done（含前20条摘要）

失败时（stale-while-revalidate）：
    不清空 _last_success，SSE 广播 scheduler_error
    前端依然可从 DB 或内存读取旧数据
```

### 3.4 结束流程

```
进程退出（Ctrl+C / 信号）
    ↓
atexit → _scheduler.shutdown()
    → APScheduler.shutdown(wait=False)
    → asyncio loop.stop()
    → daemon 线程随主进程自动消亡
```

---

## 第四章：数据处理与前端实时获取

### 4.1 采集完成后数据写向三处

```
pipeline.align_and_save()
    ├── 新条目 → DB INSERT CanonicalItemModel
    ├── 已有条目 → DB UPDATE crawled_at（+ hotness_score）
    ↓ await db_session.flush() 成功后（P1-A 强一致性）
    └── memory_cache.news_flash_cache.appendleft(item_dict)
        （flush 失败则 rollback，不写内存）
```

### 4.2 前端数据获取：两条并行路径

| 路径       | 接口                   | 数据来源     | 延迟     |
|------------|------------------------|--------------|---------|
| NewsFlash  | `GET /api/v1/newsflash` | 内存 deque  | **< 1ms** |
| 热榜排行   | `GET /api/v1/items?sort=heat` | SQLite DB | 几十ms |

### 4.3 SSE 实时推送机制

**后端（`/stream` 端点）：**
```python
# 每个 SSE 客户端对应一个 Queue(maxsize=200)
client_q: queue.Queue = queue.Queue(maxsize=200)
_sse_clients.append(client_q)

# 事件分级投递
if event_type in _HIGH_PRIORITY_EVENTS:  # scheduler_done / connected
    q.put_nowait(event)   # 必须投递，Full 才踢客户端
else:
    if not q.full():      # 低优先级满了直接丢弃，不踢客户端
        q.put_nowait(event)

# 30s keep-alive（防止代理超时断连）
yield ": keep-alive\n\n"
```

**前端（EventSource 消费）：**
```typescript
const eventSource = new EventSource(`http://localhost:5001/stream`);

eventSource.onmessage = (event) => {
    const data = JSON.parse(event.data);

    // 1. Console 面板实时滚动日志
    addLog({ level: 'OK', domain: data.domain, msg: `采集完成 ${data.items_count} 条` });

    // 2. 域活跃度滑动窗口（8个周期）
    if (data.event === 'scheduler_done') {
        setDomainActivity(prev => ({
            ...prev,
            [domain]: [...prev[domain].slice(1), data.items_count]  // 追加最新
        }));
    }

    // 3. 防抖 800ms → 触发 HTTP 拉取
    fetchNewsFlash(activeTab);   // GET /newsflash → 内存 deque → 快报面板
    fetchData(activeTab);        // GET /items → SQLite → 热榜面板
};

// 自动重连（指数退避 1s → 最大 15s）
eventSource.onerror = () => {
    sseRetryDelay.current = Math.min(sseRetryDelay.current * 2, 15000);
    setTimeout(connectSSE, sseRetryDelay.current);
};
```

### 4.4 完整端到端数据流

```
APScheduler 定时触发
        ↓
Adapter.fetch_*() → raw_data
        ↓
AlignmentPipeline.align_and_save()
        ├── DB flush()      ← P1-A 强一致性
        └── memory_cache.appendleft()
        ↓
SSE _broadcast("scheduler_done")
        ↓
前端 EventSource.onmessage
        ├── Console 实时日志
        ├── 域活跃度图表实时更新
        ├── 调度器状态面板更新
        └── 防抖 → 双路 HTTP 拉取
                ├── /newsflash → 内存 → 快报面板 (< 1ms)
                └── /items     → SQLite → 热榜面板
```

---

## 附录：关键设计决策

| 决策 | 原因 |
|------|------|
| source_id 作为路由唯一锚点 | 三层（注册/采集/对齐）无需额外配置，靠命名约定自动协作 |
| DB flush 成功后才写内存 | 防止 DB 回滚导致内存脏数据（P1-A） |
| Queue(maxsize=200) + 分级投递 | 高优先级事件（scheduler_done）必达，低优先级背压时丢弃而非踢客户端（P1-B） |
| stale-while-revalidate | 采集失败不清空历史缓存，保证前端始终有数据可看 |
| /newsflash 纯内存接口 | 热搜/快报更新频繁，0 DB 查询极速响应 |
| Yahoo Finance 串行+sleep | 规避 API 限速 429 |
| 延迟启动调度器 | 避免 Flask debug 多进程模式重复启动（`@before_request` 首次触发） |
