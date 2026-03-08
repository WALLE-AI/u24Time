# BettaFish & MiroFish 深度分析报告

> **分析时间**: 2026-03-08  
> **分析范围**: `opensource/BettaFish` + `opensource/MiroFish`  
> **分析深度**: 源码级 · 模块级 · 数据流级

---

## 一、项目概述与战略定位

### 1.1 两个项目的关系

BettaFish（微舆）和 MiroFish 构成一条完整的"数据分析三板斧"链路：

```
原始社媒数据
    │
    ▼
[BettaFish] ──── 数据采集 → 清洗对齐 → 事件/舆情/图谱分析 → 生成报告
    │
    ▼ (BettaFish报告作为种子数据)
[MiroFish] ──── 图谱构建 → 人设生成 → 社会模拟 → 预测报告
```

- **BettaFish**：v1.2.1，GPL-2.0，面向"当下"的舆情分析系统，以 Flask + 多 Agent 协作为核心
- **MiroFish**：新一代群体智能预测引擎（盛大集团孵化），以 OASIS 社会模拟框架 + Zep 知识图谱为核心，面向"未来"的预测推演

---

## 二、BettaFish 深度分析

### 2.1 系统整体架构

```
用户输入（自然语言问题）
    │
    ├──────────────────────────────┐
    │                              │
    ▼                              ▼
[QueryEngine]              [MediaEngine]           [InsightEngine]
国内外新闻广度搜索            多模态内容分析             私有数据库挖掘
(外部搜索API)               (视频/图片/结构化卡片)      (本地 MySQL/PostgreSQL)
    │                              │                      │
    ▼                              ▼                      ▼
 各自生成段落总结        ────── [ForumEngine] ──────────────
                                论坛协作协调
                                    │
                                    ▼
                             [ReportEngine]
                           智能报告生成（IR中间表示）
                                    │
                                    ▼
                          交互式 HTML / PDF / MD 报告
```

### 2.2 数据获取层：MindSpider 爬虫系统

#### 核心架构

MindSpider 是一个完全自主的 AI 驱动爬虫系统，分两个串行阶段：

**阶段一：BroadTopicExtraction（宽泛话题提取）**
- 抓取今日新闻（`get_today_news.py`），通过 LLM 提取热点话题关键词
- 生成结构化关键词（默认 100 个）存入数据库 `daily_topics` 表
- 数据库操作封装在 `database_manager.py` 和 `topic_extractor.py`

**阶段二：DeepSentimentCrawling（深度情感爬取）**
- 基于第一阶段关键词，在 7 个平台爬取内容：
  - `xhs`（小红书）、`dy`（抖音）、`ks`（快手）、`bili`（B站）、`wb`（微博）、`tieba`（贴吧）、`zhihu`（知乎）
- 使用 `MediaCrawler`（Playwright 驱动）采集帖子、视频、评论
- 数据写入 7 个主表 + 7 个评论表（共 14 张表）

#### 数据库 Schema

| 主表 | 评论表 | 核心字段 |
|------|--------|----------|
| `bilibili_video` | `bilibili_video_comment` | title, liked_count, video_play_count, video_coin_count |
| `douyin_aweme` | `douyin_aweme_comment` | title, liked_count, comment_count, share_count |
| `weibo_note` | `weibo_note_comment` | content, liked_count, comments_count, shared_count |
| `xhs_note` | `xhs_note_comment` | title, liked_count, comment_count, collected_count |
| `kuaishou_video` | `kuaishou_video_comment` | title, liked_count, viewd_count |
| `zhihu_content` | `zhihu_comment` | title, voteup_count, comment_count |
| `tieba_note` | `tieba_comment` | title, desc |

#### 触发方式

```bash
python main.py --broad-topic                          # 仅话题提取
python main.py --deep-sentiment --platforms xhs dy wb  # 仅爬取指定平台
python main.py --complete --date 2024-01-20            # 完整流程
```

MindSpider 主程序（`main.py`）通过 `subprocess.run` 调用子模块，支持：
- 数据库健康检查（`check_database_connection`）
- 自动初始化缺失表（`initialize_database`）
- 依赖自动安装（`_install_mediacrawler_dependencies`）

---

### 2.3 数据对齐与检索层：InsightEngine

InsightEngine 负责将爬取的原始数据转化为结构化的分析素材，核心是 `MediaCrawlerDB` 工具集（`search.py`）：

