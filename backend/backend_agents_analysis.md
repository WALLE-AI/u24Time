# Backend Agents (`backend/agents`) 技术框架深度分析报告

## 一、模块核心架构与技术栈

`backend/agents` 目录实现了 U24Time 的核心多智能体流（BettaFish + MiroFish），它负责话题挖掘、数据分析、情报图谱构建和事件走势预测。此系统受到 `OpenClaw` 架构思想的深刻影响，采用了强状态机管理和可插拔上下文设计。

### 1.1 关键基础设施 (Infrastructure)
1. **上下文管理 (`context_engine.py`)**：
   - 实现了类似于 `Token Budget` 的硬约束。具备四级内存压实降级策略：
     - *Level 1*: `_repair_tool_pairs` / `_strip_detail` 无损裁剪。
     - *Level 2*: 分块局部摘要 (`_summarize_chunks`)。
     - *Level 3*: 渐进式强制截断合并摘要。
     - *Level 4*: 多阶段历史合并。
2. **长效记忆注入 (`memory.py`)**：
   - 采用多模态存储: `SQLite` 三表架构 (原生文本 + `chunks_vec` 向量 + `chunks_fts` FTS5全文倒排)。
   - 实现混合检索流水线: 向量检索与 BM25 加权合并，并引入了 MMR (Maximal Marginal Relevance) 消除冗余，附带 `_apply_temporal_decay` 时序半衰期逻辑。
3. **单例状态注册表 (`subagent_registry.py`)**：
   - 管理流水线上各种子智能体实例的状态跃迁 (`PENDING -> RUNNING -> COMPLETED/FAILED/KILLED -> ARCHIVED`)。
   - 实现指数退避重试 (Exponential Backoff) 及 `Sweeper` 清理任务防僵尸。
4. **实时推送网关 (`channel_dispatcher.py`)**：
   - 统一了输出出口：SSE 流（Server-Sent Events）, WebSocket, 及外部 Webhook。
   - 设置了 `HeartbeatPolicy` 及 `InboundDebouncePolicy` 以对冲 UI 更新频率，避免心跳（Ping）干扰正常内容。
5. **任务调度 (`scheduler.py`)**：
   - 基于 `APScheduler` 的后台作业管理器，主要负责发起后台异步推演作业、执行容错重试和触发内存扫描 (sweeper)。

### 1.2 流水线编排 (Pipelines)
1. **主控器 (`e2e_coordinator.py`)**: 将孤立的分析引擎串联为 8 大步骤 (Phase 0 ~ Phase 7)。从爬虫提取(Phase 0)、对齐(Phase 1)、`Query/Insight/Media` 三端并行分析(Phase 2)到最终的宏观预测与入库(Phase 7)。
2. **BettaFish Pipeline (`phase1_bettafish` / `bettafish_pipeline.py`)**: 负责情报收集阶段（爬取、对齐、并发送情感分析，形成初始知识簇）。
3. **MiroFish Pipeline (`phase2_mirofish` / `mirofish_pipeline.py`)**: 负责基于前期总结构建 Zep Cloud 时序知识图谱，并借助 OASIS 进行抽象多轮事件仿真。

---

## 二、当前存在的技术问题/瓶颈分析

尽管架构精巧，但在高并发场景及大规模语料吞吐下仍存隐患：

1. **SQLite 极速写入的锁冲突 (PendingRollbackError)**：
   - 尽管系统已启动了 `WAL` 查询模式，但 E2E Pipeline （如跨节点频繁写入 `CanonicalItem` 和修改 SubagentRecord 时）因为使用同步与异步混合范式极易出现 `database is locked`。在单连接挂起或回滚异常未被正常捕获时，会导致当前异步 `AsyncSession` 无限报出 `PendingRollbackError`，致使 SSE 流彻底挂死。
   - *建议:* 生产环境应严格更换为 PostgreSQL 驱动 (`asyncpg`)。

2. **异步主循环中潜在的同步阻塞**：
   - 在图谱构建 (`GraphBuilder`)、甚至部分数据清洗阶段可能引入了阻塞 IO 抑或是过度密集性的 CPU 调用（例如 `SentimentAnalyzer` 本地分词）。这可能会暂时堵塞 ASGI (Uvicorn) 事件循环，导致 SSE 缓冲推迟与前端的心跳超时脱节。

3. **内存压实带来的巨额 API 消耗 (LLM Cost)**：
   - `AgentContext` 配置的四级压实策略高度依赖于 LLM 触发器 (`_generate_summary` / `_llm_summarize`)。在 `Phase 2` 的 Forum 轮转期，大量 Agent Messages 涌入可能引发极其频繁的 API calls 用于缩减历史上下文尺寸，造成高延迟并放大 token 消费。
   - *建议:* 调整 `COMPACT_TRIGGER_RATIO` (0.85)，并在轻量级交互中只截断非关键信息。

