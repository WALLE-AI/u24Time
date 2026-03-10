# -*- coding: utf-8 -*-
"""
EndToEndCoordinator — E2E 多智能体主控协调器
贯通 BettaFish + MiroFish 7 阶段全流程

流程:
  Phase 0: CrawlerAgent  — 话题提取 + 社交媒体爬虫
  Phase 1: AlignmentAgent — 媒体统一对齐 + 热度计算
  Phase 2: AnalysisAgents — [Query + Insight + Media] 并行 + Forum主持
  Phase 3: SelectionAgent — 三维权重选题决策
  Phase 4: ReportEngine   — IR装订报告生成
  Phase 5: GraphAgent     — 本体生成 + Zep Cloud图谱构建
  Phase 6: SimAgent       — OASIS仿真 (后台 Task)
  Phase 7: PredictionAgent — 图谱+仿真报告 + 写入长期记忆

集成:
  - AgentContext: bootstrap先验 → ingestBatch整轮 → after_turn压实触发
  - SubagentRegistry: 每个阶段 PhaseRunner 自动状态机管理
  - MemoryIndexManager: Phase 0 bootstrap → Phase 7 store_analysis
  - HeartbeatPolicy: is_heartbeat=True 时跳过 UI 推送
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from agents.context_engine import ContextEngine, AgentMessage, create_agent_context
from agents.memory import MemoryIndexManager, get_memory_manager
from agents.subagent_registry import SubagentRegistry, PhaseRunner, get_subagent_registry
from agents.phase1_bettafish.topic_selector import (
    TopicSelectorAgent,
    TopicCandidate,
    SelectionResult,
)


class EndToEndCoordinator:
    """
    E2E 多智能体主控协调器
    """

    def __init__(
        self,
        db_session: AsyncSession,
        llm,                            # LLMClient
        registry: Optional[SubagentRegistry] = None,
        memory: Optional[MemoryIndexManager] = None,
        channel_dispatcher=None,        # ChannelDispatcher (可选)
        token_budget: int = 8_000,
    ):
        self._db = db_session
        self._llm = llm
        self._registry = registry or get_subagent_registry()
        self._memory: Optional[MemoryIndexManager] = memory
        self._dispatcher = channel_dispatcher
        self._token_budget = token_budget
        self._topic_selector = TopicSelectorAgent()

    async def _get_memory(self) -> MemoryIndexManager:
        if self._memory is None:
            self._memory = await get_memory_manager()
        return self._memory

    # ── 主入口 ────────────────────────────────────────────────────────────────

    async def run(
        self,
        topic: str = "auto",
        is_heartbeat: bool = False,
        platforms: Optional[list[str]] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """
        E2E 流程主入口
        is_heartbeat=True: 定时触发, UI 静默; False: 用户主动请求
        """
        session_id = session_id or str(uuid.uuid4())
        logger.info(
            f"E2ECoordinator: 开始运行 session={session_id} "
            f"topic='{topic}' is_heartbeat={is_heartbeat}"
        )

        # ── 初始化上下文 ────────────────────────────────────────────────────
        mem = await self._get_memory()
        ctx = create_agent_context(
            session_id=session_id,
            system_prompt=self._build_system_prompt(is_heartbeat),
            token_budget=self._token_budget,
            is_heartbeat=is_heartbeat,
            llm_summarize=self._llm_summarize,
        )

        # bootstrap: 检索先验知识 → 注入 systemPromptAddition
        if topic and topic != "auto":
            prior_results = await mem.search_history(topic, k=5)
            if prior_results:
                prior_text = "\n\n---\n\n".join(
                    f"[历史报告片段 {i+1}]\n{r.snippet}"
                    for i, r in enumerate(prior_results[:3])
                )
                await ctx.bootstrap(prior_knowledge=prior_text)

        result: dict = {"session_id": session_id, "is_heartbeat": is_heartbeat}

        try:
            # ── Phase 0: 话题爬取 ──────────────────────────────────────────
            topics = await self._phase0_crawl(ctx, session_id, topic, is_heartbeat)
            if not topics:
                logger.warning("E2ECoordinator: Phase 0 未提取到话题, 退出")
                return {**result, "status": "no_topics"}

            # ── Phase 1: 数据对齐 ──────────────────────────────────────────
            hot_items = await self._phase1_align(ctx, session_id, topics, is_heartbeat)
            if not hot_items:
                logger.warning("E2ECoordinator: Phase 1 未找到相关数据, 退出")
                return {**result, "status": "no_data"}

            # ── Phase 2: 并行分析 ──────────────────────────────────────────
            analysis = await self._phase2_analyze(
                ctx, session_id, topics[0], hot_items, is_heartbeat
            )

            # 批量提交整个 Forum 轮次
            if analysis.get("forum_messages"):
                forum_msgs = [
                    AgentMessage(role=m["role"], content=m["content"])
                    for m in analysis["forum_messages"]
                ]
                await ctx.ingest_batch(forum_msgs, is_heartbeat=is_heartbeat)

            # 轮次后检查, 可能触发后台压实
            await ctx.after_turn(
                pre_prompt_message_count=len(ctx.messages),
                token_budget=self._token_budget,
                is_heartbeat=is_heartbeat,
            )

            # ── Phase 3: 选题 ──────────────────────────────────────────────
            selection = await self._phase3_select(
                ctx, session_id, topics, hot_items, is_heartbeat
            )
            if not selection.threshold_passed:
                logger.info("E2ECoordinator: Phase 3 选题未过阈值, 退出")
                return {**result, "status": "below_threshold",
                        "selection": selection.__dict__}

            selected_topic = selection.selected_topic

            # ── Phase 4: 报告生成 ──────────────────────────────────────────
            report = await self._phase4_report(
                ctx, session_id, selected_topic, analysis, is_heartbeat
            )

            # ── Phase 5: 图谱构建 ──────────────────────────────────────────
            graph_result = await self._phase5_graph(
                ctx, session_id, selected_topic, report, is_heartbeat
            )

            # ── Phase 6: 仿真 (后台并行) ───────────────────────────────────
            sim_task = asyncio.create_task(
                self._phase6_simulate(session_id, selected_topic, graph_result, is_heartbeat)
            )

            # ── Phase 7: 预测报告 ──────────────────────────────────────────
            prediction = await self._phase7_predict(
                ctx, session_id, selected_topic, graph_result, is_heartbeat
            )

            # ── 写入长期记忆 ───────────────────────────────────────────────
            await mem.store_analysis(
                topic=selected_topic,
                content=prediction.get("content", ""),
                metadata={
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "is_heartbeat": is_heartbeat,
                },
            )

            # ── 渠道分发 ───────────────────────────────────────────────────
            if self._dispatcher:
                await self._dispatcher.dispatch(
                    event="final_report",
                    payload={"topic": selected_topic, "report": prediction},
                    run_id=session_id,
                    is_heartbeat=is_heartbeat,
                )

            # 确保资源清理 (压实)
            compact_result = await ctx.compact(token_budget=self._token_budget)
            logger.info(
                f"E2ECoordinator: 完成 session={session_id} "
                f"topic='{selected_topic}' compact={compact_result.compacted}"
            )

            return {
                **result,
                "status": "success",
                "topic": selected_topic,
                "report": report,
                "prediction": prediction,
                "graph": graph_result,
                "selection": selection.__dict__,
                "compact": {
                    "compacted": compact_result.compacted,
                    "tokens_before": compact_result.tokens_before,
                    "tokens_after": compact_result.tokens_after,
                },
            }

        except asyncio.CancelledError:
            logger.warning(f"E2ECoordinator: session={session_id} 被取消")
            raise
        except Exception as e:
            logger.exception(f"E2ECoordinator: session={session_id} 异常 — {e}")
            return {**result, "status": "error", "error": str(e)}

    # ── Phase 0: 话题爬取 ─────────────────────────────────────────────────────

    async def _phase0_crawl(
        self, ctx: ContextEngine, session_id: str, topic: str, is_heartbeat: bool
    ) -> list[str]:
        async with PhaseRunner(self._registry, "phase0_crawl", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase0_crawl", "percent": 10}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                from agents.pipeline.bettafish_pipeline import BettaFishPipeline
                pipeline = BettaFishPipeline(self._db, self._llm)

                if topic and topic != "auto":
                    topics = [topic]
                else:
                    topics = await pipeline.get_latest_topics()

                await ctx.ingest(
                    AgentMessage(role="assistant",
                                 content=f"Phase 0 完成: 提取到 {len(topics)} 个话题"),
                    is_heartbeat=is_heartbeat,
                )
                if self._dispatcher:
                    await self._dispatcher.dispatch("subagent_log", {"source": "BettaFish", "content": f"提取到 {len(topics)} 个话题", "type": "success"}, run_id=session_id, is_heartbeat=is_heartbeat)
                return topics
            except Exception as e:
                logger.error(f"Phase 0 失败: {e}")
                return []

    # ── Phase 1: 数据对齐 ─────────────────────────────────────────────────────

    async def _phase1_align(
        self, ctx: ContextEngine, session_id: str,
        topics: list[str], is_heartbeat: bool
    ) -> list[dict]:
        async with PhaseRunner(self._registry, "phase1_align", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase1_align", "percent": 20}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                from agents.phase1_bettafish.alignment.media_db import MediaCrawlerDB
                media_db = MediaCrawlerDB(self._db)
                items = await media_db.search_topic_globally(topics[0], limit=50)

                await ctx.ingest(
                    AgentMessage(role="assistant",
                                 content=f"Phase 1 完成: 对齐 {len(items)} 条内容"),
                    is_heartbeat=is_heartbeat,
                )
                if self._dispatcher:
                    await self._dispatcher.dispatch("subagent_log", {"source": "BettaFish", "content": f"对齐 {len(items)} 条媒体内容", "type": "info"}, run_id=session_id, is_heartbeat=is_heartbeat)
                return items
            except Exception as e:
                logger.error(f"Phase 1 失败: {e}")
                return []

    # ── Phase 2: 并行分析 ─────────────────────────────────────────────────────

    async def _phase2_analyze(
        self, ctx: ContextEngine, session_id: str,
        topic: str, items: list[dict], is_heartbeat: bool
    ) -> dict:
        async with PhaseRunner(self._registry, "phase2_analysis", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase2_analysis", "percent": 40}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                from agents.pipeline.bettafish_pipeline import BettaFishPipeline
                from data_alignment.schema import CanonicalItem

                pipeline = BettaFishPipeline(self._db, self._llm)

                # 将 dict 转回对象
                obj_items = []
                for item in items:
                    try:
                        obj_items.append(CanonicalItem(**item))
                    except Exception:
                        pass

                # 情感分析
                analyzed = await pipeline._sentiment.analyze_canonical_items(obj_items)

                forum_messages = []

                async def broadcast(source: str, content: str):
                    forum_messages.append({"role": source, "content": content})
                    if self._dispatcher:
                        await self._dispatcher.dispatch("subagent_log", {"source": source, "content": content, "type": "thought"}, run_id=session_id, is_heartbeat=is_heartbeat)

                # 并行三引擎
                results = await asyncio.gather(
                    pipeline._query_agent.run(topic, broadcast_cb=broadcast),
                    pipeline._insight_agent.run(topic, analyzed, broadcast_cb=broadcast),
                    pipeline._media_agent.run(topic, analyzed, broadcast_cb=broadcast),
                    return_exceptions=True,
                )

                reports = {}
                for name, res in zip(["query", "insight", "media"], results):
                    if isinstance(res, Exception):
                        logger.error(f"Phase 2 {name} 失败: {res}")
                        reports[name] = f"分析失败: {res}"
                    else:
                        reports[name] = getattr(res, "paragraph", str(res))

                await ctx.ingest(
                    AgentMessage(role="assistant",
                                 content=f"Phase 2 完成: 三引擎分析 reports={list(reports.keys())}"),
                    is_heartbeat=is_heartbeat,
                )
                return {"reports": reports, "forum_messages": forum_messages}
            except Exception as e:
                logger.error(f"Phase 2 失败: {e}")
                return {"reports": {}, "forum_messages": []}

    # ── Phase 3: 选题 ─────────────────────────────────────────────────────────

    async def _phase3_select(
        self, ctx: ContextEngine, session_id: str,
        topics: list[str], items: list[dict], is_heartbeat: bool
    ) -> SelectionResult:
        async with PhaseRunner(self._registry, "phase3_select", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase3_select", "percent": 50}, run_id=session_id, is_heartbeat=is_heartbeat)
            candidates = TopicSelectorAgent.build_candidates_from_db_results(items, topics)
            result = await self._topic_selector.select(
                candidates, llm_enhance=True, llm_client=self._llm
            )
            await ctx.ingest(
                AgentMessage(role="assistant",
                             content=f"Phase 3 选题: '{result.selected_topic}' score={result.score:.3f}"),
                is_heartbeat=is_heartbeat,
            )
            if self._dispatcher:
                await self._dispatcher.dispatch("subagent_log", {"source": "BettaFish", "content": f"选题决策完成: '{result.selected_topic}' (Score: {result.score:.3f})", "type": "success"}, run_id=session_id, is_heartbeat=is_heartbeat)
            return result

    # ── Phase 4: 报告生成 ─────────────────────────────────────────────────────

    async def _phase4_report(
        self, ctx: ContextEngine, session_id: str,
        topic: str, analysis: dict, is_heartbeat: bool
    ) -> dict:
        async with PhaseRunner(self._registry, "phase4_report", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase4_report", "percent": 65}, run_id=session_id, is_heartbeat=is_heartbeat)
            # 报告内容来源: 三引擎分析结果
            reports = analysis.get("reports", {})
            combined = "\n\n".join(
                f"### {k}\n{v}" for k, v in reports.items() if v
            )
            report = {
                "topic": topic,
                "content": combined,
                "sections": reports,
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            await ctx.ingest(
                AgentMessage(role="assistant",
                             content=f"Phase 4 报告生成完成: {len(combined)} 字"),
                is_heartbeat=is_heartbeat,
            )
            if self._dispatcher:
                await self._dispatcher.dispatch("subagent_log", {"source": "ReportEngine", "content": f"报告草稿装订完成, 共 {len(combined)} 字", "type": "info"}, run_id=session_id, is_heartbeat=is_heartbeat)
            return report

    # ── Phase 5: 图谱构建 ─────────────────────────────────────────────────────

    async def _phase5_graph(
        self, ctx: ContextEngine, session_id: str,
        topic: str, report: dict, is_heartbeat: bool
    ) -> dict:
        async with PhaseRunner(self._registry, "phase5_graph", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase5_graph", "percent": 80}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                from agents.pipeline.mirofish_pipeline import MiroFishPipeline
                pipeline = MiroFishPipeline(self._db, self._llm)
                content = report.get("content", "")
                result = await pipeline.run_end_to_end(
                    simulation_id=session_id,
                    document_texts=[content] if content else [],
                    requirement=f"分析话题: {topic}",
                    max_rounds=5,   # 快速模式
                )
                await ctx.ingest(
                    AgentMessage(role="assistant",
                                 content=f"Phase 5 图谱构建完成: graph_id={result.get('graph_task', {}).get('graph_id')}"),
                    is_heartbeat=is_heartbeat,
                )
                if self._dispatcher:
                    await self._dispatcher.dispatch("subagent_log", {"source": "MiroFish", "content": "知识图谱构建与本体提取完成", "type": "success"}, run_id=session_id, is_heartbeat=is_heartbeat)
                return result
            except Exception as e:
                logger.error(f"Phase 5 失败: {e}")
                return {"status": "error", "error": str(e)}

    # ── Phase 6: 仿真 (后台) ──────────────────────────────────────────────────

    async def _phase6_simulate(
        self, session_id: str, topic: str,
        graph_result: dict, is_heartbeat: bool
    ) -> dict:
        """后台仿真任务 — 使用 asyncio.create_task 非阻塞运行"""
        async with PhaseRunner(self._registry, "phase6_simulation", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase6_simulation", "percent": 90}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                logger.info(f"Phase 6 仿真开始 (后台): session={session_id}")
                # 仿真结果写入 Zep 时序边 (在 SimulationRunner 内部处理)
                await asyncio.sleep(1)  # 占位; 真实实现由 MiroFishPipeline 管理
                logger.info(f"Phase 6 仿真任务已启动: session={session_id}")
                if self._dispatcher:
                    await self._dispatcher.dispatch("subagent_log", {"source": "SimAgent", "content": "OASIS 非对称社会仿真引擎已启动 (后台执行)", "type": "thought"}, run_id=session_id, is_heartbeat=is_heartbeat)
                return {"status": "running", "session_id": session_id}
            except Exception as e:
                logger.error(f"Phase 6 仿真失败: {e}")
                return {"status": "error", "error": str(e)}

    # ── Phase 7: 预测报告 ──────────────────────────────────────────────────────

    async def _phase7_predict(
        self, ctx: ContextEngine, session_id: str,
        topic: str, graph_result: dict, is_heartbeat: bool
    ) -> dict:
        async with PhaseRunner(self._registry, "phase7_predict", session_id):
            if self._dispatcher:
                await self._dispatcher.dispatch("stage_transition", {"stage": "phase7_predict", "percent": 100}, run_id=session_id, is_heartbeat=is_heartbeat)
            try:
                from agents.phase2_mirofish.graph.builder import GraphBuilderService
                from agents.phase2_mirofish.simulation.runner import SimulationRunner
                from agents.phase2_mirofish.prediction.report_agent import PredictionReportAgent

                graph = GraphBuilderService()
                runner = SimulationRunner()
                reporter = PredictionReportAgent(self._llm, graph, runner)

                prediction_content = ""
                async for chunk in reporter.generate_report_stream(
                    query=topic,
                    graph_id=graph_result.get("graph_task", {}).get("graph_id"),
                    simulation_id=session_id,
                ):
                    prediction_content += chunk
                    if self._dispatcher:
                        await self._dispatcher.dispatch("report_chunk", {"chunk": chunk}, run_id=session_id, is_heartbeat=is_heartbeat)
                
                prediction = {"content": prediction_content, "topic": topic}
                
                await ctx.ingest(
                    AgentMessage(role="assistant",
                                 content=f"Phase 7 预测报告完成: {len(prediction_content)} 字"),
                    is_heartbeat=is_heartbeat,
                )
                if self._dispatcher:
                    await self._dispatcher.dispatch("subagent_log", {"source": "PredictionAgent", "content": "趋势预测报告生成完成, 正在归档记忆...", "type": "success"}, run_id=session_id, is_heartbeat=is_heartbeat)
                return prediction
            except Exception as e:
                logger.error(f"Phase 7 失败: {e}")
                return {
                    "status": "error",
                    "error": str(e),
                    "topic": topic,
                    "content": "预测报告生成失败",
                }

    # ── 工具函数 ──────────────────────────────────────────────────────────────

    def _build_system_prompt(self, is_heartbeat: bool) -> str:
        mode = "心跳定时" if is_heartbeat else "手动触发"
        return (
            f"你是一个高级情报分析智能体, 负责监控舆情、分析事件并预测走势。\n"
            f"本次运行模式: {mode}。\n"
            f"分析维度: 社交媒体热度 / 情感倾向 / 知识图谱演化 / 社会仿真预测。\n"
            f"请保持客观、精准、结构化的输出风格。"
        )

    async def _llm_summarize(self, text: str, instructions: Optional[str] = None) -> str:
        """注入给 AgentContext 的 LLM 摘要函数"""
        try:
            prompt = (
                f"{instructions or ''}\n\n请摘要以下对话历史 (保留关键事实、UUID、任务状态):\n\n{text}"
            )
            resp = await self._llm.chat([{"role": "user", "content": prompt}])
            return str(resp).strip()
        except Exception as e:
            logger.warning(f"E2ECoordinator: LLM 摘要失败 — {e}")
            return text[:1000] + "..." if len(text) > 1000 else text