#### 热度计算模型（加权算法）

```python
W_LIKE    = 1.0    # 点赞权重
W_COMMENT = 5.0    # 评论权重（互动价值最高）
W_SHARE   = 10.0   # 分享/转发/收藏权重（传播价值最高）
W_VIEW    = 0.1    # 播放权重（基础流量）
W_DANMAKU = 0.5    # 弹幕权重（B站特有）
```

不同平台因字段差异而使用不同公式：
- **B站**：`like*1 + comment*5 + share*10 + favorite*10 + coin*10 + danmaku*0.5 + view*0.1`
- **抖音/快手/小红书/微博**：基于各自有效字段的子集

#### 五大查询工具

| 工具名 | 功能 | 时间复杂度 |
|--------|------|-----------|
| `search_hot_content` | 按时间范围（24h/week/year）获取热点内容 | UNION ALL 跨6表排序 |
| `search_topic_globally` | 全库关键词搜索（内容+评论+标签+来源词） | 覆盖15张表 |
| `search_topic_by_date` | 历史时间段话题搜索 | 含时间戳转换（ms/sec/str三种格式） |
| `get_comments_for_topic` | 获取全平台评论（默认limit=500） | UNION ALL 跨7个评论表 |
| `search_topic_on_platform` | 平台精准定向搜索 | 单平台内容+评论双查 |

#### 关键词优化中间件

`keyword_optimizer.py` 使用 Qwen 模型对用户输入的关键词进行语义扩展和优化，提升搜索召回率。

---

### 2.4 事件分析（QueryEngine）

QueryEngine 负责外部网络信息的广度搜索分析：

**核心节点流水线**：

```
SearchNode（初步搜索）
    → FormattingNode（结构化格式化）
    → ReflectionSummaryNode（反思总结，max_reflections=2）
    → FirstSummaryNode（首次段落总结）
    → SummaryNode（最终总结输出）
```

**工具集**：
- 国内搜索引擎 API（百度、必应中文）
- 国际搜索引擎 API（Google、Bing）
- 配置参数：`max_search_results=15`，`max_content_length=8000`

**反思机制**：Agent 会对初次搜索结果进行自我批判，识别信息缺口后补充搜索（最多 2 轮反思）。

---

### 2.5 舆情分析（InsightEngine + SentimentAnalysisModel）

InsightEngine 是核心的舆情分析引擎，对本地数据库进行深度挖掘。

#### 情感分析技术栈

系统集成了 5 种情感分析方法，优先级递增：

| 方法 | 模型 | 特点 |
|------|------|------|
| 传统机器学习 | SVM/LSTM | 速度最快，精度最低 |
| BERT-LoRA | `BertChinese-LoRA` | 中文语境，强泛化 |
| GPT-2-LoRA | `GPT2-LoRA` | 生成式情感表达 |
| Qwen3-LoRA | `WeiboSentiment_SmallQwen` | 小参数但语义理解强 |
| 多语言 | `tabularisai/multilingual-sentiment-analysis` | **默认使用**，支持22种语言 |

#### WeiboMultilingualSentimentAnalyzer 核心实现

**5级情感分类**：
```python
sentiment_map = {
    0: "非常负面",
    1: "负面",
    2: "中性",
    3: "正面",
    4: "非常正面"
}
```

**分析流程**：
1. `initialize()` → 加载 `tabularisai/multilingual-sentiment-analysis`（首次下载，后续本地缓存）
2. `_select_device()` → 优先 CUDA > MPS > CPU
3. `analyze_single_text(text)` → tokenizer编码 → softmax分类 → 返回 `SentimentResult`
4. `analyze_batch(texts)` → 批量处理，返回 `BatchSentimentResult`（含成功率、置信度均值）
5. `analyze_query_results(query_results)` → 专为 MediaCrawlerDB 返回结果设计，输出情感分布统计

#### 批量分析输出示例

```json
{
  "sentiment_analysis": {
    "total_analyzed": 450,
    "success_rate": "450/500",
    "average_confidence": 0.8734,
    "sentiment_distribution": {
      "正面": 128,
      "负面": 220,
      "中性": 89,
      "非常负面": 13
    },
    "summary": "共分析450条内容，主要情感倾向为'负面'(220条，占48.9%)",
    "high_confidence_results": [...]
  }
}
```

---

### 2.6 图谱分析：ForumEngine 协作机制

