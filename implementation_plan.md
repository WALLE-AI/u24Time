# 端对端多智能体情报预测架构方案 v2.1
> 基于 **BettaFish + MiroFish + OpenClaw** 三项目源码逐行深度分析  
> 版本: 2.1 | 更新时间: 2026-03-09 | 分析深度: 源码级 · 算法级 · 数据流级

---

## 一、三大项目核心技术图谱 (Deep Source-Level Analysis)

### 1.1 BettaFish 核心技术

| 模块 | 关键文件 | 深度实现细节 |
| :--- | :--- | :--- |
| **MindSpider** | `get_today_news.py` / `topic_extractor.py` | 两阶段串行: BroadTopicExtraction(100关键词→`daily_topics`表) → DeepSentimentCrawling(7平台×14表); `subprocess.run`驱动; 支持断点续传+DB健康检查 |
| **InsightEngine** | `agent.py` (40KB) | 5大查询工具(hot/global/date/comments/platform); UNION ALL 跨15张表; **热度公式**: `Like×1+Comment×5+Share×10+View×0.1+Danmaku×0.5`; Qwen关键词语义扩展 |
| **QueryEngine** | `nodes/` | SearchNode→FormattingNode→**ReflectionSummaryNode**(max 2轮)→FirstSummaryNode→SummaryNode; max_search_results=15; 多层JSON容错修复(`fix_json_string`) |
| **SentimentAnalyzer** | `SentimentAnalysisModel/` | 默认`tabularisai/multilingual-sentiment-analysis`(22语言); 5级(-2~+2); 批量处理返回`sentiment_distribution+confidence_mean`; CUDA>MPS>CPU优先 |
| **ForumEngine** | `monitor.py` / `llm_host.py` | 1秒轮询3个日志文件大小变化; 每**5条**Agent发言触发HostLLM(Qwen)生成引导; `threading.Lock`并发安全写入; 过滤ERROR块(遇错暂停到下个INFO) |
| **ReportEngine** | `ir/validator.py` / `stitcher.py` | 模板选择→布局设计→字数预算→章节JSON生成→IR验证装订→HTML/PDF/MD; 支持SVG图表块; 增量重渲染(跳过分析阶段) |

### 1.2 MiroFish 核心技术

| 模块 | 深度实现细节 |
| :--- | :--- |
| **OntologyGenerator** | temperature=0.3; 精确10实体+6-10关系; 最后2个必须是Person/Organization; **Zep保留字防御**: `RESERVED_NAMES={uuid,name,group_id,summary,created_at}` 自动前缀避让 |
| **GraphBuilderService** | Zep Cloud API; `chunk_size=500 overlap=50`; `batch_size=3`写EpisodeData; 轮询`episode.processed`(每3秒检查,超时600s); 返回节点数/边数/实体分布 |
| **OasisProfileGenerator** | 从Zep图谱节点提取→生成Agent人设/记忆/行为配置; 每个Agent独立人格+记忆空间 |
| **SimulationRunner** | OASIS双平台并行(Twitter+Reddit); **144轮**(72h@30min/轮); Agent动作→独立`actions.jsonl`; 跨平台进程管理(Win:`taskkill /F /T /PID` / Unix:`SIGTERM`) |
| **ZepGraphMemoryUpdater** | 监控线程每2s读`actions.jsonl`; Agent行为→**时序边(`valid_at/invalid_at/expired_at`)**写入Zep; 支持知识图谱时序回放 |
| **ReportAgent** | 99KB核心文件; ZepEntityReader(实体/多跳路径/时序事实查询)+Agent深度对话; `get_graph_data()`返回完整节点+边+属性 |

### 1.3 OpenClaw 核心技术 (源码精读)

#### 记忆管理子系统 (`src/memory/`)

**`manager.ts` — MemoryIndexManager 核心类**

```
架构: MemoryIndexManager extends MemoryManagerEmbeddingOps implements MemorySearchManager
存储: SQLite(同步) + chunks_vec(向量表) + chunks_fts(FTS5表) + embedding_cache表
嵌入: 支持 OpenAI/Gemini/Voyage/Mistral/Ollama — 自动Fallback链
同步: FSWatcher(文件变更watch) + SessionListener + IntervalSync(定时) + on-search触发
只读恢复: SQLITE_READONLY → 关闭连接 → 重开连接 → 重试(readonlyRecovery机制)
会话预热: warmSession() — 首次search时自动触发sync(reason="session-start")
```

**`search()` — 五步混合检索流水线**:

```
Step 1: extractKeywords(query) → 多语言停用词过滤(EN/ES/PT/AR/ZH/KO/JA)
        → CJK字符n-gram化(中文bigram/日文分脚本/韩文去助词)
Step 2: FTS-only降级路径 — 无嵌入Provider时纯BM25检索
        OR
        并行: BM25关键词检索(chunks_fts) + 向量检索(chunks_vec)
Step 3: mergeHybridResults(vectorWeight * vecScore + textWeight * textScore)
Step 4: applyTemporalDecayToHybridResults — 指数半衰期衰减
        score = score × e^(-λt)  [λ = ln2/halfLifeDays]
        ⚠️ 常青文件豁免: MEMORY.md/memory.md/非日期命名memory文件不参与衰减
Step 5: mmrRerank — MMR多样性重排序
        MMR = λ×relevance - (1-λ)×max_JaccardSimilarity_to_selected (default λ=0.7)
```