4. **孤儿 SSE 队列引发内存泄漏**：
   - `ChannelDispatcher._sse_queues` 的键按 `run_id` 自动插入。当客户端中途断连却没有触发明确的 shutdown 或是抛出异常后生命周期处理不当，相应的 `asyncio.Queue` 未被 `remove_sse_queue` 回收，久而久之会产生幽灵占用（Zombie allocations）。
   - *建议:* 在队列消费层加上严格的超时机制 / TTL，并与 FastAPI 的 `BackgroundTasks` 深度绑定。

---

## 四、工具化与可插拔扩展 (Tool Ecosystem)

系统引入了一套高度结构化的工具化框架，灵感来源于 `OpenClaw`，用于解耦 Agent 的逻辑与具体的业务操作（如搜索、发信、文件读写）。

### 4.1 核心基座 (`tools/base.py`)
- **Tool 基类**: 自备 `Pydantic` 参数验证、自动注册机制 (`_registry`)、以及 `to_openai_function` 元数据生成。
- **ToolContext**: 提供了标准化的执行环境，封装了 `session_id`、上传文件访问 (`get_files`)、数据库连接及中止信号。
- **自动注册**: 利用 `__init_subclass__` 钩子，任何继承 `Tool` 的类在定义时会自动进入全局注册表。

### 4.2 鉴权与安全管线 (`tools/policy.py`)
- **四级拦截策略**: 
    - `WorkspaceGuardPolicy`: 拦截 `..` 符号及绝对路径逃逸，确保 Agent 只能在指定沙箱内操作。
    - `LoopDetectionPolicy`: 侦测重复失败的参数调用，自动熔断故障工具，防止死循环导致 API 费用暴涨。

### 4.3 Agent 对工具的两种驱动模式
1.  **静态/直接调用 (Static Implementation)**:
    - 如 `TopicExtractor` 中直接实例化 `WebFetchTool()` 并调用 `execute`。这是目前的稳健模式，逻辑确定性强。
2.  **动态/函数调用 (Dynamic Function Calling)**:
    - 借由 `to_openai_function` 生成的 JSON Schema，Agent 可以将工具集注册给 LLM，由 LLM 根据 User Query 决定调用的工具及其参数。这为未来的 `PlanMode` 和更通用的智能体奠定了基础。

### 4.4 扩展能力集 (Ported from OpenClaw)
目前已完成 Phase 1 移植的工具集包含：
- **Social (`social.py`)**: Discord, Slack, Telegram, WhatsApp, Feishu (一站式社交分发)。
- **Web (`web_search.py` / `web_fetch.py`)**: 深度解析网页 Markdown，支持 Jina Reader 集成。
- **Memory & System**: 针对 Zep 图谱和 OS 系统的底层交互工具。

---

## 五、未来演进建议

1.  **将 Hardcoded 爬虫工具化**: 目前 `QueryAgent` 和 `MediaCrawlerDB` 中的搜索逻辑仍有部分是通过 `httpx` 硬编码实现的，应逐步迁移至 `WebSearchTool` 以复用 `LoopGuard` 和 `WorkspaceGuard` 等安全策略。
2.  **增强 Forum 机制的异步非阻塞性**: 在 `Phase 2` 的并行分析中，引入 `FollowupRunner` 对 Tool 回调进行消峰填谷，避免单点阻塞推迟整个 E2E 响应。
3.  **实现 Dynamic Tool Loader**: 支持从 `backend/agents/tools/` 动态扫描并挂载新工具，无需重启核心 E2E 系统即可热插拔新解析器（如 Lobster, Diffs 等）。

---

## 三、配置系统说明 (`config.py` & `agents/config.py`)

系统基于 `pydantic-settings` 实现了环境驱动的分层加载策略。

### 3.1 核心全局配置 (`backend/config.py`)
定义了系统级的 DB（主推 PostgreSQL，降级回 SQLite `u24time.db`），以及用于原始情报来源的各类爬虫 API (如 NASA FIRMS, ACLED, OpenSky)。
- `LLM_MODEL_NAME` / `LLM_API_KEY`: 分类和翻译辅助。
- `RSS_CONCURRENCY` / `HTTP_TIMEOUT`: 控制抓取引擎并行度。
- `NEWSNOW_BASE_URL`: 聚合热词源。

### 3.2 Agents 领域配置 (`backend/agents/config.py`)
专门供 `Subagent` 工作流消费。其配置类 `AgentsSettings` 利用 `__getattr__` 降级读取全局 settings。
- `AGENTS_PORT`: **5002** (默认子应用独立起端口)。
- `ZEP_API_KEY`: 知识图谱底层依赖服务。
- `OASIS_MAX_ROUNDS` (144) / `OASIS_MINUTES_PER_ROUND` (20)：精细管理 `Phase 6` 中的环境步长。
- `SENTIMENT_CONFIDENCE_THRESHOLD`: 情感分类最低阈值 (低于不处理或报 Neutral)。
- `SEARCH_API_PROVIDER`: `tavily` / `serpapi` 外部增强搜索支持供 Query Agent 补充增量信息。
