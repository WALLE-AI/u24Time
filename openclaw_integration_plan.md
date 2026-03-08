# OpenClaw 深度分析与端到端智能体架构执行方案

## 1. OpenClaw 核心架构与技术栈深度分析

通过对 `opensource/openclaw` 源码（特别是 `src/` 与 `AGENTS.md`）的分析，提炼出其作为个人 AI 助手的五大核心底层技术：

### 1.1 整体智能体架构设计 (Agent Architecture)
- **Gateway WS 控制面 (Control Plane)**：OpenClaw 采用本地优先（Local-first）的 Gateway 架构，通过 WebSocket (`ws://127.0.0.1:18789`) 连接所有的客户端终端（macOS/iOS/Web）、工具组件和事件网关。
- **Pi Agent Runtime (RPC 模式)**：智能体核心运行在 Pi 引擎上。它解耦了执行层与控制层。
- **Subagent 注册表与并发机制**：`src/agents/subagent-registry` 实现了子智能体的衍生（Spawn）、生命周期管理、深度限制控制，支持复杂任务的 Agent-to-Agent（通过 `sessions_send`）协作调度。

### 1.2 上下文管理 (Context Management)
- **Context Engine**：`src/context-engine` 与 `pi-embedded-runner` 共同维持会话生命周期。
- **块分块与修复机制**：具备 `session-transcript-repair` 功能。由于 LLM 输出可能中断或越界，机制会自动校验 Markdown 标签、修复中断的代码块，并通过 Compaction（上下文压实）限制滑动窗口内的 Token 消耗。
- **动静隔离**：区分主 System Prompt (如 `AGENTS.md`, `SOUL.md`) 与动态会话上下文，实施严格的优先级截断保护。

### 1.3 记忆管理 (Memory Management)
- **SQLite-Vec 向量底层**：在 `src/memory/` 下，OpenClaw 没有依赖重型外部向量库，而是大量使用了轻量级扩展 `sqlite-vec.ts`。
- **混合检索 (Hybrid Search)**：提供了基于 BM25 和多模型（OpenAI/Gemini/Ollama/Mistral/Voyage 模型自动降级回退）Embedding 的内存搜索，支持自动定时将日常记录向量化，供 Agent `memory_search` 调用。

### 1.4 心跳与调度任务技术 (Heartbeat & Cron)
- **精准的心跳策略**：在 `src/cron/heartbeat-policy.ts` 和 `service/` 目录下，包含了一整套 `Background Scheduler` 服务。
- **任务防重与防呆追踪**：控制主循环、单次执行任务清理 (`session-reaper`)，并防止高频唤醒，确保长待机设备的电池健康及事件响应（如自动分析、准点播报）。

### 1.5 渠道适配技术 (Channel Technology)
- **多渠道收件箱 (Multi-inbox Pattern)**：通过 `src/channels/` 中的适配器，无缝桥接了 Telegram, WhatsApp, Slack, Discord 等 22 种协议。
- **权限与沙盒白名单隔离**：为主会话提供直接宿主工具访问权限；对来自公开频道的请求，在容器沙盒中（Docker）执行或降级（Non-main session），实施严格的命令鉴权。

---

## 2. 与现有 Backend (U24Time) 模块对比

| 能力项 | OpenClaw 方案 | 现有 U24Time Backend 方案 (BettaFish + MiroFish) | 优化/结合点 |
| :--- | :--- | :--- | :--- |
| **通信与分发** | 强大的 WS Gateway，灵活的跨平台 Channel 路由。 | 基于 FastAPI 构建 HTTP 端点与 SSE 单向流，以 Web 前端驱动为主。 | **引入 Gateway 思想**，将 FastAPI SSE 升级或配合双向通道，支持多协议触达。 |
| **图谱与记忆** | 轻量 `sqlite-vec` + Chunk 历史记忆搜索。 | **Zep Cloud**，维护带时序边的高级异构知识图谱。 | 保留 Zep 的复杂图谱分析能力，参考 OpenClaw 针对高频流水数据的本地防抖压缩设计。 |
| **编排引擎** | Pi RPC 动态调用，子智能体分权。 | **Pipeline 顺序流 + 论坛 (ForumHost) 事件微调**，利用 QueryAgent, InsightAgent 的 Reflect 机制流转。 | 将 Pipeline 升级为类 Subagent-registry 机制，支持动态扩缩并发查询。 |
| **社会仿真推演** | 不支持。 | 强大的 **OASIS 沙盒仿真** (Agent 并行 144 轮社会演化演练)。 | 现有系统强项：利用多智能体图谱做未来预测。 |

