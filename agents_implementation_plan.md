# 端对端多智能体情报预测架构方案
> 基于 BettaFish + MiroFish + OpenClaw 三方项目源码深度分析（源码级）
> 更新时间: 2026-03-08

---

## 一、三大项目核心技术地图

### 1.1 BettaFish — 舆情分析管线核心技术

| 模块 | 核心文件 | 关键实现细节 |
| :--- | :--- | :--- |
| **ForumEngine** | `monitor.py` / `llm_host.py` | `LogMonitor` 1秒轮询 3 个 `.log` 文件；每采集到 **5 条** Agent 发言触发 `ForumHost`(Qwen-235B 模型) 引导总结；`threading.Lock` 保证并发安全写入 `forum.log` |
| **InsightEngine** | `agent.py` (40KB) | `search_hot_content/search_topic_globally/get_comments_for_topic` 等 5 大工具；UNION ALL 跨 15 张表；加权热度: **Like×1 + Comment×5 + Share×10 + View×0.1** |
| **QueryEngine** | `nodes/` | SearchNode → FormattingNode → **ReflectionSummaryNode**(max 2轮) → FirstSummaryNode → SummaryNode；`max_search_results=15` |
| **SentimentAnalyzer** | `SentimentAnalysisModel/` | 默认 `tabularisai/multilingual-sentiment-analysis`(22语言，5级分类：0非常负面～4非常正面)；批量输出情感分布/置信度 |
| **ReportEngine** | `ReportEngine/` | 模板选择 → 布局设计 → 字数预算 → 逐章生成 → JSON校验 → 装订 → HTML/PDF/MD |

### 1.2 MiroFish — 图谱仿真预测核心技术

| 模块 | 关键实现细节 |
| :--- | :--- |
| **OntologyGenerator** | temperature=0.3；精确 10 实体 + 6-10 关系；最后 2 个必须是 Person/Organization；禁用 Zep 保留字 |
| **GraphBuilderService** | Zep Cloud；chunk_size=500 overlap=50；batch_size=3；轮询 episode.processed (超时 600s) |
| **SimulationRunner** | OASIS 双平台并行 (Twitter + Reddit)；默认 **144 轮**（72虚拟小时）；Agent行为实时写入图谱时序边 |
| **ReportAgent** | 99KB 核心文件；图谱查询 + 与模拟 Agent 深度对话 + 生成预测报告 |
| **ZepTools** | 实体检索/关系路径查询/时序事实查询/Agent记忆读取 |

### 1.3 OpenClaw — 智能体运行时核心技术

| 技术域 | 核心文件 | 关键实现细节 |
| :--- | :--- | :--- |
| **ContextEngine (接口)** | `context-engine/types.ts` | `bootstrap/ingest/ingestBatch/afterTurn/assemble/compact/prepareSubagentSpawn/onSubagentEnded`；`isHeartbeat` 标志区分心跳与常规 Turn |
| **记忆管理** | `memory/manager.ts` | `MemoryIndexManager`：SQLite + sqlite-vec + BM25 FTS 混合检索；多嵌入模型自动 fallback；`search()` 实现 Vector+Keyword+MMR+时序衰减 |
| **子智能体注册表** | `agents/subagent-registry.ts` | 完整生命周期；指数退避重试 (1s→2s→4s→8s)；Sweeper 每 60s 清档；`archiveAfterMinutes` 控制超时；孤儿检测/清理 |
| **心跳调度** | `cron/heartbeat-policy.ts` | `shouldSkipHeartbeatOnlyDelivery()` 抑制纯心跳输出；`shouldEnqueueCronMainSummary()` 控制任务汇报 |
| **渠道网关** | `channels/` | `registry.ts` 统一注册；`dock.ts` 双向调度；`draft-stream-loop.ts` SSE 流式；`inbound-debounce-policy.ts` 防抖；支持 Telegram/Slack/Discord 等 |

---

## 二、E2E 整合架构设计

### 2.1 五层架构模型