ForumEngine 实现了 BettaFish 中最独特的"多 Agent 论坛协作"机制，这是一种隐式的"动态知识图谱"。

#### LogMonitor 监控原理

ForumEngine 通过监控三个日志文件构建 Agent 间知识传递网络：

```
insight.log ──╮
media.log  ──╬──► ForumEngine(LogMonitor) ──► forum.log ──► 所有Agent读取
query.log  ──╯
```

**关键实现细节**：
1. 每 1 秒轮询三个日志文件大小变化
2. 识别 `FirstSummaryNode`（首次总结）或 `ReflectionSummaryNode`（反思总结）产出的 JSON
3. 过滤 ERROR 块（遇到 ERROR 日志即暂停，直到下一个 INFO 出现）
4. 从 JSON 中提取 `paragraph_latest_state` 或 `updated_paragraph_latest_state` 字段
5. 写入 `forum.log`，带时间戳和来源标签（`[INSIGHT]`, `[MEDIA]`, `[QUERY]`）

#### 主持人（HOST）触发机制

```python
host_speech_threshold = 5  # 每5条Agent发言触发一次主持人发言
```

LLM 主持人（`llm_host.py`中的 `generate_host_speech`）读取最近 5 条 Agent 发言，生成引导性问题或总结，写入 forum.log，标记为 `[HOST]`，所有 Agent 通过 `forum_reader` 工具读取并调整研究方向。

这形成了一个**隐式多跳知识图谱**：
- 节点：每条 Agent 分析段落
- 边：HOST 引导的话题关联
- 传播：后续 Agent 通过读取 forum.log 继承前序分析

---

### 2.7 ReportEngine：中间表示（IR）报告生成

**Document IR（中间表示）装订流程**：

```
LLM 选模板
    │
    ├── template_selection_node → 从 report_template/ 选最合适模板
    ├── document_layout_node   → 设计标题/目录/主题
    ├── word_budget_node       → 规划各章节字数
    └── chapter_generation_node → 逐章生成 JSON 块

章节 JSON 校验（ir/validator.py）
    │
    ▼
stitcher.py → 装订为 Document IR
    │
    ├── html_renderer.py → 交互式 HTML（含 SVG 图表）
    ├── pdf_renderer.py  → PDF（WeasyPrint）
    └── md_renderer      → Markdown
```

**IR Schema 亮点**：
- 支持多种块类型：文本块、图表块（SVG矢量）、表格块、引用块
- 章节级 JSON 校验，发现问题立即修复
- 支持增量重生成（`regenerate_latest_html.py` 跳过分析阶段直接重渲染）

---

## 三、MiroFish 深度分析

### 3.1 系统整体架构

```
用户上传（BettaFish报告/PDF/文档）+ 预测需求
    │
    ├── [接口1] OntologyGenerator → 本体生成（LLM，10实体+10关系定义）
    │
    ├── [接口2] GraphBuilderService → 图谱构建（Zep Cloud API）
    │         ├── 文本分块（chunk_size=500, overlap=50）
    │         ├── 批量写入 EpisodeData（batch_size=3）
    │         └── 轮询等待 episode.processed 完成
    │
    ├── [接口3] OasisProfileGenerator → Agent人设生成
    │         └── 从图谱节点生成有独立人格/记忆/行为的Agent配置
    │
    ├── [接口4] SimulationConfigGenerator → 模拟配置生成
    │         ├── 时间配置（total_simulation_hours, minutes_per_round）
    │         └── Agent行为参数注入
    │
    ├── [接口5] SimulationRunner → OASIS双平台并行模拟
    │         ├── Twitter仿真平台
    │         └── Reddit仿真平台
    │
    ├── [接口6] ReportAgent → 预测报告生成
    │         └── 与模拟后环境深度交互，生成预测报告
    │
    └── [接口7] 深度互动模式
              ├── 与任意模拟Agent对话
              └── 与ReportAgent对话
```

**技术栈**：Flask + Node.js + Python 3.11 + Zep Cloud + OASIS + uv

---

### 3.2 数据获取与对齐：图谱构建（GraphBuilderService）

MiroFish 的"数据获取"是从 BettaFish 生成的报告（或任意文档）中提取知识，构建知识图谱。

#### 本体生成（OntologyGenerator）

LLM（temperature=0.3）基于以下约束设计本体：

