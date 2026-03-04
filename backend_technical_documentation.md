# U24Time Backend 技术架构文档

本文档对 `U24Time` 项目的后端进行深度剖析，提取系统架构、模块功能、核心技术栈以及对外的接口服务规范。

## 1. 系统概述

U24Time Backend 是一个基于 Python 构建的高性能数据采集与处理中枢体系。它通过灵活的后台调度策略（分层 TTL 刷新）和并发采集引擎，持续不断地从包含 RSS、公开 API、特定第三方集成平台（如 HuggingFace、GitHub、NASA，以及各类科研、经济、地缘灾害数据源）中获取数据。随后，系统利用标准化管道（Data Alignment Pipeline），将来自不同平台的异构格式进行抽取、清洗、去重与标准化，输出为结构统一的 `CanonicalItem` 情报数据，持久化到数据库中供前端消费，或通过 SSE 提供实时推送。

## 2. 技术架构图

```mermaid
graph TD
    %% Define components
    subgraph Frontend / Clients
        Client[Web Client]
        SSE_Receiver[SSE Listener]
    end

    subgraph API Gateway (main.py)
        Flask_App[Flask Web App]
        SSE_Stream[SSE Endpoint]
    end

    subgraph Scheduler (scheduler.py)
        DataScheduler[DataScheduler<br/>TTL / Layered Config]
    end

    subgraph Crawler Engine (crawler_engine/)
        Engine[CrawlerEngine]
        RSS[RSS Fetcher]
        Adapters[API Adapters<br/>NASA / GDELT / GitHub / etc.]
        Social[Social Scrapers<br/>Playwright / Custom Base]
    end

    subgraph Alignment & Processing (data_alignment/)
        Pipeline[AlignmentPipeline]
        Normalizers[Domain Normalizers<br/>Tech, Academic, Economy, Geo, etc.]
        Deduplicator[Deduplicator<br/>Hash / ID validation]
        LLM[LLM Client<br/>Context / Sub-domain Classifier]
    end

    subgraph Database (db/)
        ORM[SQLAlchemy ORM]
        DB[(SQLite / PostgreSQL)]
    end

    %% Define connections
    Client -->|HTTP Requests| Flask_App
    Flask_App -->|Trigger / Config| DataScheduler
    Flask_App -->|Manual trigger| Engine
    Flask_App --> SSE_Stream
    SSE_Stream -.->|Server-Sent Events| SSE_Receiver

    DataScheduler -->|Time-based trigger| Engine
    
    Engine --> RSS
    Engine --> Adapters
    Engine --> Social

    RSS --> Pipeline
    Adapters --> Pipeline
    Social --> Pipeline

    Pipeline --> Deduplicator
    Deduplicator --> Normalizers
    Normalizers -.->|Enhance via AI| LLM
    Normalizers --> ORM
    
    ORM --> DB
    
    %% Async state reports
    Pipeline -.->|Progress events| DataScheduler
    Engine -.->|Task events| DataScheduler
    DataScheduler -.->|Broadcast| SSE_Stream
```

## 3. 核心模块与关键技术

### 3.1 接入层与 API ( `main.py` )
- **技术栈**：Flask, Flask-CORS, queue.
- **核心逻辑**：提供跨域的 HTTP RESTful 接口进行健康监测与任务管理。系统巧妙地结合了传统的 Flask 同步接口，以及后台基于 `asyncio` 和独立子线程运行的事件循环（通过 `_run_async` 包装器调度异步并发的引擎和协程任务）。
- **SSE 推送**：使用 Python 原生生成器配合 `text/event-stream` Context，向所有接入监控中心的前端实时传递（broadcast）抓取进度、错误日志和状态迁移情况。

### 3.2 任务调度系统 ( `scheduler.py` )
- **技术栈**：Python `asyncio`, 后台常驻事件循环。
- **核心逻辑**：`DataScheduler` 借鉴了 WorldMonitor 的分层 TTL 策略。按数据新鲜度依赖区分：
  - **实时层 (1~5 mins)**：加密货币行情、AI 服务状态等。
  - **新闻级别 (15 mins)**：RSS。
  - **事件/威胁 (30 mins)**：NASA 灾害火点、NVD 漏洞 (CVE)、GDELT 核心地缘事件。
  - **宏观/长效 (60~360 mins)**：科技短评、学术趋势论文（Arxiv, HF papers）、经济周期数据。