**`mmr.ts` — MMR算法核心**:
- Jaccard相似度计算: Tokenize → 取交集/并集 → `intersectionSize/unionSize`
- 分数归一化到[0,1]后参与MMR计算
- 迭代贪心选择: 每轮选MMR分最高项，使用原始分数打破平局

**`temporal-decay.ts` — 时序衰减**:
- `halfLifeDays=30` (默认关闭, 需显式启用)
- 公式: `score × exp(-ln2/halfLifeDays × ageInDays)`
- 日期文件名识别: `/memory/YYYY-MM-DD.md` 正则解析 → 获取文件日期

**`query-expansion.ts` — 多语言查询扩展** (用于FTS降级模式):
- EN/ES/PT/AR/ZH/KO/JA 7语言停用词全库
- 中文: 字符级unigram + bigram双词
- 日文: 分脚本提取(ASCII/片假名/汉字/平假名)
- 韩文: 结尾助词剥离(`KO_TRAILING_PARTICLES`)后语义词干提取
- LLM增强扩展: `expandQueryWithLlm()` — 先LLM扩展，失败fallback本地 

**`query-expansion.ts` 中文示例**:
```
"之前讨论的那个方案" → tokens: ["讨论","方案"] (过滤停用词"之前","那个")
→ FTS查询: "讨论" AND "方案"
```

#### 上下文管理子系统 (`src/context-engine/`, `src/agents/compaction.ts`)

**`types.ts` — ContextEngine 接口(可插拔合约)**:

```typescript
interface ContextEngine {
  bootstrap?({sessionId, sessionFile}): Promise<BootstrapResult>
  // 初始化引擎状态; 可选导入历史上下文; bootstrapped=true表示成功
  
  ingest({sessionId, message, isHeartbeat?}): Promise<IngestResult>
  // 单条消息入库; isHeartbeat=true时消息不推送UI; 返回ingested=false表示重复
  
  ingestBatch?({sessionId, messages, isHeartbeat?}): Promise<IngestBatchResult>
  // 整轮批量入库; 返回ingestedCount
  
  afterTurn?({sessionId, sessionFile, messages, prePromptMessageCount,
              autoCompactionSummary?, isHeartbeat?, tokenBudget?, runtimeContext?}): Promise<void>
  // 轮次后钩子; 持久化规范上下文; 触发后台压实决策
  
  assemble({sessionId, messages, tokenBudget?}): Promise<AssembleResult>
  // 在Token预算内组装最终messages[]; 可输出systemPromptAddition前缀
  
  compact({sessionId, sessionFile, tokenBudget?, force?, currentTokenCount?,
           compactionTarget?, customInstructions?, runtimeContext?}): Promise<CompactResult>
  // 压实: 生成摘要, 裁剪旧轮次; ownsCompaction=true时引擎自管理压实
  
  prepareSubagentSpawn?({parentSessionKey, childSessionKey, ttlMs?}): PrepareResult
  // 子智能体衍生前准备; 返回rollback()支持失败回滚
  
  onSubagentEnded?({childSessionKey, reason}): Promise<void>
  // 子智能体生命周期结束通知(deleted/completed/swept/released)
}
```

**`compaction.ts` — 四级压实策略**:

```
常量:
  BASE_CHUNK_RATIO = 0.4     # 基础分块比例(保留40%历史)
  MIN_CHUNK_RATIO  = 0.15    # 最小分块比例(大消息场景)
  SAFETY_MARGIN    = 1.2     # Token估算安全系数(+20%缓冲)
  SUMMARIZATION_OVERHEAD = 4096  # 留给摘要LLM的额外Token

Level 1: pruneHistoryForContextShare() — 历史裁剪
  while estimateTokens(messages) > maxContextTokens * maxHistoryShare(=0.5):
    按tokenShare分块 → 丢弃最旧块 → repairToolUseResultPairing(修复孤儿tool_result)

Level 2: summarizeChunks() — 分块摘要
  chunkMessagesByMaxTokens() → 每块逐个summarize → retryAsync(3次, 500ms~5s退避)
  SECURITY: stripToolResultDetails() — 禁止toolResult.details泄露至摘要

Level 3: summarizeWithFallback() — 渐进降级
  尝试全量摘要 → 失败时仅摘要"小消息"跳过oversized(>50%上下文) → 最终fallback只记录统计

Level 4: summarizeInStages() — 多阶段摘要合并
  splitMessagesByTokenShare(parts=2) → 各块独立摘要 → MERGE_SUMMARIES_INSTRUCTIONS合并
  合并关键要求: 保留进行中任务状态/批量进度/UUID等标识符/开放TODO/最后用户请求

```

**`subagent-registry.ts` — 子智能体完整状态机**:

```
全局常量:
  SUBAGENT_ANNOUNCE_TIMEOUT_MS      = 120_000   # 公告超时2分钟
  MIN_ANNOUNCE_RETRY_DELAY_MS       = 1_000     # 最小退避1秒
  MAX_ANNOUNCE_RETRY_DELAY_MS       = 8_000     # 最大退避8秒
  MAX_ANNOUNCE_RETRY_COUNT          = 3         # 超3次放弃
  ANNOUNCE_EXPIRY_MS                = 5×60_000  # 非completion公告5分钟强制过期
  ANNOUNCE_COMPLETION_HARD_EXPIRY   = 30×60_000 # completion公告30分钟硬上限
  LIFECYCLE_ERROR_RETRY_GRACE_MS    = 15_000    # 错误事件15秒宽限期(等待重试取消)
  FROZEN_RESULT_TEXT_MAX_BYTES      = 100×1024  # 冻结结果100KB上限
  archiveAfterMinutes               = 60        # 60分钟后Sweeper归档

指数退避公式: baseDelay = MIN × 2^(retryCount-1), capped at MAX
  retry#1 = 1s, retry#2 = 2s, retry#3 = 4s → MAX=8s封顶

生命周期状态机:
  [SPAWNED] → [RUNNING(start事件)] → [COMPLETED(end事件)] 
                                    OR [ERROR(error事件→15s宽限→FAILED)]
                                    OR [KILLED] → [ARCHIVED(sweeper@60s)]

磁盘持久化: persistSubagentRunsToDisk() / restoreSubagentRunsFromDisk()
  支持重启恢复 + 孤儿运行调和(orphan reconciliation)

Context Engine集成: 子智能体结束时调用 engine.onSubagentEnded(childSessionKey, reason)
```

**`heartbeat-policy.ts` — 心跳策略**:

```typescript
shouldSkipHeartbeatOnlyDelivery(payloads, ackMaxChars):
  // 有媒体附件 → 不跳过
  // 纯文本且strip心跳Token后shouldSkip=true → 跳过(避免无内容推送)

shouldEnqueueCronMainSummary({summaryText, deliveryRequested, delivered,
                              deliveryAttempted, suppressMainSummary, isCronSystemEvent}):
  // summaryText非空 AND 是CronSystemEvent AND 投递被请求
  // AND 未成功投递 AND 未尝试过 AND 未抑制 → 入队
```

**`channels/inbound-debounce-policy.ts` — 防抖策略**:

```typescript
shouldDebounceTextInbound({text, cfg, hasMedia, commandOptions, allowDebounce}):
  // allowDebounce=false → 不防抖
  // hasMedia → 不防抖(媒体消息即时处理)
  // 含ControlCommand(斜杠命令等) → 不防抖
  // 普通文本 → 参与防抖(merging short-interval messages)
```

---

## 二、整体架构设计 — 六层架构模型 (v2.1 增强版)

```
┌────────────────────────────────────────────────────────────────────┐
│  LAYER 6: 渠道网关层 (Channel Gateway)                              │
│  WebSocket双向 + SSE实况流 + Webhook分发(Telegram/企微/飞书)         │
│  InboundDebounce(媒体/控制命令不防抖) | HeartbeatPolicy(心跳抑制)    │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────┐
│  LAYER 5: 心跳与调度层 (Heartbeat & Scheduler)                      │
│  APScheduler AsyncIO | 心跳防重入锁 | isHeartbeat标志               │
│  指数退避(1→2→4→8s,max3次) | Sweeper@60s清档 | 磁盘持久化重启恢复    │
│  LIFECYCLE_ERROR_RETRY_GRACE_MS=15s错误宽限 | 任务状态机             │
└───────────────────────────────────┬────────────────────────────────┘
                                    │ 触发 (isHeartbeat=True/False)
┌───────────────────────────────────▼─────────────────────────────────────────┐
│  LAYER 4: 多智能体协作层 (Multi-Agent Coordination)                          │
│  SubagentRegistry 统一生命周期 + 磁盘持久化 + onSubagentEnded回调            │
│                                                                              │
│  Phase 0: CrawlerAgent(TopicExtractor 100词 + SocialCrawler 7平台)           │
│  Phase 1: AlignmentAgent(MediaCrawlerDB×5工具 + 跨平台热度统一计算)          │
│  Phase 2: [QueryAgent + InsightAgent + MediaAgent] ←asyncio.gather并行       │
│           ForumHost(5条/触发 → Qwen引导 → asyncio.Queue共享)                │
│  Phase 3: SentimentAgent(22语言5级) + TopicSelectorAgent(三维权重决策)       │
│  Phase 4: ReportEngine(IR装订 → HTML/PDF/MD)                                │
│  Phase 5: OntologyAgent(10实体+关系本体) + GraphAgent(Zep Cloud)             │
│  Phase 6: ProfileAgent(人设生成) + SimulationAgent(OASIS 144轮双平台)        │
│           ZepGraphUpdater(2s轮询actions.jsonl → 时序边)                      │
│  Phase 7: PredictionAgent(ZepEntityReader + Agent对话 + 预测报告)            │
└───────────────────────────────────┬─────────────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────┐
│  LAYER 3: 上下文管理层 (Context Engine) — 可插拔接口                │
│                                                                     │
│  bootstrap()  → 注入先验记忆到System Prompt前缀                     │
│  ingest()     → 追加消息; isHeartbeat=True时不推送UI                │
│  ingestBatch()→ 整轮批量入库(ForumEngine一轮汇总后批量提交)          │
│  afterTurn()  → Token预算检查 → 触发后台压实决策                    │
│  assemble()   → Token预算内组装messages[] + systemPromptAddition    │
│  compact()    → 四级压实策略 (裁剪→分块摘要→降级→多阶段合并)         │
│  prepareSubagentSpawn() → Rollback支持                              │
│  onSubagentEnded()      → 子智能体结束通知                          │
│                                                                     │
│  Token保护: SAFETY_MARGIN=1.2; toolResult.details禁止泄露至摘要     │
│  动静隔离: System Prompt(不可裁减) vs 动态消息流(超限从最旧裁减)      │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────┐
│  LAYER 2: 记忆管理层 (Memory Management) — 三层架构                 │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │短期工作记忆: AgentsSessionModel (SQLite)                     │   │
│  │ → 当前Pipeline运行状态 + Stage产出 + 中间结果               │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │长期分析记忆: MemoryIndexManager (参考OpenClaw深度实现)        │   │
│  │ 存储: SQLite + chunks_vec(向量) + chunks_fts(FTS5)           │   │
│  │ 嵌入: OpenAI → Gemini → Voyage → Mistral → Ollama fallback  │   │
│  │ 搜索: 5步流水线 (关键词扩展→BM25∥向量→加权合并→时序衰减→MMR)  │   │
│  │ MMR: λ×relevance-(1-λ)×Jaccard, λ=0.7, 常青文件豁免衰减     │   │
│  │ 同步: FS Watch + Session监听 + 定时同步 + search触发         │   │
│  │ 容灾: SQLITE_READONLY → 自动重连恢复 + batch失败计数         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │图谱时序记忆: Zep Cloud                                       │   │
│  │ 节点: uuid/name/labels/summary/attributes                   │   │
│  │ 边: valid_at/invalid_at/expired_at 时序建模                  │   │
│  │ 仿真: Agent行为 → 带时间戳的时序边 → 舆情演化时序回放        │   │
│  └─────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────┬────────────────────────────────┘
                                    │
┌───────────────────────────────────▼────────────────────────────────┐
│  LAYER 1: 数据基础层 (Data Foundation)                               │
│  7平台×14表原始数据(MySQL/PostgreSQL) | canonical_items表            │
│  daily_topics表 | SQLite本地向量存储 | actions.jsonl仿真日志          │
└────────────────────────────────────────────────────────────────────┘
```