| 约束 | 内容 |
|------|------|
| 实体类型数量 | **精确 10 个** |
| 兜底类型 | 最后 2 个必须是 `Person`（个人兜底）和 `Organization`（组织兜底） |
| 实体必须可发声 | 只能是真实主体（人、企业、机构、媒体），不能是抽象概念 |
| 关系类型数量 | 6-10 个（UPPER_SNAKE_CASE 命名） |
| 属性限制 | 不可使用 `name/uuid/group_id/created_at/summary`（Zep 保留字） |

**输出结构**：
```json
{
  "entity_types": [
    {"name": "University", "description": "...", "attributes": [...], "examples": [...]},
    ...,
    {"name": "Person", "description": "Any individual not fitting other types"},
    {"name": "Organization", "description": "Any organization not fitting other types"}
  ],
  "edge_types": [
    {"name": "WORKS_FOR", "source_targets": [{"source": "Person", "target": "University"}]},
    ...
  ],
  "analysis_summary": "..."
}
```

#### 图谱构建（GraphBuilderService）

使用 **Zep Cloud** 作为图谱数据库，关键流程：

```python
1. create_graph(name)           # 生成 graph_id = "mirofish_{uuid16}"
2. set_ontology(graph_id, ontology)  # 动态创建 EntityModel / EdgeModel 子类
3. split_text(text, 500, 50)    # TextProcessor 分块
4. add_text_batches(graph_id, chunks, batch_size=3)  # 每批3块，间隔1秒
5. _wait_for_episodes(uuids)    # 轮询 episode.processed，每3秒检查，超时600秒
6. _get_graph_info(graph_id)    # 获取节点数/边数/实体类型分布
```

**Zep 图谱数据模型**：
- **节点（Node）**：uuid, name, labels（实体类型列表）, summary, attributes, created_at
- **边（Edge）**：uuid, name（关系类型）, fact（关系描述文本）, source_node_uuid, target_node_uuid, valid_at, invalid_at, expired_at, episodes

---

### 3.3 事件分析：OASIS 双平台社会模拟（SimulationRunner）

#### 仿真架构

MiroFish 使用 **OASIS**（CAMEL-AI 开源框架）驱动双平台并行模拟：

```
SimulationRunner
    ├── run_twitter_simulation.py   → Twitter 推文/转发/点赞 仿真
    ├── run_reddit_simulation.py    → Reddit 帖子/评论/投票 仿真
    └── run_parallel_simulation.py  → 双平台并行（默认）
```

**Agent 动作类型**（`AgentAction`）：
- `CREATE_POST` / `LIKE_POST` / `RETWEET` / `COMMENT` / `FOLLOW`
- 每个动作记录：round_num, timestamp, platform, agent_id, agent_name, action_args, success

**时间配置**：
- `total_simulation_hours`：本次模拟跨越的虚拟时间（默认 72 小时）
- `minutes_per_round`：每轮代表的虚拟时间（默认 30 分钟）
- `total_rounds = total_hours * 60 / minutes_per_round`（默认 144 轮）

#### 实时状态监控

`SimulationRunState` 跟踪：
- 各平台独立轮次：`twitter_current_round`, `reddit_current_round`
- 各平台独立时间：`twitter_simulated_hours`, `reddit_simulated_hours`
- 完成状态：`Twitter/Reddit platform_completed`（通过 `simulation_end` 事件检测）
- 最近 50 条动作记录（`recent_actions`）

**进程管理**：
- Windows：`taskkill /F /T /PID` 终止进程树
- Unix：`os.killpg(pgid, SIGTERM)` 终止进程组（`start_new_session=True`）

#### 图谱记忆动态更新

启用 `enable_graph_memory_update=True` 后，每个 Agent 的动作实时写入 Zep 图谱：

```python
ZepGraphMemoryManager.create_updater(simulation_id, graph_id)
# 监控线程每2秒读取 actions.jsonl
graph_updater.add_activity_from_dict(action_data, platform)
```

Agent 的社交行为（谁和谁互动、转发了什么、评论了什么）成为图谱中的时序边（带 `valid_at/invalid_at`）。

---

### 3.4 舆情分析：Zep 图谱记忆系统（ZepEntityReader + ZepTools）

`zep_entity_reader.py` 和 `zep_tools.py` 提供对模拟后图谱的深度查询能力：

**主要功能**：
1. **实体检索**：按实体类型、名称、属性筛选图谱节点
2. **关系路径查询**：多跳图遍历，找到实体间的间接关联路径
3. **时序事实查询**：检索特定时间窗口内的图谱边（valid_at 过滤）
4. **Agent 记忆读取**：通过 Zep 的用户记忆 API 读取单个 Agent 在模拟期间的长期记忆