### 3.3 采集引擎层 ( `crawler_engine/` )
- **技术栈**：`aiohttp`, `feedparser`, `asyncio.gather`.
- **核心逻辑**：`engine.py` 内含核心调度网关 `CrawlerEngine`。将任务分为三类：
  - `run_rss`: 采用并发协程处理大规模 RSS feeds 拉取。
  - `run_api` & `run_custom_adapter`: 调用 `api_adapters/`（包含 GithubAdapter, NASAFIRMSAdapter 等）。
  - `run_hotsearch`: 专属抓取各家主流 NewsNow 级别聚合热搜榜。
- 所有执行结果都会作为统一抽象的 `RawData` 被送往下游 Pipeline。

### 3.4 数据对齐与清洗管道 ( `data_alignment/` )
- **技术栈**：面向对象设计模式、Pydantic (`schema.py` 未显式标出，但有 CanonicalItem 规约）、LLM API (智能归类辅助)。
- **核心逻辑**：
  - `AlignmentPipeline`：数据必经之路，统一接收多源 RAW JSON。
  - **分发机制 (`Normalizers`)**：根据数据的 `source_id` 前缀路由到各自领域的专门处理类（`academic_normalizer.py`, `tech_normalizer.py`, `economy_normalizer.py` 等）。
  - 各级 Normalizer 负责按规范提炼出标题、内容、来源、严重程度、经纬度坐标（Geo 事件中），并由 `utils/llm_client.py` 提供分类打标。
  - `Deduplicator` 提供 URL + Hash 级别的基础去重。

### 3.5 数据持久层 ( `db/` )
- **技术栈**：SQLAlchemy (`Mapped`, `mapped_column`, ORM).
- **核心逻辑**：兼顾 SQLite 灵活性和 PostgreSQL 并发优势（通过 pydantic-settings 进行 `config.py` 配置切换）。
  - `CanonicalItemModel`：对齐清洗后的情报唯一范式（入库最终表）。具有多种性能查询索引（如按 `domain`, `published_at` 等）。
  - `RawItemModel`：保留抓取原始报文（RAW_JSON），便于出现解析 Bug 时重新离线 replay 对齐。
  - `CrawlTaskModel` / `DataSourceHealthModel`：全链路监控指标和数据源状态打点。

---

## 4. API 接口服务清单

| 方法 | Endpoint | 参数 (Body / Query) | 说明 |
|------|----------|---------------------|------|
| **GET** | `/health` | 无 | 检测 Flask 服务本机的响应心跳和版本。 |
| **GET** | `/api/v1/stream` | 无 | SSE 端点；监听来自后端的调度日志和数据流推送。 |
| **GET** | `/api/v1/sources` | 无 | 获取系统内建所有注册的数据源清单及其最新监控态。 |
| **POST** | `/api/v1/sources/health` | 无 | 触发系统执行后台异步的健康度全检操作。 |
| **GET** | `/api/v1/scheduler/status` | 无 | 获取调度器引擎当前排队的缓存态及各个 source_id 离下次抓取的等待时间（秒）。 |
| **POST** | `/api/v1/scheduler/trigger/<source_id>` | `<source_id>` in path | 手动唤起特定 `source_id` 的临时立即抓取（越过 TTL）。 |
| **POST** | `/api/v1/scheduler/trigger_all` | 无 | 全量并发拉取所有数据。**注意**：可能极度消耗吞吐率。 |
| **POST** | `/api/v1/crawl/rss` | `category` (opt), `feed_ids` (opt) | 触发通用 RSS 抓取，并交由 Pipeline 处理对齐。 |
| **POST** | `/api/v1/crawl/api` | `source_id` | 指定触发具体 API 类型（如 `geo.gdelt`）拉取与对齐。 |
| **POST** | `/api/v1/crawl/hotsearch` | `source_ids` (opt) | 触发 BettaFish NewsNow 聚合热搜 API 的抓取并对齐。 |
| **GET** | `/api/v1/crawl/tasks/<task_id>` | `<task_id>` in path | 轮询某特定手工抓取任务的对齐和写入数统计。 |