---

## 三、记忆管理深度设计 (Memory Management — v2.1 精化)

### 3.1 长期记忆系统设计

```python
# backend/agents/memory.py (新建) — 深度参考 OpenClaw memory/manager.ts

class MemoryIndexManager:
    """
    三表架构: files(元数据) + chunks(分块文本) + chunks_vec(向量) + chunks_fts(FTS5)
    嵌入Fallback链: OpenAI → Gemini → Voyage → Mistral → 无Provider(降级FTS-only)
    """
    
    async def store_analysis(self, topic: str, content: str, metadata: dict):
        """
        存储分析报告为记忆片段
        1. 按 chunk_size=500, overlap=50 分块
        2. embedBatch(chunks) → 多Provider fallback
        3. 写入 chunks_vec (向量) + chunks_fts (BM25索引)
        4. 更新 files 元数据表 (含时间戳供时序衰减使用)
        """
    
    async def search_history(self, query: str, k: int = 5) -> list[MemorySearchResult]:
        """
        五步混合检索流水线 — 完整参考 OpenClaw manager.search()
        """
        # Step 1: 多语言关键词扩展 (FTS降级路径/混合路径)
        keywords = extract_keywords(query)  # EN/ZH/JA/KO/AR多语言停用词过滤
        
        # Step 2A: BM25 FTS检索 (chunks_fts)
        bm25_results = self._search_keyword(query, candidates)
        # FTS查询构建: tokens → `"token1" AND "token2"` 格式
        # BM25分数转换: score = relevance / (1 + relevance) 归一化到[0,1]
        
        # Step 2B: 向量检索 (chunks_vec)
        query_vec = await self._embed_query(query)  # 含 embedQueryWithTimeout
        vec_results = self._search_vector(query_vec, candidates)
        
        # Step 3: 加权合并
        merged = merge_hybrid_results(
            vector=vec_results, keyword=bm25_results,
            vectorWeight=0.7, textWeight=0.3  # 默认向量权重更高
        )
        # byId去重 → score = vectorWeight×vecScore + textWeight×textScore
        
        # Step 4: 时序衰减 (halfLifeDays=30)
        # score = score × exp(-ln2/30 × ageInDays)
        # 常青文件豁免: MEMORY.md/memory/{非日期命名}.md 不参与衰减
        decayed = await apply_temporal_decay(merged, half_life_days=30)
        sorted_results = sorted(decayed, key=lambda x: x.score, reverse=True)
        
        # Step 5: MMR多样性重排序 (λ=0.7)
        # MMR_score = 0.7×relevance - 0.3×max_JaccardSim_to_selected
        # Jaccard: intersect(tokenize(A), tokenize(B)) / union(...)
        return apply_mmr_rerank(sorted_results, lambda_=0.7, k=k)
    
    async def _handle_fts_only_fallback(self, query: str, k: int) -> list:
        """无嵌入Provider时降级为纯BM25 + 关键词扩展"""
        keywords = extract_keywords(query)
        search_terms = keywords if keywords else [query]
        result_sets = await gather(*[self._search_keyword(t, k) for t in search_terms])
        # 合并去重, 保留最高分 → 返回前k个
```