---

## 3. 端到端 (E2E) 智能体架构流程设计

我们将基于现有 U24Time Backend 基础设施，结合 OpenClaw 的生命周期、记忆与心跳技术，构建一个如下的**完全自动化端到端情报预测架构**：

### 核心阶段链路：
1. **感知与数据抓取层 (Data Acquisition & Alignment)**
   - **监控触发 / Cron 心跳**：继承 OpenClaw 的 `Heartbeat API` 定期定时唤醒。
   - **两阶段爬虫**：`TopicExtractor` 获取全网话题 -> `SocialCrawler / MediaCrawlerDB` 执行 7平台 × 14表 的元数据对齐落地。

2. **多维自动化分析层 (Automated Analysis)**
   - **主题与关键字解析**：基于 `InsightAgent` 提供全局视图降维分类。
   - **批量情感分类**：运用 `SentimentAnalyzer` (22种语言预热的轻量化 NLP 模型) 为海量舆论添加“喜爱度/愤怒值”标签。
   - **事件分析与深挖**：触发 `QueryAgent/MediaEngine`进行二次外部全网反思检索 (最多 2 轮反思)，补全缺失背景。

3. **选题与智能派发 (Topic Selection)**
   - **热度算法与决策树**：应用对齐组件中的加权热度算法（Like*1 + Comment*5 + Share*10）。当某一事件热度或情感波动阈值触及预警，由 **Host Agent** 发起选题锁定。
   - **舆情快报生成**：`ReportAgent` 同步产出初始报告，并推送至各类 Channel (模拟 OpenClaw 的通知投递)。

4. **因果建构与社会仿真 (Graph Reconstruction & Simulation)**
   - **本体重构**：`OntologyGenerator` 根据分析报告自动抽取 10实体+10关系 网络。
   - **时间图谱**：同步入库 Zep 进行时序知识图谱结构化存储。
   - **沙盒推演**：下发至 OASIS 双平台（模拟 Twitter、Reddit 认知战）运行多轮微观虚拟仿真演化，预测舆情走向 144 级别节点的状态变迁。

5. **决断预判 (Prediction Execution)**
   - `PredictionReportAgent` 在接收到仿真末态后，输出“事件演化终极研判”，并存入长效记忆（模拟 OpenClaw 的 `memory-search`），为下次周期性任务提供先验背景（Prior Context）。

---

## 4. 后续执行方案 (Execution Plan)

> **目标**：在 `backend` 中贯通此 E2E 流程，并产出一个统筹大管家（`Orchestrator Scheduler`）。

*   **Step 1: 整合心跳与调度中心 (Heartbeat & Cron)**
    *   借用 OpenClaw `service` 思想，在 `backend/agents` 初始化时注册一个异步的 `Background Task Scheduler`，实现自动监控循环（间隔 1-6 小时触发全网抓取检测）。
*   **Step 2: 建立 E2E 统一长管道 (Pipeline Coordinator)**
    *   在 `backend/agents/pipeline` 下创建 `EndToEndPipeline`，以线性+并行协程方式，打通 BettaFish 管道 (P0-P3) 直接调用 MiroFish 管道 (P4-P5) 的无缝衔接。将 BettaFish 的分析输出自动变现为 MiroFish 的输入材料。
*   **Step 3: 实现 Context & Memory 连接器**
    *   引入长期记忆状态表，使每一次推演完毕的报告通过向量数据库检索，确保下一次仿真能够基于类似事件的历史数据进行偏置。
*   **Step 4: 渠道广播模块 (Channel Notification)**
    *   基于 `httpx` 构建基础通道模块（类似 Telegram/Web hooks），通过 FastAPI 的 Background Tasks 将预报预测单 (Markdown) 发送至指定终端。