**ReportAgent 工具集**（`report_agent.py`，99KB，最大服务文件）：
- 可以向模拟世界中的任意 Agent 发起对话
- 查询图谱中的关键节点和关系链路
- 基于模拟日志和图谱数据生成预测报告

---

### 3.5 图谱分析：知识图谱可视化

MiroFish 实现了完整的图谱数据导出，前端可视化包含：

```python
# get_graph_data() 返回
{
  "graph_id": "mirofish_abc123",
  "nodes": [
    {
      "uuid": "node-uuid",
      "name": "武汉大学",
      "labels": ["University"],
      "summary": "...",
      "attributes": {"full_name": "武汉大学", "role": "一流大学"},
      "created_at": "2026-03-08T10:00:00"
    }
  ],
  "edges": [
    {
      "uuid": "edge-uuid",
      "name": "WORKS_FOR",
      "fact": "张教授就职于武汉大学计算机学院",
      "source_node_name": "张教授",
      "target_node_name": "武汉大学",
      "valid_at": "2024-01-01",
      "attributes": {}
    }
  ],
  "node_count": 156,
  "edge_count": 432
}
```

---

## 四、整体数据流贯通分析

### 4.1 完整链路图

```
[Phase 0: 数据采集] MindSpider
    BroadTopicExtraction → 热点关键词 (daily_topics表)
    DeepSentimentCrawling → 7平台×14表 原始内容+评论

[Phase 1: 数据对齐] InsightEngine/MediaCrawlerDB
    search_hot_content     → 按加权热度排序
    search_topic_globally  → 全库关键词召回
    get_comments_for_topic → 评论精提取
    keyword_optimizer      → Qwen关键词扩展

[Phase 2: 事件分析] QueryEngine + MediaEngine + InsightEngine 并行
    外部搜索Agent  → 网页热点事件梳理
    多模态Agent    → 短视频/图片/结构化卡片解析
    数据库Agent    → 本地历史舆情深挖
    (三路并行, 最多2轮反思)

[Phase 3: 舆情分析] SentimentAnalysisModel
    WeiboMultilingualSentiment → 22语言5级情感分类
    输出：sentiment_distribution + high_confidence_results

[Phase 4: 协作调度] ForumEngine
    监控三引擎日志 → 提取SummaryNode输出
    每5条Agent发言 → HOST主持人LLM生成引导
    forum.log → 全局共享知识空间

[Phase 5: 图谱分析] 隐式知识图谱
    论坛交流形成 → 话题关联图（隐式）
    InsightEngine知识 ←→ QueryEngine发现 ←→ MediaEngine洞察

[Phase 6: 报告生成] ReportEngine
    模板选择 → 布局设计 → 章节生成 → IR装订 → HTML/PDF/MD

══ BettaFish 输出报告 ══════════════════════════════════════════════

[Phase 7: 图谱重建] MiroFish OntologyGenerator + GraphBuilderService
    分析报告文本 → 设计本体（10实体+10关系）
    文本分块 → Zep Cloud EpisodeData → 知识图谱

[Phase 8: 人设生成] OasisProfileGenerator
    图谱节点 → Agent人格/记忆/行为参数

[Phase 9: 社会仿真] SimulationRunner + OASIS
    Twitter + Reddit 双平台并行
    N轮（默认144轮=72虚拟小时）Agent自由演化
    图谱记忆动态更新（Agent行为→图谱边）

[Phase 10: 预测分析] ReportAgent
    图谱查询 + Agent对话 → 预测报告
    "哪些节点影响力最大?" / "舆情会如何演化?"
```

### 4.2 三大分析维度的技术实现对比

| 维度 | BettaFish 实现 | MiroFish 实现 |
|------|---------------|---------------|
| **事件分析** | QueryEngine（外部搜索+反思）+ MediaEngine（多模态）| SimulationRunner（事件传播仿真）|
| **舆情分析** | WeiboMultilingualSentiment（5级分类，22语言）| ZepGraphMemory（Agent行为时序图谱）|
| **图谱分析** | ForumEngine（隐式论坛知识图谱）| Zep Cloud（显式实体关系图谱）|

---

## 五、关键技术亮点分析

### 5.1 BettaFish 亮点

#### ① 无缝异步数据库访问

