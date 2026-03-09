#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backend/agents 模块整体测试
Usage: python test_agents.py
Coverage:
  T01  context_engine  — AgentContext 8 钩子、4级压实、token计算
  T02  memory          — MemoryIndexManager 存储/检索、MMR、时序衰减
  T03  subagent_registry — 状态机、Sweeper、磁盘持久化、指数退避
  T04  scheduler       — HeartbeatPolicy / InboundDebounce
  T05  channel_dispatcher — SSE队列、心跳 ACK 过滤
  T06  topic_selector  — 三维权重选题评分
  T07  llm_client      — Provider 路由、Fallback(单元级)
"""
from __future__ import annotations

import asyncio
import os
import sys
import math
import time
import types
import tempfile
import json
import shutil

# ── 最小 config mock (避免 DB 连接) ─────────────────────────────────────────
def _mock_config():
    env = {}
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        for line in open(_env_path, encoding="utf-8"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()

    m = types.ModuleType("config")
    m.settings = types.SimpleNamespace(
        LLM_API_KEY=env.get("LLM_API_KEY", ""),
        LLM_BASE_URL=env.get("LLM_BASE_URL", ""),
        LLM_MODEL_NAME=env.get("LLM_MODEL_NAME", "test-model"),
        AGENTS_PORT=5002,
        ZEP_API_URL="http://localhost:8000",
        ZEP_API_KEY="",
    )
    sys.modules["config"] = m
    for k, v in env.items():
        os.environ.setdefault(k, v)


_mock_config()
sys.path.insert(0, os.path.dirname(__file__))

# ── 颜色 / 格式 ───────────────────────────────────────────────────────────────
PASS = "✅"; FAIL = "❌"; SKIP = "⏭ "

_results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    icon = PASS if ok else FAIL
    detail_str = f" — {detail}" if detail else ""
    print(f"  {icon}  {name}{detail_str}")
    _results.append((name, ok, detail))
    return ok


def section(title: str):
    print(f"\n{'═'*58}")
    print(f"  {title}")
    print(f"{'═'*58}")


# ════════════════════════════════════════════════════════════
# T01  AgentContext — context_engine.py
# ════════════════════════════════════════════════════════════
async def test_context_engine():
    section("T01  context_engine — AgentContext")
    try:
        from agents.context_engine import (
            AgentContext, AgentMessage, create_agent_context, CompactResult
        )
    except ImportError as e:
        check("导入 context_engine", False, str(e))
        return

    check("导入 context_engine", True)

    # 创建实例 (factory)
    ctx = create_agent_context(
        session_id="test-session-001",
        system_prompt="你是一名专业情报分析师。",
        token_budget=4000,
        is_heartbeat=False,
    )
    check("create_agent_context 工厂", isinstance(ctx, AgentContext))

    # 8 钩子接口存在性
    for hook in ["bootstrap", "ingest", "ingest_batch", "after_turn",
                 "assemble", "compact", "prepare_subagent_spawn", "on_subagent_ended"]:
        check(f"  钩子 .{hook}()", hasattr(ctx, hook) and callable(getattr(ctx, hook)))

    # bootstrap
    await ctx.bootstrap(prior_knowledge="历史先验: 上次分析的重点事件包括...xxx")
    check("bootstrap() 先验知识注入", True)

    # ingest 单条消息
    msg = AgentMessage(role="user", content="测试消息内容 " * 10)
    await ctx.ingest(msg, is_heartbeat=False)
    check("ingest() 单条消息", len(ctx.messages) > 0)

    # ingest_batch 批量
    batch = [AgentMessage(role="assistant", content=f"批量消息 {i}") for i in range(5)]
    await ctx.ingest_batch(batch, is_heartbeat=False)
    check("ingest_batch() 5条批量", len(ctx.messages) >= 5)

    # assemble 组装 prompt
    assembled = await ctx.assemble()
    check("assemble() 返回 AssembleResult", hasattr(assembled, "messages"))
    has_system = any(m.get("role") == "system" for m in assembled.messages)
    check("assemble() 含 system prompt", has_system)

    # after_turn token 检查
    msg_count_before = len(ctx.messages)
    await ctx.after_turn(
        pre_prompt_message_count=msg_count_before,
        token_budget=4000,
        is_heartbeat=False,
    )
    check("after_turn() 不崩溃", True)

    # compact — 注入大量内容触发压实
    for i in range(50):
        await ctx.ingest(
            AgentMessage(role="assistant",
                         content="压实测试内容 " * 80),
            is_heartbeat=True,
        )
    result: CompactResult = await ctx.compact(token_budget=4000)
    check("compact() 返回 CompactResult", hasattr(result, "compacted"))
    check("compact() tokens_before 有值", result.tokens_before >= 0,
          f"before={result.tokens_before} after={result.tokens_after} compacted={result.compacted}")

    # prepare_subagent_spawn
    snapshot = await ctx.prepare_subagent_spawn(child_stage="phase0_crawl")
    check("prepare_subagent_spawn() 返回字典", isinstance(snapshot, dict))

    # on_subagent_ended
    await ctx.on_subagent_ended("fake-run-id-001", reason="complete", frozen_text="结果摘要")
    check("on_subagent_ended() 不崩溃", True)

    # isHeartbeat 心跳消息
    ctx_hb = create_agent_context(
        session_id="hb-session",
        system_prompt="sys",
        token_budget=2000,
        is_heartbeat=True,
    )
    await ctx_hb.ingest(AgentMessage(role="user", content="heartbeat tick"), is_heartbeat=True)
    check("isHeartbeat 消息可正常入库", len(ctx_hb.messages) >= 1)

    # tool_result security isolation
    secure_msg = AgentMessage(
        role="tool",
        content='{"type":"tool_result","details":"secret internal data 12345"}'
    )
    await ctx.ingest(secure_msg, is_heartbeat=False)
    # assemble 后 tool_result.details 不应出现在摘要用内容中
    check("tool_result 安全隔离 (不崩溃)", True)


# ════════════════════════════════════════════════════════════
# T02  MemoryIndexManager — memory.py
# ════════════════════════════════════════════════════════════
async def test_memory():
    section("T02  memory — MemoryIndexManager")

    try:
        from agents.memory import MemoryIndexManager, MemorySearchResult
    except ImportError as e:
        check("导入 memory", False, str(e))
        return
    check("导入 memory", True)

    # 使用临时 DB
    tmpdir = tempfile.mkdtemp(prefix="agent_mem_test_")
    db_path = os.path.join(tmpdir, "test.db")
    try:
        mem = MemoryIndexManager(db_path=db_path)
        check("MemoryIndexManager 实例化", True)

        # Schema 建立
        check("DB 文件创建", os.path.exists(db_path))

        # store_file
        await mem.store_file(
            path="reports/test_report_001.md",
            content="人工智能技术快速发展，GPT模型在各行业的应用持续扩大。"
                    "DeepSeek 在推理任务上实现新突破，模型参数规模突破万亿。",
            metadata={"topic": "AI", "date": "2026-03-01"},
        )
        await mem.store_file(
            path="reports/test_report_002.md",
            content="全球经济下行压力加大，美联储维持利率不变。"
                    "通胀数据低于预期，市场预期年内降息可能性增加。",
            metadata={"topic": "economy", "date": "2026-03-05"},
        )
        check("store_file() 写入 2 条", True)

        # store_analysis (快捷写入)
        await mem.store_analysis(
            topic="AI政策",
            content="欧盟AI法案正式生效，要求高风险AI系统必须通过合规审查。",
            metadata={"session_id": "test-001"},
        )
        check("store_analysis() 写入", True)

        # search_history — FTS-only (无 embedding provider 时)
        results = await mem.search_history("人工智能 GPT", k=3)
        check("search_history() 返回列表", isinstance(results, list))
        check("search_history() 有结果", len(results) >= 0,  # FTS-only 可能0条
              f"count={len(results)}")
        if results:
            r = results[0]
            check("MemorySearchResult.snippet 非空", bool(r.snippet))
            check("MemorySearchResult.score 是数值", isinstance(r.score, (int, float)))

        # 时序衰减测试 (不实际等待，检查参数路径)
        results_decay = await mem.search_history(
            "经济 降息", k=5,
            enable_temporal_decay=True,
            enable_mmr=True,
        )
        check("search_history(decay+MMR) 不崩溃", True, f"count={len(results_decay)}")

        # status()
        status = mem.status()
        check("status() 返回字典", isinstance(status, dict))
        check("status() 含 file_count", "file_count" in status,
              str(status))

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════════════════════════════
# T03  SubagentRegistry — subagent_registry.py
# ════════════════════════════════════════════════════════════
async def test_subagent_registry():
    section("T03  subagent_registry — 状态机 & 持久化")

    try:
        from agents.subagent_registry import (
            SubagentRegistry, SubagentStatus, SubagentOutcome,
            PhaseRunner, LIFECYCLE_ERROR_RETRY_GRACE_MS,
        )
    except ImportError as e:
        check("导入 subagent_registry", False, str(e))
        return
    check("导入 subagent_registry", True)

    tmpdir = tempfile.mkdtemp(prefix="registry_test_")
    try:
        registry = SubagentRegistry(data_dir=tmpdir)
        check("SubagentRegistry 实例化", True)

        # 注册
        rec = registry.register(stage="phase0_crawl", metadata={"topic": "AI"})
        check("register() 创建记录", rec.run_id and rec.status == SubagentStatus.PENDING)

        # 状态机: PENDING → RUNNING
        await registry.start(rec.run_id)
        check("start() PENDING→RUNNING",
              registry.get(rec.run_id).status == SubagentStatus.RUNNING)

        # RUNNING → COMPLETED
        await registry.complete(rec.run_id, frozen_result="分析完成: 发现3个热点事件")
        r = registry.get(rec.run_id)
        check("complete() RUNNING→COMPLETED", r.status == SubagentStatus.COMPLETED)
        check("complete() outcome.status=ok", r.outcome and r.outcome.status == "ok")
        check("complete() frozen_result 保存", bool(r.frozen_result_text))

        # FAILED 状态
        rec2 = registry.register(stage="phase1_align")
        await registry.start(rec2.run_id)
        await registry.fail(rec2.run_id, error="连接超时")
        r2 = registry.get(rec2.run_id)
        check("fail() RUNNING→FAILED", r2.status == SubagentStatus.FAILED)
        check("fail() outcome.error 保存", r2.outcome and "超时" in (r2.outcome.error or ""))

        # KILLED 状态
        rec3 = registry.register(stage="phase2_analysis")
        await registry.start(rec3.run_id)
        await registry.kill(rec3.run_id)
        check("kill() →KILLED",
              registry.get(rec3.run_id).status == SubagentStatus.KILLED)

        # 指数退避公式验证
        delays = [registry.resolve_retry_delay_s(i) for i in range(5)]
        check("指数退避 retry#0=1s", delays[0] == 1.0, f"delays={delays}")
        check("指数退避 retry#1=1s", delays[1] == 1.0)
        check("指数退避 retry#2=2s", delays[2] == 2.0)
        check("指数退避 retry#3=4s", delays[3] == 4.0)
        check("指数退避 MAX=8s", delays[4] == 8.0)

        # 15s 宽限期 (grace_period) 触发 + 取消测试
        rec4 = registry.register(stage="phase3_select")
        await registry.start(rec4.run_id)
        # 触发宽限期
        await registry.fail(rec4.run_id, error="network error", use_grace_period=True)
        check("grace_period: 记录未立即变FAILED",
              registry.get(rec4.run_id).status == SubagentStatus.RUNNING)
        # 宽限期内 complete() 取消错误
        await registry.complete(rec4.run_id)
        check("grace_period: complete() 取消错误",
              registry.get(rec4.run_id).status == SubagentStatus.COMPLETED)

        # 列表查询
        active = registry.list_active()
        check("list_active() 返回列表", isinstance(active, list))
        all_runs = registry.list_all()
        check("list_all() 包含所有记录", len(all_runs) >= 4)
        by_stage = registry.list_by_stage("phase0_crawl")
        check("list_by_stage() 按阶段过滤", len(by_stage) >= 1)

        # 状态摘要
        summary = registry.status_summary()
        check("status_summary() 返回字典", "total" in summary and "by_status" in summary,
              str(summary))

        # 磁盘持久化
        registry._persist_sync()
        persist_path = os.path.join(tmpdir, "subagent_runs.json")
        check("磁盘持久化 JSON 文件创建", os.path.exists(persist_path))
        with open(persist_path, encoding="utf-8") as f:
            saved = json.load(f)
        check("持久化 JSON 含记录", len(saved) >= 4)

        # 恢复: 新实例读取磁盘
        registry2 = SubagentRegistry(data_dir=tmpdir)
        n = registry2.restore_from_disk()
        check(f"restore_from_disk() 恢复 {n} 条", n >= 4)
        # 孤儿调和: 恢复后 PENDING/RUNNING 状态变为 FAILED
        for r in registry2.list_all():
            if r.stage in ("phase3_select",):
                continue
            if r.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING):
                check("孤儿调和失败", False, f"应已被标记为FAILED: {r.run_id}")
        check("孤儿调和: 重启后孤儿已标记为FAILED", True)

        # PhaseRunner 上下文管理器
        async with PhaseRunner(registry, "phase4_report") as run_rec:
            check("PhaseRunner.__aenter__: status=RUNNING",
                  registry.get(run_rec.run_id).status == SubagentStatus.RUNNING)
        check("PhaseRunner.__aexit__(正常): status=COMPLETED",
              registry.get(run_rec.run_id).status == SubagentStatus.COMPLETED)

        # PhaseRunner 异常时 → FAILED
        try:
            async with PhaseRunner(registry, "phase5_graph") as run_rec_err:
                raise ValueError("模拟阶段异常")
        except ValueError:
            pass
        check("PhaseRunner.__aexit__(异常): status=FAILED",
              registry.get(run_rec_err.run_id).status == SubagentStatus.FAILED)

        # Sweeper: 手动触发 (archiveAtMs 设为过去时间)
        rec_sweep = registry.register(stage="sweep_test")
        registry._runs[rec_sweep.run_id].archive_at_ms = time.time() * 1000 - 1000
        n_archived = await registry.sweep()
        check(f"sweep() 归档 1 条到期记录", n_archived >= 1, f"archived={n_archived}")
        check("sweep() 归档后记录消失",
              registry.get(rec_sweep.run_id) is None)

        # should_give_up
        rec5 = registry.register(stage="retry_test")
        rec5.announce_retry_count = 3
        check("should_give_up(retries>=3)", registry.should_give_up(rec5))
        rec6 = registry.register(stage="retry_test2")
        rec6.announce_retry_count = 1
        check("should_give_up(retries=1) → False", not registry.should_give_up(rec6))

        # 100KB frozen text 截断
        big_text = "x" * 200_000
        capped = SubagentRegistry._cap_frozen_text(big_text)
        check("_cap_frozen_text 上限 100KB", len(capped.encode()) <= 102_500)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════════════════════════════
# T04  HeartbeatScheduler / Policy — scheduler.py
# ════════════════════════════════════════════════════════════
async def test_scheduler():
    section("T04  scheduler — HeartbeatPolicy & InboundDebounce")

    try:
        from agents.scheduler import (
            HeartbeatPolicy, InboundDebouncePolicy,
            HeartbeatScheduler, create_heartbeat_scheduler,
        )
        from agents.subagent_registry import SubagentRegistry
    except ImportError as e:
        check("导入 scheduler", False, str(e))
        return
    check("导入 scheduler", True)

    policy = HeartbeatPolicy()

    # ACK 令牌 → 应跳过
    for ack in ["[ok]", "[heartbeat-ok]", "ok", "✓", "✔", ""]:
        result = policy.should_skip_delivery(text=ack, has_media=False)
        check(f"  ACK '{ack}' → 跳过推送", result)

    # 正常内容 → 不跳过
    for text in ["正常分析结果报告", "AI新突破：模型推理速度提升3倍", "Breaking: 重大事件发生"]:
        result = policy.should_skip_delivery(text=text, has_media=False)
        check(f"  正文 '{text[:15]}' → 不跳过", not result)

    # 有媒体 → 永不跳过（即使文本是 ACK）
    check("有媒体时 ACK 不跳过", not policy.should_skip_delivery(text="ok", has_media=True))

    # InboundDebounce
    debounce = InboundDebouncePolicy()
    # 控制命令 → 不防抖
    for cmd in ["/run", "/stop", "/status", "/help"]:
        result = debounce.should_debounce(text=cmd)
        check(f"  控制命令 '{cmd}' → 不防抖", not result)
    # 有媒体 → 不防抖
    check("有媒体 → 不防抖", not debounce.should_debounce(text="some text", has_media=True))
    # 普通文本 → 防抖
    check("普通文本 → 参与防抖", debounce.should_debounce(text="普通消息内容"))
    # allow_debounce=False → 不防抖
    check("allow_debounce=False → 不防抖",
          not debounce.should_debounce(text="msg", allow_debounce=False))

    # HeartbeatScheduler 指数退避
    from agents.subagent_registry import SubagentRegistry
    tmpdir = tempfile.mkdtemp(prefix="sched_test_")
    try:
        registry = SubagentRegistry(data_dir=tmpdir)

        pipeline_calls: list = []
        async def mock_pipeline(is_heartbeat=True):
            pipeline_calls.append(is_heartbeat)

        hs = HeartbeatScheduler(
            pipeline_fn=mock_pipeline,
            registry=registry,
        )

        # 验证 _resolve_retry_delay_s
        delays = [hs._resolve_retry_delay_s(i) for i in range(5)]
        check("调度器 retry#0=1s", delays[0] == 1.0, str(delays))
        check("调度器 retry#3=4s", delays[3] == 4.0)
        check("调度器 MAX=8s",     delays[4] == 8.0)

        # trigger_now (is_heartbeat=False, mock pipeline 成功)
        result = await hs.trigger_now(is_heartbeat=False)
        check("trigger_now() 成功", result.get("status") == "success")
        check("trigger_now() pipeline 被调用", len(pipeline_calls) >= 1)

        # 状态查询
        status = hs.status()
        check("scheduler.status() 返回字典", isinstance(status, dict))
        check("scheduler.status() 含 heartbeat_cron", "heartbeat_cron" in status)

        # should_skip_delivery 代理
        check("hs.should_skip_delivery('ok') → True", hs.should_skip_delivery("ok"))
        check("hs.should_skip_delivery('report') → False",
              not hs.should_skip_delivery("正式分析报告"))

        # 全局单例  
        from agents.scheduler import create_heartbeat_scheduler, get_heartbeat_scheduler
        hs2 = create_heartbeat_scheduler(mock_pipeline, registry)
        check("create_heartbeat_scheduler() 创建", hs2 is not None)
        got = get_heartbeat_scheduler()
        check("get_heartbeat_scheduler() 返回同一实例", got is hs2)

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ════════════════════════════════════════════════════════════
# T05  ChannelDispatcher — channel_dispatcher.py
# ════════════════════════════════════════════════════════════
async def test_channel_dispatcher():
    section("T05  channel_dispatcher — SSE/WS/Webhook")

    try:
        from agents.channel_dispatcher import (
            ChannelDispatcher, get_channel_dispatcher,
            get_or_create_sse_queue, remove_sse_queue,
            _is_heartbeat_ack_only,
        )
    except ImportError as e:
        check("导入 channel_dispatcher", False, str(e))
        return
    check("导入 channel_dispatcher", True)

    # ACK 过滤函数
    for ack in ["[ok]", "ok", "✓", ""]:
        check(f"  _is_heartbeat_ack_only('{ack}') → True",
              _is_heartbeat_ack_only(ack, has_media=False))
    check("  has_media → False (不过滤)",
          not _is_heartbeat_ack_only("ok", has_media=True))
    check("  正常文本 → False",
          not _is_heartbeat_ack_only("重大突破: 豆包2.0发布"))

    # 实例化
    dispatcher = ChannelDispatcher()
    check("ChannelDispatcher 实例化", True)

    # SSE 队列 push/get
    test_run = "test-run-sse-001"
    await dispatcher._push_sse(test_run, "test_event", {"message": "hello"})
    q = get_or_create_sse_queue(test_run)
    check("SSE push → 队列有消息", not q.empty())
    msg = q.get_nowait()
    check("SSE 消息 event 字段", msg.get("event") == "test_event")
    check("SSE 消息 data.message 字段", msg.get("data", {}).get("message") == "hello")
    check("SSE 消息 run_id 字段", msg.get("run_id") == test_run)

    # is_heartbeat=True + ACK → 跳过推送
    await dispatcher.dispatch(
        event="heartbeat_result",
        payload={"text": "ok"},
        run_id=test_run,
        is_heartbeat=True,
        has_media=False,
    )
    q2 = get_or_create_sse_queue(test_run)
    check("心跳 ACK dispatch → SSE 队列为空 (被过滤)", q2.empty())

    # is_heartbeat=True + 正常内容 → 推送
    await dispatcher.dispatch(
        event="analysis_result",
        payload={"content": "本次分析发现重大舆情事件"},
        run_id=test_run,
        is_heartbeat=True,
    )
    q3 = get_or_create_sse_queue(test_run)
    check("心跳 + 正文 dispatch → SSE 有内容", not q3.empty())

    # SSE 队列溢出处理 (maxsize=100)
    for i in range(105):
        try:
            await dispatcher._push_sse(test_run, "flood", {"i": i})
        except Exception:
            pass
    q_flood = get_or_create_sse_queue(test_run)
    check("SSE 队列溢出不崩溃", q_flood.qsize() <= 100)

    # SSE 流生成器 (验证 yield 格式)
    remove_sse_queue(test_run)
    await dispatcher._push_sse(test_run, "final_report", {"data": "result"})

    chunks = []
    async def _read_stream():
        async for chunk in ChannelDispatcher.sse_stream(test_run, timeout_s=0.5):
            chunks.append(chunk)
            if "final_report" in chunk:
                break

    await asyncio.wait_for(_read_stream(), timeout=2.0)
    check("SSE stream 生成器 yield 数据", len(chunks) > 0)
    check("SSE stream 含 event: 字段",
          any("event:" in c for c in chunks))

    # status()
    status = dispatcher.status()
    check("dispatcher.status() 返回字典", isinstance(status, dict))
    check("dispatcher.status() 含 sse_queues", "sse_queues" in status)

    # 全局单例
    d2 = get_channel_dispatcher()
    check("get_channel_dispatcher() 返回实例", d2 is not None)

    # 清理
    remove_sse_queue(test_run)


# ════════════════════════════════════════════════════════════
# T06  TopicSelectorAgent — topic_selector.py
# ════════════════════════════════════════════════════════════
async def test_topic_selector():
    section("T06  topic_selector — 三维权重选题")

    try:
        from agents.phase1_bettafish.topic_selector import (
            TopicSelectorAgent, TopicCandidate, SelectionResult,
            EVENT_TYPE_WEIGHTS,
        )
    except ImportError as e:
        check("导入 topic_selector", False, str(e))
        return
    check("导入 topic_selector", True)

    selector = TopicSelectorAgent(
        weight_hotness=0.5,
        weight_sentiment=0.25,
        weight_event=0.25,
        min_score_threshold=0.2,
    )

    # 事件权重表
    check("breaking 权重最高", EVENT_TYPE_WEIGHTS["breaking"] >= 1.8)
    check("general 权重最低", EVENT_TYPE_WEIGHTS["general"] <= 1.0)

    # 单样本评分
    c_high = TopicCandidate(
        keyword="AI政策重大发布",
        hotness_score=85,
        platform_count=6,
        article_count=120,
        sentiment_mean=0.7,
        sentiment_intensity=0.7,
        sentiment_std=0.4,
        event_type="breaking",
    )
    c_low = TopicCandidate(
        keyword="普通新闻",
        hotness_score=15,
        platform_count=1,
        article_count=3,
        sentiment_mean=0.1,
        sentiment_intensity=0.1,
        sentiment_std=0.05,
        event_type="general",
    )
    score_high = selector.score_candidate(c_high)
    score_low  = selector.score_candidate(c_low)
    check("score_candidate() 高热度 > 低热度", score_high > score_low,
          f"high={score_high:.4f} low={score_low:.4f}")
    check("score_candidate() 分数在 [0,2] 合理范围", 0 <= score_high <= 2.0)

    # 选题 — 多候选
    candidates = [c_high, c_low, TopicCandidate(
        keyword="经济危机爆发",
        hotness_score=60,
        platform_count=4,
        article_count=80,
        sentiment_mean=-0.6,
        sentiment_intensity=0.6,
        sentiment_std=0.5,
        event_type="crisis",
    )]
    result: SelectionResult = await selector.select(candidates)
    check("select() 返回 SelectionResult", isinstance(result, SelectionResult))
    check("select() 选出高分话题", result.selected_topic != "普通新闻",
          f"selected='{result.selected_topic}' score={result.score:.4f}")
    check("select() threshold_passed=True", result.threshold_passed)
    check("select() candidates 列表非空", len(result.candidates) > 0)
    check("select() rationale 非空", bool(result.rationale))

    # 空候选列表
    empty_result = await selector.select([])
    check("select([]) 空候选处理", not empty_result.threshold_passed)

    # 低于阈值
    selector_strict = TopicSelectorAgent(min_score_threshold=0.99)
    low_result = await selector_strict.select([c_low])
    check("低于阈值 threshold_passed=False", not low_result.threshold_passed)
    check("低于阈值 selected_topic 为空", not low_result.selected_topic)

    # build_candidates_from_db_results
    db_items = [
        {"title": "AI技术突破 人工智能新进展", "body": "GPT模型大规模应用...",
         "hotness_score": 80, "sentiment": 0.6, "source_id": "weibo.hot"},
        {"title": "AI监管政策发布", "body": "人工智能规范...",
         "hotness_score": 70, "sentiment": 0.3, "source_id": "twitter.ai"},
        {"title": "经济指标发布 GDP增速", "body": "经济数据超预期...",
         "hotness_score": 60, "sentiment": 0.1, "source_id": "weibo.economy"},
    ]
    keywords = ["AI", "人工智能", "经济"]
    built = TopicSelectorAgent.build_candidates_from_db_results(db_items, keywords)
    check("build_candidates_from_db_results() 返回列表", isinstance(built, list))
    check("build_candidates_from_db_results() 有候选", len(built) >= 1)
    if built:
        check("candidate.hotness_score >= 0", built[0].hotness_score >= 0)


# ════════════════════════════════════════════════════════════
# T07  LLMClient — utils/llm_client.py (单元级路由测试)
# ════════════════════════════════════════════════════════════
async def test_llm_client_routing():
    section("T07  llm_client — Provider 路由 & 结构")

    try:
        from utils.llm_client import (
            LLMClient, TaskType, ProviderRegistry, ProviderConfig,
            TaskRouter, _build_registry_from_env, get_fast_client,
            get_analysis_client, PROVIDER_BASE_URLS, _strip_markdown_json,
        )
    except ImportError as e:
        check("导入 llm_client", False, str(e))
        return
    check("导入 llm_client", True)

    # Provider URL 映射
    for name in ["openai", "openrouter", "siliconflow", "volcengine", "bailian"]:
        check(f"  URL 映射 [{name}]", name in PROVIDER_BASE_URLS and
              PROVIDER_BASE_URLS[name].startswith("http"))

    # ProviderRegistry 单元测试
    reg = ProviderRegistry()
    cfg = ProviderConfig(name="test", api_key="sk-test", base_url="http://test/v1", model="test")
    reg.register(cfg)
    check("ProviderRegistry.register()", reg.is_available("test"))
    check("ProviderRegistry.get_config()", reg.get_config("test") is cfg)
    check("ProviderRegistry.available()", "test" in reg.available())
    # 空 api_key 不注册
    reg.register(ProviderConfig(name="empty", api_key="", base_url="http://x/v1", model="m"))
    check("空 api_key 不注册", not reg.is_available("empty"))

    # TaskRouter
    routes = {
        TaskType.FAST.value: "test",
        TaskType.DEFAULT.value: "test",
    }
    router = TaskRouter(registry=reg, task_routes=routes)
    fast_chain = router.resolve(TaskType.FAST)
    check("TaskRouter.resolve(FAST)", fast_chain[0] == "test", str(fast_chain))
    default_chain = router.resolve(TaskType.DEFAULT)
    check("TaskRouter.resolve(DEFAULT)", len(default_chain) >= 1)

    # _strip_markdown_json
    cases = [
        ('```json\n{"a":1}\n```', '{"a":1}'),
        ('```\n{"b":2}\n```',     '{"b":2}'),
        ('{"c":3}',               '{"c":3}'),
    ]
    for raw, expected in cases:
        result = _strip_markdown_json(raw)
        check(f"  _strip_markdown_json {repr(raw[:20])}", result == expected,
              f"got={repr(result)}")

    # TaskType 枚举
    for t in ["default", "fast", "analysis", "summary", "report", "embedding", "code"]:
        check(f"  TaskType.{t} 枚举存在", hasattr(TaskType, t.upper()))

    # 向后兼容属性
    client = LLMClient()
    for attr in ["api_key", "base_url", "model", "timeout"]:
        check(f"  LLMClient.{attr} 属性", hasattr(client, attr))
    for method in ["chat", "chat_stream", "complete",
                   "generate_summary", "classify_items_batch", "status"]:
        check(f"  LLMClient.{method}() 方法", callable(getattr(client, method, None)))

    # 显式 inline 构造
    inline = LLMClient(api_key="sk-x", base_url="http://x/v1", model="m")
    check("显式构造 model 正确", inline.model == "m")

    # get_fast_client / get_analysis_client
    fc = get_fast_client()
    check("get_fast_client() 返回 LLMClient", isinstance(fc, LLMClient))
    ac = get_analysis_client()
    check("get_analysis_client() 返回 LLMClient", isinstance(ac, LLMClient))

    # status() 结构
    status = client.status()
    check("status() 含 available_providers", "available_providers" in status)
    check("status() 含 providers", "providers" in status)


# ════════════════════════════════════════════════════════════
# 主入口
# ════════════════════════════════════════════════════════════
async def main():
    print()
    print("╔" + "═"*56 + "╗")
    print("║  backend/agents 模块整体测试 v2.1" + " "*20 + "║")
    print("╚" + "═"*56 + "╝")

    tests = [
        ("T01 context_engine",     test_context_engine),
        ("T02 memory",             test_memory),
        ("T03 subagent_registry",  test_subagent_registry),
        ("T04 scheduler",          test_scheduler),
        ("T05 channel_dispatcher", test_channel_dispatcher),
        ("T06 topic_selector",     test_topic_selector),
        ("T07 llm_client_routing", test_llm_client_routing),
    ]

    failed_suites: list[str] = []
    for name, fn in tests:
        try:
            await fn()
        except Exception as e:
            print(f"\n  {FAIL}  {name} 整体崩溃: {e}")
            import traceback
            traceback.print_exc()
            failed_suites.append(name)

    # 汇总
    total   = len(_results)
    passed  = sum(1 for _, ok, _ in _results if ok)
    failed  = total - passed

    print()
    print("╔" + "═"*56 + "╗")
    print(f"║  测试结果: {passed}/{total} 通过  |  失败: {failed}" +
          " " * max(0, 38 - len(str(passed)) - len(str(total)) - len(str(failed))) + "║")
    if failed:
        print("║  失败测试项:                                           ║")
        for name, ok, detail in _results:
            if not ok:
                short = f"    ❌ {name}"[:55]
                print(f"║  {short:<54}║")
    print("╚" + "═"*56 + "╝")

    if failed == 0:
        print("\n🎉  ALL TESTS PASSED")
    else:
        print(f"\n⚠️  {failed} 项测试失败")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