### 3.2 上下文引擎设计

```python
# backend/agents/context_engine.py (新建) — 深度参考 OpenClaw context-engine/types.ts

class AgentContext:
    """
    实现 ContextEngine 完整接口合约
    可插拔设计: 支持替换不同压实策略
    """
    session_id: str
    messages: list[AgentMessage]  # {role, content, timestamp, token_count}
    total_tokens: int
    is_heartbeat: bool
    system_prompt: str           # 静态层 — 不可裁减
    
    async def bootstrap(self, session_file: str) -> BootstrapResult:
        """
        初始化阶段:
        1. 从 MemoryIndexManager 检索同话题历史报告(k=5, 5步流水线)
        2. 从 Zep 检索同话题先验图谱摘要
        3. 将先验记忆注入 systemPromptAddition (assemble时前置)
        4. 返回 {bootstrapped: True, importedMessages: N}
        """
    
    async def ingest(self, message: AgentMessage, is_heartbeat=False) -> IngestResult:
        """
        消息入库:
        - 重复消息检测(by message_id) → 返回 ingested=False
        - is_heartbeat=True: 消息入库但不触发Channel推送
        - 实时累计 total_tokens
        """
    
    async def ingest_batch(self, messages: list, is_heartbeat=False) -> IngestBatchResult:
        """批量入库 — 整个ForumEngine轮次完成后一次性提交"""
    
    async def after_turn(self, pre_prompt_count: int, token_budget: int, **kwargs):
        """
        轮次后钩子 (ownsCompaction=False时由外部决定是否触发compact):
        1. 持久化规范上下文到 AgentsSessionModel
        2. 检查 total_tokens > token_budget × 0.85 → 触发后台compact()
        3. is_heartbeat=True → 跳过Channel通知
        """
    
    async def assemble(self, token_budget: int) -> AssembleResult:
        """
        组装最终 messages[]:
        1. System Prompt (静态层, 优先级最高, 不裁减)
        2. systemPromptAddition (先验记忆前缀, 不裁减)
        3. 动态消息流 (super限: token_budget - system_tokens)
        返回 {messages, estimatedTokens, systemPromptAddition}
        """
    
    async def compact(self, token_budget: int, force=False) -> CompactResult:
        """
        四级压实策略 (完全参考 OpenClaw compaction.ts):
        
        Level 1: pruneHistoryForContextShare()
          maxHistoryShare = 0.5 (历史最多占50%上下文)
          while tokens > budget×0.5: 按tokenShare分块丢弃最旧块
          repairToolUseResultPairing() 修复孤儿tool_result
        
        Level 2: summarizeChunks()
          chunkMessagesByMaxTokens(effectiveMax = maxChunks/SAFETY_MARGIN(1.2))
          stripToolResultDetails() — 安全: 禁止泄露details至摘要
          retryAsync(3次, 500ms~5s jitter=0.2)
        
        Level 3: summarizeWithFallback()
          全量摘要失败 → 仅摘要smallMessages(跳过>50%上下文的oversized)
          记录oversized注释: "[Large assistant (~12K tokens) omitted]"
        
        Level 4: summarizeInStages()
          parts=2: 两阶段分块摘要 → MERGE_SUMMARIES_INSTRUCTIONS合并
          保留: 进行中任务状态/批量进度(`5/17 items`)/UUID/开放TODO/承诺
        
        返回: {ok, compacted, result: {summary, firstKeptEntryId,
               tokensBefore, tokensAfter, details}}
        """
    
    async def prepare_subagent_spawn(self, parent_key: str, child_key: str) -> Rollback:
        """子智能体衍生前状态准备 + Rollback支持"""
    
    async def on_subagent_ended(self, child_key: str, reason: str):
        """子智能体结束通知 → 更新SubagentRegistry状态"""
```

### 3.3 多智能体中每个 Agent 的上下文/记忆独立性设计

| Agent | 上下文作用域 | 记忆访问 | isHeartbeat处理 |
| :--- | :--- | :--- | :--- |
| **CrawlerAgent** | 独立 session (父pipeline的子会话) | 只写: 爬取结果→AgentsSessionModel | True: 跳过UI推送 |
| **QueryAgent** | 独立session + forum共享空间 | 读: MemoryIndexManager先验知识 | True: 摘要入库但不推送 |
| **InsightAgent** | 同上 | 读+写: 本地DB查询→forum贡献 | 同上 |
| **MediaAgent** | 同上 | 读: Zep图谱实体关联 | 同上 |
| **ForumHost** | 共享 forum.log / asyncio.Queue | 读: 全部Agent发言摘要 | True: 引导词不推送 |
| **SentimentAgent** | 批处理模式(无会话) | 只写: 情感分布→AgentsSessionModel | True: 静默运行 |
| **OntologyAgent** | 独立session | 读: 报告文本+Zep先验本体 | True: 静默 |
| **GraphAgent** | Zep图谱session | 写: EpisodeData → Zep Cloud | True: 静默 |
| **SimulationAgent** | 后台Task (asyncio.create_task) | 读写: actions.jsonl + Zep时序边 | True: 进度静默 |
| **PredictionAgent** | 独立session + ZepTools | 读: 图谱+仿真日志; 写: 预测报告→MemoryIndex | False: 最终推送 |

