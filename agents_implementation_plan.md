# 端到端智能体预测架构闭环实施方案
**整合目标**: 融合 `BettaFish`(微舆)、`MiroFish`(预测沙盒) 和 `OpenClaw`(个人AI核心) 三大开源项目核心技术，在当前 `backend/agents` 模块下构建一条完全自动化、端到端 (End-to-End) 的多智能体情报预测流水线。

---

## 架构核心要素分析 (基于三大开源项目)

### 1. 整体智能体架构设计
*   **网关控制 (Gateway)**: 借鉴 OpenClaw 控制面，利用 FastAPI 的 WebSocket 和 SSE 构建双向通信网关，所有的客户端终端获取实时状态。
*   **Pi-Agent 运行时分级编排**:
    *   **主控 Agent (Gateway/Orchestrator)**: 负责心跳维护、任务调度、子 Agent 生命周期管理。
    *   **领域子 Agent (Subagents)**: QueryAgent, MediaAgent, InsightAgent, ReportAgent 作为并行的 RPC/Worker 运行，受限于主控的并发树与深度限制。

### 2. 心跳与调度任务技术 (Heartbeat)
*   借鉴 OpenClaw 的 `cron` / `service` 背景任务调度：
    *   实现一个长驻 `Background Task Scheduler`，负责按规律 (比如每6小时) 自动触发全景扫描。
    *   具备防挂死 (Loop Detection)、任务状态防重入机制。

### 3. 上下文与记忆管理
*   **短期上下文引擎 (Context Engine)**: 维持正在执行中会话的生命周期。提供分块与修复机制，处理多智能体 Forum 协作时产生的长尾对话与幻听错误。
*   **长效记忆池 (SQLite-Vec / Zep)**: 单个分析结果的长期沉淀 (结合 BettaFish 的关系日志，模拟 OpenClaw 的 Sqlite-vec Memory Search，辅以 Zep 的外部时序节点存储)，使下一次的同题分析拥有*先验认知*。

### 4. 数据获取与对齐管道 (Data Acquisition & Alignment)
*   **感知获取**: `TopicExtractor` 主题侦查 -> `SocialCrawler` 抓取 (爬虫阶段由任务调度器触发)。
*   **标准化对齐**: `MediaCrawlerDB`  facade 执行映射，将跨平台异构数据洗为 `canonical_items` 存入。

### 5. 渠道推送分发 (Channel Tech)
*   分析结束后产出的 Markdown 报告或者预测预警，借助 OpenClaw 风格的多渠道 webhook 发往宿主指定渠道（如 Telegram, 内线通知）。

---

## E2E 工作流水线设计 (The Core Loop)

流水线将从传统的被动 HTTP API 触发，升级为**事件/心跳自动驱动**的闭环。

```mermaid
graph TD
    Cron[调度与心跳引擎<br>(OpenClaw Scheduler)] -->|1. 定时触发| ACQ[感知监控层<br>(TopicExtractor+Crawler)]
    ACQ -->|2. 元数据入库| ALIGN[数据对齐与度量计算<br>(MediaCrawlerDB + Hotness)]
    ALIGN -->|阈值判定| EVENT[事件与舆情分析<br>- Query/Insight/Media<br>- 情感计算分析]
    EVENT <-->|3. 多轮反思/Forum协作| F[Forum 共享脑区<br>Context Engine]
    EVENT -->|4. 主题确立/快报| SELECT[智能选题与快报<br>(ReportAgent)]
    SELECT -->|5. 本体提纯| GRAPH[图谱重建<br>(Zep Ontology)]
    GRAPH -->|6. 沙盒加载| SIM[OASIS 多智能体双平台仿真<br>预测推演 144 轮]
    SIM -->|7. 局势研判| PREDICT[决断预判<br>(PredictionReportAgent)]
    PREDICT -->|8. 写成长时记忆| MEM[Sqlite-Vec/Zep 长期记忆]
    PREDICT -->|9. 多渠道推送| CH[Channel Gateway 分发]
```

---

## 分阶段执行方案 (Execution Plan)

目前我们已经在 `backend/agents` 下完成了 BettaFish API 路由的搭建以及 FastAPI 的初始化，下一步是将其串联和升级。

### **Phase 1: 基础设施建设 - 心跳引擎与记忆库引入**
*   **组件开发**:
    *   `backend/agents/scheduler.py`: 引入 `APScheduler` 或 asyncio 任务队列，模拟 OpenClaw 的 background cron 触发机制。
    *   `backend/agents/memory.py`: 构建与长期图谱交火的中间记忆区接口。
*   **目标验证**: 启动服务后，心跳系统能够独立运行，并定时发起 Dummy 探测任务。

### **Phase 2: 搭建 E2E 主控管线 (Orchestrator)**
*   **组件开发**:
    *   `backend/agents/pipeline/e2e_coordinator.py`: 这是全图的核心。它侦听前序执行结果的信号，把现有的 BettaFish Pipeline (P0-P3, 分析) 的输出结果作为输入，直接自动传送给 MiroFish Pipeline (P4-P5, 重构图谱与沙盒演练)。
*   **事件打通**:
    *   实现当舆情热度 `HotnessCalculator` 的结果超出阈值时，自动决定当前话题作为核心选题。

### **Phase 3: 渠道融合与 Gateway 完善**
*   **组件开发**:
    *   丰富 FastAPI Websocket 网关层，向前端 UI 实况推送 E2E 进度（包括子智能体现正处理的任务、Zep 图谱更新数）。
    *   实现最终预测结果（Prediction Report）的外部 Webhook/File 落盘。

### **Phase 4: 全链路系统集成与健壮性回归**
*   **调优与错误截获**: 利用上下文修复策略，容阻中间 API (Zep, 搜索引擎) 的调用失败自动回退。
*   进行模拟触发测试：从“爬取”一键走到“最终预测书”。
