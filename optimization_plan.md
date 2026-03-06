# U24Time 架构优化方案

> 生成时间: 2026-03-06  
> 基于: `backend_deep_analysis.md` 深度分析报告  
> 优先级: P0（阻塞性）→ P1（高优先）→ P2（长期改进）

---

## 问题汇总与根因分析

| # | 问题 | 根因 | 优先级 |
|---|------|------|--------|
| 1 | **今日快报无法实时更新** | SSE 断连后无重连机制；前端监听事件名对不上；deque 写入不触发主动推送 | **P0** |
| 2 | **SQLite 高并发瓶颈** | WAL 文件 ~25MB 持续增长；REALTIME 层 1min 触发 + 多线程并发写入 | **P1** |
| 3 | **内存与 DB 数据不一致** | `news_flash_cache.appendleft()` 在 `db_session.flush()` 之前执行，DB 回滚后内存脏数据不清除 | **P1** |
| 4 | **SSE Queue 背压 / 事件丢失** | `Queue(maxsize=50)` 满时 `put_nowait()` 静默抛弃，REALTIME 源每分钟17个并发广播 | **P1** |

---

## P0 — 今日快报实时更新修复

### 根因深挖

当前「今日快报」的实现路径：

```
pipeline.align_and_save()
  → news_flash_cache.appendleft()   ← 正确，内存已更新
  → _broadcast({event: "scheduler_done", items: [...]})  ← SSE 已推送

前端: EventSource('/stream')
  → 监听 onmessage
  → 解析 data.event === "scheduler_done"  ← ✅ 事件名正确
  → 调用 refreshDomain(data.domain)       ← ✅ 触发刷新
  → GET /api/v1/newsflash                 ← ✅ 端点正确
```

**问题实际出在以下三处：**

**① SSE 连接断开后无自动重连**
```
浏览器刷新 / 网络波动 → EventSource 断开
→ 后续所有 scheduler_done 事件前端收不到
→ 页面静止，看起来"不更新"
```

**② `scheduler_done` 的 `items` 字段 domain 可能为空或错误**
```python
# scheduler.py:227-228
_raw_domain = source_id.split(".")[0]  # "tech" → 但 domain 应为 "technology"
_DOMAIN_ALIAS = {"tech": "technology"}
_domain = _DOMAIN_ALIAS.get(_raw_domain, _raw_domain)
# 但 CanonicalItem.domain 由 normalizer 写入，可能是 "" 或 None
# → 前端按 domain 过滤 newsflash 时得不到数据
```

**③ `newsflash` 端点 domain 过滤逻辑对 `technology` 不匹配**
```python
# memory_cache 中存的 item["domain"] 可能是 "technology"
# 但 scheduler._crawl() 里广播的 domain 是从 source_id 取的，
# 前端可能用中文 "技术" 去请求，而 domain_map 中映射为 "technology"
# → 若 item.domain 是 "tech"（而非 "technology"），则过滤失败
```

### 修复方案

#### Fix 1: 前端 SSE 自动重连（核心修复）

在前端 SSE 初始化代码中增加指数退避重连：

```javascript
// frontend: useSSE.js 或类似文件
class ReconnectingEventSource {
  constructor(url, options = {}) {
    this.url = url;
    this.maxDelay = options.maxDelay || 30000;
    this.delay = 1000;
    this._connect();
  }

  _connect() {
    this.es = new EventSource(this.url);
    
    this.es.onopen = () => {
      this.delay = 1000; // 重置退避延迟
      console.log('[SSE] 已连接');
    };

    this.es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      this._onData(data);
    };

    this.es.onerror = () => {
      this.es.close();
      console.warn(`[SSE] 断连，${this.delay}ms 后重试`);
      setTimeout(() => {
        this.delay = Math.min(this.delay * 2, this.maxDelay);
        this._connect();         // 指数退避重连
      }, this.delay);
    };
  }

  _onData(data) {
    // 具体业务逻辑
    if (data.event === 'scheduler_done') {
      store.dispatch('refreshDomain', data.domain);
    }
  }
}

// 使用
const sse = new ReconnectingEventSource('/stream');
```

#### Fix 2: 后端主动推送 newsflash 数据（推送而非拉取）

在 `scheduler.py` 的 `_crawl()` 完成后，**直接把 newsflash 格式数据推入 SSE**，前端无需再发 HTTP 请求：