---

## 四、心跳技术深度设计 (Heartbeat — v2.1)

```python
# backend/agents/scheduler.py — 完整参考 OpenClaw subagent-registry + heartbeat-policy

class HeartbeatScheduler:
    """APScheduler AsyncIO心跳调度引擎"""
    
    # 全局常量对应 OpenClaw 源码
    MIN_RETRY_DELAY_MS   = 1_000  # 1秒
    MAX_RETRY_DELAY_MS   = 8_000  # 8秒
    MAX_RETRY_COUNT      = 3      # 放弃前最多3次
    LIFECYCLE_GRACE_MS   = 15_000 # 错误宽限期15秒
    ARCHIVE_AFTER_MIN    = 60     # 60分钟Sweeper归档
    
    def _resolve_retry_delay(self, retry_count: int) -> float:
        """指数退避: delay = MIN × 2^(retryCount-1), capped at MAX"""
        bounded = max(0, min(retry_count, 10))
        exponent = max(0, bounded - 1)
        base = self.MIN_RETRY_DELAY_MS * (2 ** exponent)
        return min(base, self.MAX_RETRY_DELAY_MS) / 1000.0
    
    async def _heartbeat_job(self):
        """心跳触发 — is_heartbeat=True"""
        if self._running.get('global'):
            return  # 防重入
        
        # 15秒宽限期机制: 遇到错误不立即失败,等待可能的重试取消信号
        async with self._lock:
            self._running['global'] = True
            try:
                await self._run_with_grace_period(e2e_coordinator.run)
            except Exception:
                await self._schedule_lifecycle_error_recovery()
            finally:
                self._running['global'] = False
    
    def should_skip_heartbeat_delivery(self, payload: str, has_media: bool) -> bool:
        """参考 heartbeat-policy.shouldSkipHeartbeatOnlyDelivery"""
        if has_media:
            return False  # 有媒体永不跳过
        return is_heartbeat_ack_only(payload)  # 纯ACK跳过
    
    async def _sweeper_job(self):
        """60秒间隔: 归档超时/完成的SubagentRunRecord"""
        for run_id, record in list(self._registry.items()):
            if record.archive_at_ms and record.archive_at_ms <= now():
                await self._archive_and_notify_context_engine(run_id, record)
    
    async def _persist_runs(self):
        """磁盘持久化 — 参考 persistSubagentRunsToDisk()"""
        # 写入 backend/data/subagent_runs.json
        # 支持进程重启后 restoreSubagentRunsFromDisk() 恢复
```

---

## 五、渠道技术深度设计 (Channel — v2.1)

```python
# backend/agents/channel_dispatcher.py — 参考 OpenClaw channels/

class ChannelDispatcher:
    """多渠道推送分发网关"""
    
    def should_debounce(self, text: str, has_media: bool, allow_debounce: bool = True) -> bool:
        """参考 inbound-debounce-policy.shouldDebounceTextInbound"""
        if not allow_debounce or has_media:
            return False
        if has_control_command(text):  # 斜杠命令等
            return False
        return True  # 普通文本参与防抖合并
    
    async def dispatch(self, event: str, payload: dict, run_id: str, is_heartbeat=False):
        """统一分发 — 心跳事件应用HeartbeatPolicy过滤"""
        if is_heartbeat:
            # shouldSkipHeartbeatOnlyDelivery() 检查 — 纯ACK跳过推送
            if self.should_skip_heartbeat_delivery(payload.get('text',''), False):
                return
        
        await asyncio.gather(
            self._push_sse(run_id, event, payload),
            self._push_ws(run_id, event, payload),
            *[self._push_webhook(wh, event, payload)
              for wh in self._webhooks if event in wh.events]
        )
    
    async def _push_webhook(self, wh: WebhookConfig, event: str, payload: dict):
        """支持 Telegram Bot API / 企业微信 / 飞书"""
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(wh.url, json={"event": event, **payload})
```

---

## 六、SubagentRegistry 深度设计 (v2.1 — 完整状态机)