`InsightEngine/utils/db.py` 使用 SQLAlchemy 异步引擎实现只读查询封装，通过 `run_until_complete` 在同步上下文中安全调用：

```python
# 支持 PostgreSQL (asyncpg) 和 MySQL (asyncmy)
# 时间戳统一处理：ms/sec/str/date_str 四种格式自动转换
```

#### ② 跨平台热度统一计算

每个平台的互动字段名各不相同，通过映射表统一处理：
```python
mapping = {
    'likes': ['liked_count', 'like_count', 'voteup_count'],
    'comments': ['video_comment', 'comments_count', 'comment_count'],
    'shares': ['video_share_count', 'shared_count', 'total_forwards'],
    ...
}
```

#### ③ Forum 并发安全写入

`write_to_forum_log` 使用 `threading.Lock` 防止三个 Agent 线程并发写入冲突，所有内容单行化（换行符转为 `\n` 字符串）。

#### ④ 多层 JSON 容错解析

面对 LLM 输出的不规则 JSON，实现状态机修复算法（`fix_json_string`），处理未转义双引号等常见问题。

### 5.2 MiroFish 亮点

#### ① Zep 保留字防御

动态构建 Pydantic 模型时，自动检测 Zep 保留属性名并添加前缀：
```python
RESERVED_NAMES = {'uuid', 'name', 'group_id', 'name_embedding', 'summary', 'created_at'}
def safe_attr_name(attr_name):
    if attr_name.lower() in RESERVED_NAMES:
        return f"entity_{attr_name}"  # 自动重命名
```

#### ② 双平台仿真独立状态追踪

Twitter 和 Reddit 各自有独立的 `actions.jsonl` 日志，通过文件存在性判断平台是否启用，避免硬编码。

#### ③ Windows/Unix 跨平台进程管理

- Windows：`taskkill /F /T /PID`（终止完整进程树）
- Unix：`os.killpg(pgid, SIGKILL)`（终止进程组）
- 使用 `PYTHONUTF8=1` 环境变量解决 Windows UTF-8 编码问题

#### ④ 图谱记忆时序建模

通过 `valid_at`/`invalid_at`/`expired_at` 字段支持知识图谱时序演化，可以回放舆情事件历史、查询特定时刻的知识状态。

---

## 六、局限性与潜在改进

### 6.1 BettaFish 局限

| 问题 | 影响 | 建议改进 |
|------|------|---------|
| MindSpider 串行两阶段 | 话题提取失败则无法爬取 | 增加断点续传，分离关键词库 |
| 情感分析单点依赖 | 仅 1 个默认模型 | 多模型集成投票提升准确率 |
| ForumEngine 轮询 1 秒 | 高并发下可能丢帧 | 改为 inotify/watchdog 文件监听 |
| 无流量控制 | 爬虫可能触发平台封禁 | 增加自适应速率限制和 UA 轮换 |

### 6.2 MiroFish 局限

| 问题 | 影响 | 建议改进 |
|------|------|---------|
| Zep Cloud 强依赖 | 无法离线运行 | 支持 Neo4j 等本地图数据库 |
| OASIS 单机运行 | 大规模 Agent 内存占用高 | 分布式 Agent 调度 |
| 报告生成无流式输出 | 长报告等待时间长 | SSE 流式章节推送 |
| 本体设计固定 10 实体 | 特定场景可能不足 | 动态本体扩展 |

---

## 七、总结

BettaFish + MiroFish 构建了一套技术路线清晰、场景互补的完整舆情分析与预测系统：

- **BettaFish** 从"爬、挖、分、报"四个维度实现了对当前舆情的全面捕获与分析，ForumEngine 的论坛协作机制是最具创新性的设计
- **MiroFish** 将 BettaFish 的分析报告作为种子，通过知识图谱构建和社会仿真，将分析延伸到"未来预测"，Zep Cloud 的时序图谱结合 OASIS 的多 Agent 仿真是其技术核心

两者结合，共同回答了以下三个核心问题：
1. **事件分析**："已经发生了什么？"（数据采集+三引擎并行分析）
2. **舆情分析**："大众的情感倾向是什么？"（WeiboMultilingual 5级情感分类）
3. **图谱分析**："谁影响了谁？未来会怎样？"（Zep知识图谱 + OASIS社会仿真）

---

*报告生成时间: 2026-03-08 | 分析工具: 源码静态分析 + 文档解读*