```python
# scheduler.py: _crawl() 方法末尾，broadcast 时增加 newsflash_items 字段
if self._broadcast:
    self._broadcast({
        "event": "scheduler_done",
        "source_id": source_id,
        "domain": _domain,
        "items_count": len(items),
        "timestamp": self._last_success[source_id].isoformat(),
        # ✅ 新增: 直接携带 newsflash 格式数据
        "newsflash": [
            {
                "item_id": i.item_id,
                "title": i.title,
                "url": i.url,
                "domain": i.domain or _domain,   # fallback 到调度器推断的 domain
                "sub_domain": i.sub_domain,
                "source_id": i.source_id,
                "crawled_at": i.crawled_at.isoformat() if i.crawled_at else None,
                "published_at": i.published_at.isoformat() if i.published_at else None,
                "hotness_score": i.hotness_score,
            }
            for i in items[:10]   # 只推最新 10 条
        ],
    })
```

前端收到 `scheduler_done` 事件后，直接用 `data.newsflash` 更新状态，**零 HTTP 往返**：

```javascript
if (data.event === 'scheduler_done' && data.newsflash?.length) {
  store.commit('prependNewsFlash', {
    domain: data.domain,
    items: data.newsflash,
  });
}
```

#### Fix 3: 修复 domain 标准化一致性

```python
# pipeline.py: align_and_save() 写入 news_flash_cache 前，确保 domain 统一
_DOMAIN_ALIAS = {"tech": "technology", "technology": "technology"}

for item in reversed(items):
    # ✅ 标准化 domain，确保和 newsflash 端点过滤逻辑一致
    normalized_domain = _DOMAIN_ALIAS.get(item.domain, item.domain) or "global"
    item_dict = {
        "item_id": item.item_id,
        "title": item.title,
        "url": item.url,
        "domain": normalized_domain,   # ← 关键：统一用 technology 而非 tech
        "sub_domain": item.sub_domain,
        "source_id": item.source_id,
        "crawled_at": ...,
        "published_at": ...,
        "hotness_score": item.hotness_score,
    }
    news_flash_cache.appendleft(item_dict)
```

#### Fix 4: 前端增加页面可见性触发刷新

用户切换标签页回来后主动拉取一次：

```javascript
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') {
    fetchNewsFlash(); // 重新拉取，防止 SSE 断连期间的数据缺失
  }
});
```

---

## P1-A — 内存与 DB 不一致修复

### 根因

```python
# pipeline.py: align_and_save() 当前执行顺序
1. news_flash_cache.appendleft()    ← 内存写入
2. db_session.flush()               ← DB 写入
3. (如 flush 失败) db_session.rollback()  ← DB 回滚
   # 但 news_flash_cache 没有对应回滚！脏数据留在内存
```

### 修复方案: 事务完成后写入内存

将内存写入移到 **DB flush 成功之后**：

```python
# pipeline.py: align_and_save() 重构写入顺序

async def align_and_save(self, source_id, raw_data, meta=None, db_session=None):
    items = self.align(source_id, raw_data, meta)

    if db_session is not None and items:
        try:
            # [步骤1] 区分新旧条目
            ids = [i.item_id for i in items]
            ...（existing_info 查询逻辑不变）...

            # [步骤2] UPSERT 已有条目
            if existing_items:
                ...（update 逻辑不变）...

            # [步骤3] LLM 分类新条目
            if items_needing_llm:
                ...（llm 分类逻辑不变）...

            # [步骤4] INSERT 新条目
            for item in new_items:
                db_session.add(CanonicalItemModel(...))

            # [步骤5] flush → 成功后才写内存  ✅ 关键修改
            await db_session.flush()

            # ✅ 仅在 DB flush 成功后更新内存缓存
            self._update_news_flash_cache(items)

            logger.info(f"AlignmentPipeline: 写入 {len(new_items)} 条 + 更新内存缓存")

        except Exception as e:
            logger.error(f"AlignmentPipeline: DB 写入失败 source={source_id} err={e}")
            await db_session.rollback()
            # ❌ 不写内存缓存，因为 DB 没有成功
            raise

    else:
        # 无 DB session 时（测试/离线模式）照常写内存
        self._update_news_flash_cache(items)

    return items


def _update_news_flash_cache(self, items: list[CanonicalItem]):
    """将 CanonicalItem 列表写入内存缓存（幂等、线程安全）"""
    from memory_cache import news_flash_cache
    _DOMAIN_ALIAS = {"tech": "technology"}

    for item in reversed(items):
        normalized_domain = _DOMAIN_ALIAS.get(item.domain, item.domain) or "global"
        item_dict = {
            "item_id": item.item_id,
            "title": item.title,
            "url": item.url,
            "domain": normalized_domain,
            "sub_domain": item.sub_domain,
            "source_id": item.source_id,
            "crawled_at": item.crawled_at.isoformat() if item.crawled_at else None,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "hotness_score": item.hotness_score,
        }
        # 队内去重
        cache_list = list(news_flash_cache)
        for old in cache_list:
            if old["item_id"] == item.item_id:
                try:
                    news_flash_cache.remove(old)
                except ValueError:
                    pass
                break
        news_flash_cache.appendleft(item_dict)
```