```
┌──────────────────────────────────────────────────────────────┐
│  LAYER 5: 渠道网关层 (Channel Gateway)                        │
│  FastAPI WS + SSE 双向网关 + Webhook 外部推送 + 前端 UI 推送   │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  LAYER 4: 心跳与调度层 (Heartbeat & Scheduler)                 │
│  APScheduler AsyncIO；防重入锁；指数退避重试；Sweeper 清档       │
└────────────────────────────┬─────────────────────────────────┘
                             │ 触发
┌────────────────────────────▼─────────────────────────────────┐
│  LAYER 3: 多智能体协作层 (Multi-Agent Coordination)            │
│  CrawlerAgent → InsightAgent → QueryAgent ──┐                │
│  MediaAgent → SentimentAgent               ForumHost(每5条)  │
│  OntologyAgent → GraphAgent → SimulationAgent → PredictAgent │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  LAYER 2: 上下文与记忆层 (Context & Memory)                    │
│  ContextEngine (bootstrap/ingest/compact/assemble)           │
│  SQLite-Vec Hybrid Memory + Zep Cloud 时序图谱               │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────┐
│  LAYER 1: 数据基础层 (Data Foundation)                         │
│  7平台×14表 + canonical_items + daily_topics + Vector DB      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 E2E 完整数据流

```
[心跳调度] ──定时触发──▶
  Phase 0  TopicExtractor (BroadTopicExtraction) + SocialCrawler (7平台×14表)
  Phase 1  MediaCrawlerDB 5大查询工具 + 加权热度 → HotnessThreshold 判定
  Phase 2  QueryAgent/InsightAgent/MediaAgent 并行分析
           ↕ ForumHost (每5条发言 → Qwen LLM 引导 → forum.log)
  Phase 3  SentimentAgent (22语言，5级) 批量情感标注
  Phase 4  智能选题 (热度×情感×事件权重) → ReportEngine 初始快报
  Phase 5  OntologyGenerator (10实体+6-10关系) + GraphBuilder → Zep Cloud
  Phase 6  OasisProfileGenerator → SimulationRunner (144轮双平台) → ZepMemoryUpdate
  Phase 7  PredictionReportAgent (图谱查询+Agent对话+预测报告)
           → 写入 SQLite-Vec 长期记忆 → Channel Gateway 多渠道分发
```

---

## 三、核心技术对应设计

### 3.1 上下文管理
- 每个 Pipeline Run 维护独立 `sessionId`，实现 `bootstrap(先验记忆注入) / ingest(消息追加) / compact(Token裁减)`
- `isHeartbeat=True` 区分定时触发与手动触发，心跳结果不直接推送给用户

### 3.2 记忆管理
- **短期**: `AgentsSessionModel` 存中间结果
- **长期 (历史检索)**: SQLite + sqlite-vec，BM25+向量混合检索历史分析报告
- **图谱记忆**: Zep Cloud 时序图谱，`valid_at/invalid_at` 建模知识有效期

### 3.3 心跳技术
- `APScheduler`，AsyncIO 模式，间隔 6 小时（可配置）
- 防重入 `asyncio.Lock`，同一话题不并发执行
- 子任务失败用指数退避（1s→2s→4s→8s），最多 3 次重试

### 3.4 渠道技术
- **内部流**: FastAPI SSE `/agents/stream/{run_id}` 实时推送进度
- **外部推送**: `ChannelDispatcher` 抽象 Webhook，支持 Telegram/企业微信
- **防抖**: 短时间多次触发仅执行最后一次

---

## 四、分阶段执行方案

> **现有基础**: `backend/agents` 已有 BettaFish P0-P3 Routers + MiroFish P4-P5 框架

### Phase 1 — 基础设施层 (预计 2-3 天)
| 新建文件 | 功能 |
| :--- | :--- |
| `backend/agents/scheduler.py` | APScheduler 心跳调度引擎 |
| `backend/agents/memory.py` | SQLite-Vec + Zep 长效记忆连接器 |
| `backend/agents/context_engine.py` | 会话上下文生命周期管理 |

### Phase 2 — E2E 主控协调器 (预计 3-4 天)
| 新建文件 | 功能 |
| :--- | :--- |
| `backend/agents/pipeline/e2e_coordinator.py` | E2E 9 阶段主控调度器 |
| `backend/agents/subagent_registry.py` | 子智能体生命周期注册表 |

### Phase 3 — 渠道网关层 (预计 1-2 天)
| 新建文件 | 功能 |
| :--- | :--- |
| `backend/agents/channel_dispatcher.py` | 多渠道 Webhook 分发 |
| `backend/agents/server.py` (更新) | 新增 WebSocket endpoint |

### Phase 4 — 系统联调 (预计 2 天)
- 全链路 E2E 压力测试
- 异常恢复测试（Zep超时、OASIS崩溃）
- 记忆先验偏置验证（同话题第二次运行引用历史）

---

## 五、关键设计决策

| 决策 | 选择 | 理由 |
| :--- | :--- | :--- |
| 调度框架 | `APScheduler (AsyncIO)` | 与 FastAPI 生命周期无缝集成 |
| 向量存储 | `SQLite + sqlite-vec` | 参考 OpenClaw，轻量无外部依赖 |
| 图谱存储 | `Zep Cloud` | 时序边支持，适合舆情演化建模 |
| Agent 通信 | `asyncio.Queue + Forum.log 机制` | 参考 BettaFish，异步化改造 |
| 心跳间隔 | 6小时（可配置） | 覆盖热点周期，避免过频触发平台封禁 |

> ⚠️ **风险**: Zep Cloud API 限速 & OASIS 单机内存瓶颈，建议 `max_agents=50` + `timeout=600s`