```python
# backend/agents/subagent_registry.py — 参考 OpenClaw subagent-registry.ts

class SubagentRunRecord(BaseModel):
    run_id: str
    parent_run_id: str | None
    child_session_key: str
    stage: str              # phase0_crawl / phase1_align / ... / phase7_predict
    status: SubagentStatus
    started_at: float | None
    ended_at: float | None
    outcome: SubagentOutcome | None  # {status: ok|error|timeout, error?: str}
    ended_reason: str | None        # complete/error/killed/swept
    announce_retry_count: int = 0
    last_announce_retry_at: float | None
    cleanup_handled: bool = False
    cleanup_completed_at: float | None
    archive_at_ms: float | None     # archiveAfterMinutes=60
    frozen_result_text: str | None  # 最终输出快照(100KB上限)
    frozen_result_captured_at: float | None
    workspace_dir: str | None

class SubagentRegistry:
    # MAX_ANNOUNCE_RETRY_COUNT = 3
    # ANNOUNCE_EXPIRY_MS = 5×60_000
    # ANNOUNCE_COMPLETION_HARD_EXPIRY_MS = 30×60_000
    # LIFECYCLE_ERROR_RETRY_GRACE_MS = 15_000
    
    async def schedule_lifecycle_error(self, run_id: str, error: str):
        """15秒宽限: 等待可能的start事件取消此错误(Provider重试场景)"""
        async def deferred():
            await asyncio.sleep(15)
            if not self._error_cancelled(run_id):
                await self.complete_run(run_id, status='error', error=error)
        asyncio.create_task(deferred())
    
    async def sweep(self):
        """Sweeper@60s: archiveAtMs到期→通知ContextEngine→删除记录→清理会话"""
        for run_id, record in list(self._runs.items()):
            if record.archive_at_ms and record.archive_at_ms <= now():
                await self._ctx_engine.on_subagent_ended(
                    record.child_session_key, reason="swept")
                del self._runs[run_id]
    
    async def persist(self):
        """磁盘持久化 → 支持重启后恢复"""
    
    async def restore(self):
        """重启恢复 + 孤儿调和(orphan reconciliation)"""
        # 孤儿检测: 找不到对应SessionEntry → 标记为error并清理
```

---

## 七、E2E Coordinator — 统一主控协调器 (v2.1)

```python
# backend/agents/pipeline/e2e_coordinator.py

class EndToEndCoordinator:
    """贯通 7 阶段 BettaFish+MiroFish 全流程"""
    
    async def run(self, topic: str = "auto", is_heartbeat: bool = False):
        session_id = str(uuid4())
        ctx = AgentContext(session_id=session_id, is_heartbeat=is_heartbeat)
        registry = SubagentRegistry()
        
        # ① 引导: 五步流水线检索先验记忆 → 注入SystemPromptAddition
        await ctx.bootstrap(session_file=f"sessions/{session_id}.json")
        
        try:
            # ② BettaFish 管道
            topics   = await self._run_phase(0, registry, ctx, self._phase0_crawl)
            hot      = await self._run_phase(1, registry, ctx, self._phase1_align, topics)
            if not hot: return  # 未达热度阈值 → 心跳静默退出
            
            analysis = await self._run_phase(2, registry, ctx, self._phase2_analyze, hot)
            await ctx.ingest_batch(analysis.messages, is_heartbeat)  # 批量提交Forum轮次
            await ctx.after_turn(pre_prompt_count=len(ctx.messages), token_budget=8000)
            
            selection = await self._run_phase(3, registry, ctx, self._phase3_select)
            report    = await self._run_phase(4, registry, ctx, self._phase4_report, selection)
            
            # ③ MiroFish 管道
            graph_id  = await self._run_phase(5, registry, ctx, self._phase5_graph, report)
            sim_task  = asyncio.create_task(self._phase6_simulate(registry, ctx, graph_id))
            prediction= await self._run_phase(7, registry, ctx, self._phase7_predict,
                                              graph_id, sim_task)
            
            # ④ 持久化: 写入长期记忆(5步流水线可检索)
            await memory_mgr.store_analysis(topic, prediction.content,
                                            {"session_id": session_id, "ts": utcnow()})
            
            # ⑤ 渠道分发(HeartbeatPolicy过滤)
            await channel_dispatcher.dispatch("final_report",
                                              {"report": prediction.content},
                                              session_id, is_heartbeat)
        finally:
            await ctx.compact(token_budget=8000)  # 确保Token清理
    
    async def _run_phase(self, phase_id, registry, ctx, fn, *args):
        """通用阶段执行器: 注册→运行→异常隔离→状态机更新"""
        record = registry.register(f"phase{phase_id}", parent=ctx.session_id)
        try:
            result = await fn(*args)
            registry.complete(record.run_id)
            return result
        except Exception as e:
            registry.fail(record.run_id, str(e))
            raise
```

---

## 八、分阶段执行方案 (Execution Plan — v2.1 更新)

> **现有基础**: `backend/agents/pipeline/` 已有 BettaFishPipeline + MiroFishPipeline 骨架

### Phase 1 — 基础设施层 (P0, 预计 4-5 天)

| 文件 | 状态 | 核心实现要点 |
| :--- | :---: | :--- |
| `backend/agents/context_engine.py` | **[NEW]** | 完整8钩子接口; 四级压实策略; 动静隔离; 安全边距×1.2 |
| `backend/agents/memory.py` | **[NEW]** | 五步混合检索; 多语言关键词扩展; MMR(λ=0.7); 时序衰减(30天半衰期); 多Provider fallback |
| `backend/agents/subagent_registry.py` | **[NEW]** | 完整状态机; 15s错误宽限; 指数退避(1→2→4→8s); Sweeper@60s; 磁盘持久化 |
| `backend/agents/scheduler.py` | **[NEW/UPGRADE]** | APScheduler; isHeartbeat标志; HeartbeatPolicy; 防重入锁 |

### Phase 2 — 多智能体协作层 (P1, 预计 4-5 天)