> **权衡说明**: 此修改让内存与 DB 强一致，代价是：若 DB 写入失败，当次采集的新数据不会出现在 newsflash 中（但下次成功采集时会补充）。这比"内存有脏数据"更符合预期行为。

---

## P1-B — SSE Queue 背压修复

### 根因

```python
# main.py:67
def _broadcast(event: dict):
    with _sse_lock:
        dead: list[queue.Queue] = []
        for q in _sse_clients:
            try:
                q.put_nowait(event)   # ← Queue(maxsize=50) 满时抛 Full 异常
            except queue.Full:
                dead.append(q)         # ← 直接认为客户端死了！移除连接
        for q in dead:
            _sse_clients.remove(q)
```

**问题**: `Queue.Full` 不代表客户端死了，只是消费速度跟不上。在 REALTIME 层（1分钟并发 17 个源）时，每分钟约 17 次广播，Queue(50) 很容易积满。

### 修复方案

#### 方案A: 扩大 Queue 并分级投递（推荐，改动最小）

```python
# main.py: 扩大 Queue + 区分重要事件

_HIGH_PRIORITY_EVENTS = {"scheduler_done", "connected", "health_check_done"}

def _broadcast(event: dict):
    event_type = event.get("event", "")
    with _sse_lock:
        dead: list[queue.Queue] = []
        for q in _sse_clients:
            try:
                if event_type in _HIGH_PRIORITY_EVENTS:
                    q.put_nowait(event)               # 重要事件：必须投递
                else:
                    # 低优先级事件（align_start/align_done 等）：满了就丢
                    if not q.full():
                        q.put_nowait(event)
            except queue.Full:
                # 重要事件的 Queue.Full 才认为客户端死亡
                if event_type in _HIGH_PRIORITY_EVENTS:
                    dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

# 同时扩大 Queue 容量
@app.route("/stream")
def sse_stream():
    client_q: queue.Queue = queue.Queue(maxsize=200)  # 50 → 200
    ...
```

#### 方案B: 改用事件去重（合并同源同类事件）

```python
# 对于同一 source_id 的连续 scheduler_done，只保留最新一条
def _broadcast(event: dict):
    with _sse_lock:
        for q in _sse_clients:
            # 检查 queue 中是否已有同 source_id 的 scheduler_done
            if event.get("event") == "scheduler_done":
                source_id = event.get("source_id")
                existing = list(q.queue)
                # 移除旧的同源事件（防止堆积）
                for old in existing:
                    if (old.get("event") == "scheduler_done" and
                            old.get("source_id") == source_id):
                        try:
                            q.queue.remove(old)
                        except ValueError:
                            pass
                        break
            try:
                q.put_nowait(event)
            except queue.Full:
                pass
```

---

## P1-C — SQLite 并发性能优化

### 当前问题

```
WAL 文件: u24time.db-wal = 25MB（应定期 CHECKPOINT）
并发写入: REALTIME 层每分钟 ~17 个任务并发，SQLite 写锁互斥
asyncio + threading 混合: 多线程写入同一 SQLite 连接池
```

### 短期优化（不更换数据库）

#### 优化1: 开启 WAL 自动 CHECKPOINT

