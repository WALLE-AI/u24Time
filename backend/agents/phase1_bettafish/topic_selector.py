# -*- coding: utf-8 -*-
"""
TopicSelectorAgent — 三维权重选题决策
基于热度 × 情感 × 事件分析指标, 从候选话题中优先选取最值得深度分析的主题

选题维度:
  - 热度维度: hotness_score (0-100) + 平台覆盖广度
  - 情感维度: 情感强度 (绝对值) + 情感分布一致性
  - 事件维度: 事件类型权重 + 发展阶段系数
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger


# ─── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class TopicCandidate:
    """候选话题"""
    keyword: str
    hotness_score: float = 0.0          # 0-100
    platform_count: int = 1             # 覆盖平台数
    article_count: int = 0              # 相关文章数
    sentiment_mean: float = 0.0         # 情感均值 [-1, 1]
    sentiment_std: float = 0.0          # 情感标准差 (越大越分裂)
    sentiment_intensity: float = 0.0    # |sentiment_mean| (极性强度)
    event_type: str = "general"         # breaking/developing/ongoing/general
    event_weight: float = 1.0           # 事件类型权重
    rank: int = 999
    metadata: dict = field(default_factory=dict)


@dataclass
class SelectionResult:
    """选题结果"""
    selected_topic: str
    score: float
    candidates: list[dict]
    rationale: str
    threshold_passed: bool
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ─── 事件类型权重表 ───────────────────────────────────────────────────────────

EVENT_TYPE_WEIGHTS = {
    "breaking":   2.0,   # 突发事件 — 最高优先
    "developing": 1.6,   # 持续发展中
    "crisis":     1.8,   # 危机/舆情爆发
    "policy":     1.4,   # 政策公告
    "economic":   1.3,   # 经济事件
    "ongoing":    1.1,   # 持续进行中
    "general":    1.0,   # 一般话题
    "historical": 0.7,   # 历史性回顾
}


# ─── 主类 ──────────────────────────────────────────────────────────────────────

class TopicSelectorAgent:
    """
    三维权重选题决策器

    综合评分公式:
      score = w_hot × hot_score
             + w_sentiment × sentiment_score
             + w_event × event_score

    其中:
      hot_score       = (hotness_score/100) × log(platform_count+1) × article_boost
      sentiment_score = sentiment_intensity × (1 + sentiment_std × 0.5)
                       (极性越强+争议越大, 优先级越高)
      event_score     = event_weight × phase_multiplier
    """

    def __init__(
        self,
        weight_hotness: float = 0.5,
        weight_sentiment: float = 0.25,
        weight_event: float = 0.25,
        min_score_threshold: float = 0.15,
        max_hotness: float = 100.0,
    ):
        self._w_hot       = weight_hotness
        self._w_sentiment = weight_sentiment
        self._w_event     = weight_event
        self._threshold   = min_score_threshold
        self._max_hotness = max_hotness

    def score_candidate(self, candidate: TopicCandidate) -> float:
        """计算单个候选话题的综合评分"""
        import math

        # 热度维度
        norm_hotness = min(1.0, candidate.hotness_score / self._max_hotness)
        platform_boost = math.log(candidate.platform_count + 1) / math.log(8)  # 最多7平台
        article_boost = min(1.3, 1.0 + math.log(candidate.article_count + 1) / 10.0)
        hot_score = norm_hotness * platform_boost * article_boost

        # 情感维度 (极性越强 + 分歧越大 → 舆情价值越高)
        intensity = min(1.0, abs(candidate.sentiment_mean))
        controversy_bonus = min(0.5, candidate.sentiment_std * 0.5)
        sentiment_score = intensity + controversy_bonus

        # 事件维度
        event_weight = EVENT_TYPE_WEIGHTS.get(candidate.event_type, 1.0)
        event_score = min(1.0, event_weight / 2.0)  # 归一化到 [0,1]

        total = (
            self._w_hot       * hot_score
            + self._w_sentiment * sentiment_score
            + self._w_event     * event_score
        )
        return round(total, 4)

    async def select(
        self,
        candidates: list[TopicCandidate],
        llm_enhance: bool = False,
        llm_client=None,
    ) -> SelectionResult:
        """
        从候选话题列表中选择最优主题

        Args:
            candidates: 候选话题列表 (来自 TopicExtractor)
            llm_enhance: 是否使用 LLM 辅助判断
            llm_client: LLM 客户端 (可选)

        Returns:
            SelectionResult 包含选中话题和评分理由
        """
        if not candidates:
            return SelectionResult(
                selected_topic="",
                score=0.0,
                candidates=[],
                rationale="没有候选话题",
                threshold_passed=False,
            )

        # 批量计算评分
        scored = []
        for c in candidates:
            score = self.score_candidate(c)
            scored.append((c, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        best_candidate, best_score = scored[0]
        threshold_passed = best_score >= self._threshold

        # LLM 增强 (可选)
        rationale = self._build_rationale(best_candidate, best_score, threshold_passed)
        if llm_enhance and llm_client and threshold_passed:
            try:
                rationale = await self._llm_rationale(
                    best_candidate, best_score, scored[:5], llm_client
                )
            except Exception as e:
                logger.warning(f"TopicSelector: LLM 增强失败 — {e}")

        logger.info(
            f"TopicSelector: 选题完成 → '{best_candidate.keyword}' "
            f"score={best_score:.3f} threshold_passed={threshold_passed}"
        )

        return SelectionResult(
            selected_topic=best_candidate.keyword if threshold_passed else "",
            score=best_score,
            candidates=[
                {
                    "keyword": c.keyword,
                    "score": round(s, 4),
                    "hotness": c.hotness_score,
                    "event_type": c.event_type,
                    "platforms": c.platform_count,
                }
                for c, s in scored[:10]
            ],
            rationale=rationale,
            threshold_passed=threshold_passed,
        )

    def _build_rationale(
        self,
        candidate: TopicCandidate,
        score: float,
        passed: bool,
    ) -> str:
        """构建规则化选题理由"""
        lines = [
            f"候选话题: '{candidate.keyword}'",
            f"综合评分: {score:.3f} (阈值: {self._threshold})",
            f"热度分: {candidate.hotness_score:.1f}/100, 跨 {candidate.platform_count} 平台",
            f"情感: mean={candidate.sentiment_mean:.2f}, "
            f"intensity={candidate.sentiment_intensity:.2f}",
            f"事件类型: {candidate.event_type} (权重×{EVENT_TYPE_WEIGHTS.get(candidate.event_type, 1.0)})",
        ]
        if not passed:
            lines.append(f"⚠️ 未达到最低阈值 {self._threshold}, 建议等待后续数据更新")
        return "\n".join(lines)

    async def _llm_rationale(
        self,
        best: TopicCandidate,
        score: float,
        top5: list,
        llm_client,
    ) -> str:
        """LLM 增强选题理由生成"""
        candidates_text = "\n".join(
            f"  {i+1}. {c.keyword} (score={s:.3f}, hot={c.hotness_score:.0f})"
            for i, (c, s) in enumerate(top5)
        )
        prompt = (
            f"你是一名资深新闻编辑，请根据以下候选话题数据选择最值得深度报道的主题，"
            f"并给出 2-3 句专业分析理由。\n\n"
            f"候选话题 (按综合评分排序):\n{candidates_text}\n\n"
            f"已选定: '{best.keyword}' (综合评分={score:.3f})\n\n"
            f"请简述选择该话题的理由 (50字以内):"
        )
        try:
            resp = await llm_client.chat([{"role": "user", "content": prompt}])
            return resp.strip()
        except Exception:
            return self._build_rationale(best, score, True)

    # ── 话题候选构建工具 ──────────────────────────────────────────────────────

    @staticmethod
    def build_candidates_from_db_results(
        db_items: list[dict],
        keywords: list[str],
    ) -> list[TopicCandidate]:
        """
        从数据库检索结果和关键词列表构建候选话题
        db_items: CanonicalItemModel.to_dict() 列表
        keywords: TopicExtractor 提取的关键词列表
        """
        from collections import defaultdict
        import math

        # 按关键词聚合统计
        kw_stats: dict[str, dict] = defaultdict(lambda: {
            "hotness_sum": 0.0,
            "count": 0,
            "sentiment_sum": 0.0,
            "sentiment_sq_sum": 0.0,
            "platforms": set(),
        })

        for item in db_items:
            for kw in keywords:
                if kw.lower() in (item.get("title", "") + " " + (item.get("body", "") or "")).lower():
                    stats = kw_stats[kw]
                    stats["hotness_sum"] += item.get("hotness_score", 0.0)
                    stats["count"] += 1
                    if item.get("sentiment") is not None:
                        stats["sentiment_sum"] += item["sentiment"]
                        stats["sentiment_sq_sum"] += item["sentiment"] ** 2
                    platform = item.get("source_id", "unknown").split(".")[0]
                    stats["platforms"].add(platform)

        candidates = []
        for i, kw in enumerate(keywords):
            stats = kw_stats.get(kw, {})
            n = max(1, stats.get("count", 1))
            hot = min(100.0, stats.get("hotness_sum", 0.0) / n)
            s_mean = stats.get("sentiment_sum", 0.0) / n
            s_var = stats.get("sentiment_sq_sum", 0.0) / n - s_mean ** 2
            s_std = math.sqrt(max(0.0, s_var))

            candidates.append(TopicCandidate(
                keyword=kw,
                hotness_score=hot,
                platform_count=len(stats.get("platforms", {kw})),
                article_count=n,
                sentiment_mean=s_mean,
                sentiment_std=s_std,
                sentiment_intensity=abs(s_mean),
                event_type="general",
                rank=i,
            ))

        return candidates