| 文件 | 状态 | 核心实现要点 |
| :--- | :---: | :--- |
| `backend/agents/pipeline/e2e_coordinator.py` | **[NEW]** | 7阶段统一编排; 批量ingestBatch; after_turn压实触发 |
| `backend/agents/phase1_bettafish/topic_selector.py` | **[NEW]** | 热度×情感×事件 三维权重决策; 阈值预警 |
| `backend/agents/pipeline/bettafish_pipeline.py` | **[MODIFY]** | 集成ContextEngine; asyncio.Queue替换文件轮询 |
| `backend/agents/pipeline/mirofish_pipeline.py` | **[MODIFY]** | 集成SubagentRegistry; 后台仿真Task |

### Phase 3 — 渠道网关层 (P2, 预计 2 天)

| 文件 | 状态 | 核心实现要点 |
| :--- | :---: | :--- |
| `backend/agents/channel_dispatcher.py` | **[NEW]** | HeartbeatPolicy过滤; InboundDebounce; WS+SSE+Webhook |
| `backend/agents/server.py` | **[MODIFY]** | WebSocket endpoint; lifespan集成调度器启动 |
| `backend/agents/routers/e2e.py` | **[NEW]** | E2E触发/状态/记忆查询/调度器状态 API |

### Phase 4 — 测试验证 (P3, 予计 2 天)

- **记忆先验验证**: 同话题第二次运行 → 检索先验 → bootstrap注入验证
- **压实安全测试**: 超Token限制场景 → 4级压实策略逐级触发验证
- **心跳静默验证**: is_heartbeat=True → UI无推送 + 数据正常写入
- **异常恢复**: Zep超时/OASIS崩溃/SQLITE_READONLY → 自动恢复验证
- **E2E性能基线**: Phase0→Phase7 全链路耗时记录

---

## 九、关键设计决策与风险

| 决策 | 选择 | 基于OpenClaw源码的理由 |
| :--- | :--- | :--- |
| 调度框架 | `APScheduler AsyncIO` | FastAPI lifespan集成; 复现heartbeat-policy完整语义 |
| 向量存储 | `SQLite + sqlite-vec` | MemoryIndexManager同款方案; SQLITE_READONLY自动恢复 |
| FTS引擎 | `SQLite FTS5` | BM25字段支持; `bm25RankToScore`归一化公式复现 |
| 相似度算法 | `Jaccard (MMR)` | 参考mmr.ts; 计算效率高 vs 余弦相似度 |
| 时序衰减 | `指数半衰期30天` | temporal-decay.ts默认值; 常青文件豁免策略 |
| Agent通信 | `asyncio.Queue` | 替换BettaFish 1s文件轮询; 事件驱动更实时 |
| 上下文压实 | `四级策略+SAFETY_MARGIN=1.2` | 完整参考compaction.ts; toolResult.details安全隔离 |
| 错误宽限 | `15s LIFECYCLE_GRACE_MS` | 参考subagent-registry.ts; 防止Provider重试误判 |

> ⚠️ **风险1**: sqlite-vec Windows二进制兼容性 → 提前验证; 降级纯FTS-only模式  
> ⚠️ **风险2**: Zep Cloud API限速 → `batch_size=3 + episode_timeout=600s`  
> ⚠️ **风险3**: OASIS单机内存瓶颈 → `max_agents=50`; 后期分布式调度  
> ⚠️ **风险4**: 爬虫平台封禁 → IP代理池+UA轮换+速率自适应限制  

---

## 十、验证计划

```bash
# P0: 记忆系统单元验证
cd backend
python -c "
import asyncio
from agents.memory import MemoryIndexManager

async def test():
    mgr = MemoryIndexManager()
    # 存储测试
    await mgr.store_analysis('AI技术', '这是一段测试分析内容' * 100, {})
    # 五步流水线检索验证
    results = await mgr.search_history('AI技术发展', k=5)
    print(f'检索结果数: {len(results)}')
    print(f'最高分: {results[0].score:.4f}')
    print(f'MMR多样性: {results[0].snippet[:50]}...')
asyncio.run(test())
"

# P0: 压实策略验证
python -c "
import asyncio
from agents.context_engine import AgentContext

async def test():
    ctx = AgentContext('test', is_heartbeat=True)
    for i in range(100):
        await ctx.ingest({'role':'user','content':f'消息{i}'*200})
    print(f'压实前tokens: {ctx.total_tokens}')
    result = await ctx.compact(token_budget=4000)
    print(f'压实后tokens: {result.result.tokensAfter}')
    print(f'压实摘要: {result.result.summary[:100]}')
asyncio.run(test())
"

# P1: E2E全链路验证
uvicorn agents.server:app --port 8100
curl -X POST http://localhost:8100/agents/e2e/run \
  -H "Content-Type: application/json" \
  -d '{"topic":"AI技术发展","is_heartbeat":false}'
```

---

*方案版本: v2.1 | 生成时间: 2026-03-09*  
*源码分析: BettaFish(全模块) + MiroFish(全模块) + OpenClaw(memory×7文件 + context-engine/types.ts + compaction.ts + subagent-registry.ts + heartbeat-policy.ts + channels/inbound-debounce)*