```python
# db/session.py: 创建 engine 时增加 WAL pragma

from sqlalchemy import event as sa_event

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_size=5,          # 限制并发连接数
    max_overflow=10,
    pool_timeout=30,
)

# 新连接时自动设置 WAL + CHECKPOINT 阈值
@sa_event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")      # 比 FULL 快 3x，安全性可接受
    cursor.execute("PRAGMA wal_autocheckpoint=1000") # 1000页后自动 checkpoint
    cursor.execute("PRAGMA cache_size=-64000")       # 64MB 页缓存
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()
```

#### 优化2: 写操作串行化（防止锁竞争）

```python
# scheduler.py: 为 writes 添加异步锁

import asyncio
_db_write_lock = asyncio.Lock()

async def _crawl(self, source_id: str):
    ...
    async with _db_write_lock:          # ← 串行化写入，避免锁超时
        if self._db_factory:
            async with self._db_factory() as db_session:
                items = await self._dispatch_crawl(source_id, db_session=db_session)
```

> **注意**: 此方案限制了并发写入性能，但对于 SQLite 单文件数据库这是正确的取舍。

#### 优化3: 定时 CHECKPOINT 任务

```python
# scheduler.py: 注册定时 CHECKPOINT

self._scheduler.add_job(
    func=self._checkpoint_db,
    trigger="interval",
    minutes=30,
    id="sqlite_checkpoint",
)

def _checkpoint_db(self):
    """定期执行 SQLite WAL checkpoint，防止 WAL 文件无限增长"""
    from db.session import get_sync_session
    try:
        with get_sync_session() as session:
            session.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            logger.info("SQLite WAL checkpoint 完成")
    except Exception as e:
        logger.warning(f"WAL checkpoint 失败: {e}")
```

### 长期方案：迁移 PostgreSQL（推荐路线图）

| 阶段 | 工作 | 收益 |
|------|------|------|
| Phase 1 | 配置 `config.py` 支持 `DATABASE_URL` 切换（已有） | 0 代码改动切换 |
| Phase 2 | 部署 PostgreSQL 15（Docker 1行命令） | 真正的并发写入 |
| Phase 3 | 利用 PostgreSQL `LISTEN/NOTIFY` 替代轮询 | SSE 推送从应用层下沉到 DB 层 |
| Phase 4 | 为 `canonical_items` 增加 `BRIN` 索引（时序数据） | 时间范围查询快 10x |

```bash
# Docker 一键启动 PostgreSQL
docker run -d \
  --name u24time-pg \
  -e POSTGRES_DB=u24time \
  -e POSTGRES_USER=u24time \
  -e POSTGRES_PASSWORD=your_password \
  -p 5432:5432 \
  postgres:15-alpine

# .env 修改
DATABASE_URL=postgresql+asyncpg://u24time:your_password@localhost/u24time
```

---

## 优化实施路线图

```
第1天 (P0): 前端今日快报实时性修复
  ├── Fix 1: 前端 SSE 自动重连（30分钟）
  ├── Fix 2: backend scheduler_done 携带 newsflash 数据（20分钟）
  └── Fix 3: domain 标准化一致性（10分钟）

第2天 (P1): 后端稳定性修复
  ├── P1-A: pipeline.py 内存写入移到 DB flush 之后（30分钟）
  ├── P1-B: SSE Queue 扩容 + 分级投递（20分钟）
  └── P1-C: SQLite pragma 优化 + WAL checkpoint（30分钟）

第3-7天 (P2): 长期改进
  └── 迁移 PostgreSQL（视运维资源决定）
```

---

## 各修复影响范围评估

| 修复 | 改动文件 | 改动行数 | 风险 |
|------|---------|---------|------|
| SSE 重连 | 前端 useSSE.js | ~30行 | 🟢 低，纯新增 |
| newsflash 数据随 SSE 推送 | scheduler.py | ~15行 | 🟢 低，新增字段向后兼容 |
| domain 标准化 | pipeline.py | ~5行 | 🟢 低 |
| 内存写入后移 | pipeline.py | ~40行重排 | 🟡 中，需测试 DB 失败回滚场景 |
| SSE Queue 扩容 | main.py | ~10行 | 🟢 低 |
| SQLite pragma | db/session.py | ~10行 | 🟡 中，重启后生效 |
| 迁移 PostgreSQL | db/session.py + .env | ~20行 | 🔴 高，需数据迁移 |
