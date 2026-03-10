# -*- coding: utf-8 -*-
"""
AgentContext — 可插拔上下文管理引擎
深度参考 OpenClaw src/context-engine/types.ts + src/agents/compaction.ts

实现 ContextEngine 完整 8 钩子接口:
  bootstrap / ingest / ingest_batch / after_turn /
  assemble / compact / prepare_subagent_spawn / on_subagent_ended

压实策略 (4 级):
  Level 1 pruneHistoryForContextShare   — 历史裁剪 (maxHistoryShare=0.5)
  Level 2 summarizeChunks               — 分块 LLM 摘要
  Level 3 summarizeWithFallback         — 渐进降级 (跳过 oversized)
  Level 4 summarizeInStages             — 多阶段合并摘要

安全:
  - toolResult details 永不泄露至摘要 LLM
  - SAFETY_MARGIN = 1.2 补偿 Token 估算偏差
  - tokenBudget 动态检查, 超过 85% 触发后台压实
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from loguru import logger

# ─── 常量 (对齐 OpenClaw compaction.ts) ──────────────────────────────────────
BASE_CHUNK_RATIO          = 0.4    # pruneHistory 基础分块比
MIN_CHUNK_RATIO           = 0.15   # 大消息场景最小分块比
SAFETY_MARGIN             = 1.2    # Token 估算安全系数
SUMMARIZATION_OVERHEAD    = 4096   # 留给摘要 LLM 的额外 Token
DEFAULT_TOKEN_BUDGET      = 8_000  # 默认上下文预算
MAX_HISTORY_SHARE         = 0.5    # 历史消息最多占上下文比例
COMPACT_TRIGGER_RATIO     = 0.85   # 超过预算的 85% 时触发后台压实
FROZEN_TEXT_MAX_BYTES     = 100 * 1024  # 冻结结果 100 KB 上限

MERGE_SUMMARIES_INSTRUCTIONS = (
    "Merge these partial summaries into a single cohesive summary.\n\n"
    "MUST PRESERVE:\n"
    "- Active tasks and their current status (in-progress, blocked, pending)\n"
    "- Batch operation progress (e.g., '5/17 items completed')\n"
    "- The last thing the user requested and what was being done about it\n"
    "- Decisions made and their rationale\n"
    "- TODOs, open questions, and constraints\n"
    "- Any commitments or follow-ups promised\n"
    "- All opaque identifiers exactly as written (UUIDs, hashes, IDs, URLs)\n\n"
    "PRIORITIZE recent context over older history."
)


# ─── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class AgentMessage:
    """对话消息载体"""
    role: str                             # "system" | "user" | "assistant" | "tool"
    content: str
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    is_heartbeat: bool = False
    tool_use_id: Optional[str] = None    # 兼容字段
    tool_call_id: Optional[str] = None   # OpenAI 规范: tool 消息需携带此 ID
    tool_calls: Optional[list[dict]] = None # OpenAI 规范: assistant 消息可能携带此列表
    detail: Optional[str] = None         # tool_result 详情 (摘要时剥离)

    def to_dict(self) -> dict:
        d = {
            "role": self.role,
            "content": self.content,
        }
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass
class AssembleResult:
    messages: list[dict]
    estimated_tokens: int
    system_prompt_addition: Optional[str] = None


@dataclass
class CompactResult:
    ok: bool
    compacted: bool
    reason: Optional[str] = None
    summary: Optional[str] = None
    first_kept_entry_id: Optional[str] = None
    tokens_before: int = 0
    tokens_after: Optional[int] = None


@dataclass
class BootstrapResult:
    bootstrapped: bool
    imported_messages: int = 0
    reason: Optional[str] = None


@dataclass
class IngestResult:
    ingested: bool


@dataclass
class IngestBatchResult:
    ingested_count: int


# ─── 接口协议 ─────────────────────────────────────────────────────────────────

@runtime_checkable
class ContextEngine(Protocol):
    """ContextEngine 接口协议 — 所有的上下文引擎必须实现此接口"""

    @property
    def messages(self) -> list[AgentMessage]: ...
    
    @property
    def total_tokens(self) -> int: ...
    
    @property
    def message_count(self) -> int: ...

    async def bootstrap(self, session_file: str = "", prior_knowledge: Optional[str] = None) -> BootstrapResult: ...
    async def ingest(self, message: AgentMessage, is_heartbeat: bool = False) -> IngestResult: ...
    async def ingest_batch(self, messages: list[AgentMessage], is_heartbeat: bool = False) -> IngestBatchResult: ...
    async def after_turn(self, pre_prompt_message_count: int = 0, token_budget: Optional[int] = None, is_heartbeat: bool = False, **kwargs) -> None: ...
    async def assemble(self, token_budget: Optional[int] = None) -> AssembleResult: ...
    async def compact(self, token_budget: Optional[int] = None, force: bool = False, custom_instructions: Optional[str] = None, compaction_target: str = "budget") -> CompactResult: ...
    async def prepare_subagent_spawn(self, parent_session_key: str, child_session_key: str, ttl_ms: Optional[int] = None) -> dict: ...
    async def on_subagent_ended(self, child_session_key: str, reason: str) -> None: ...
    def get_compacted_summary(self) -> Optional[str]: ...
    def clear(self) -> None: ...



# ─── Token 估算 ────────────────────────────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """
    简易 Token 估算 — chars/4 启发式 (与 OpenClaw estimateTokens 对齐)
    SAFETY_MARGIN 在调用侧乘以补偿
    """
    return max(1, len(text) // 4)


def estimate_message_tokens(msg: AgentMessage) -> int:
    return estimate_tokens(msg.content) + 4  # 4 Token 结构开销


def estimate_messages_tokens(messages: list[AgentMessage]) -> int:
    """SECURITY: 剥离 tool_result details 后再估算"""
    return sum(estimate_message_tokens(_strip_detail(m)) for m in messages)


def _strip_detail(msg: AgentMessage) -> AgentMessage:
    """剥离 tool_result.detail — 防止敏感/冗余内容泄露至摘要"""
    if msg.role == "tool" and msg.detail:
        return AgentMessage(
            role=msg.role, content=msg.content,
            message_id=msg.message_id, timestamp=msg.timestamp,
            is_heartbeat=msg.is_heartbeat, tool_use_id=msg.tool_use_id,
        )
    return msg


# ─── 压实辅助 ──────────────────────────────────────────────────────────────────

def _split_by_token_share(
    messages: list[AgentMessage], parts: int = 2
) -> list[list[AgentMessage]]:
    """按 Token 数均等分割消息列表"""
    if not messages:
        return []
    parts = max(1, min(parts, len(messages)))
    if parts <= 1:
        return [messages]

    total = estimate_messages_tokens(messages)
    target = total / parts
    chunks: list[list[AgentMessage]] = []
    current: list[AgentMessage] = []
    current_tokens = 0

    for msg in messages:
        mt = estimate_message_tokens(msg)
        if len(chunks) < parts - 1 and current and current_tokens + mt > target:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(msg)
        current_tokens += mt

    if current:
        chunks.append(current)
    return chunks


def _chunk_by_max_tokens(
    messages: list[AgentMessage], max_tokens: int
) -> list[list[AgentMessage]]:
    """按最大 Token 数分块 (含 SAFETY_MARGIN)"""
    if not messages:
        return []
    effective_max = max(1, int(max_tokens / SAFETY_MARGIN))
    chunks: list[list[AgentMessage]] = []
    current: list[AgentMessage] = []
    current_tokens = 0

    for msg in messages:
        mt = estimate_message_tokens(msg)
        if current and current_tokens + mt > effective_max:
            chunks.append(current)
            current = []
            current_tokens = 0
        current.append(msg)
        current_tokens += mt
        if mt > effective_max:
            chunks.append(current)
            current = []
            current_tokens = 0

    if current:
        chunks.append(current)
    return chunks


def _is_oversized(msg: AgentMessage, context_window: int) -> bool:
    """单消息 > 50% 上下文视为 oversized"""
    return estimate_message_tokens(msg) * SAFETY_MARGIN > context_window * 0.5


def _repair_tool_pairs(messages: list[AgentMessage]) -> list[AgentMessage]:
    """
    修复孤儿 tool_result (其 tool_use 已被裁剪):
    扫描 tool_use_id 配对, 无对应 tool_use 的 tool_result 一律丢弃
    """
    tool_use_ids: set[str] = set()
    for m in messages:
        if m.role == "assistant" and m.tool_use_id:
            tool_use_ids.add(m.tool_use_id)
    return [
        m for m in messages
        if not (m.role == "tool" and m.tool_use_id and m.tool_use_id not in tool_use_ids)
    ]


# ─── 摘要生成 ──────────────────────────────────────────────────────────────────

async def _generate_summary(
    messages: list[AgentMessage],
    llm_summarize: Callable[[str, Optional[str]], Any],
    custom_instructions: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> str:
    """
    单批次 LLM 摘要生成
    llm_summarize(conversation_text, instructions) -> str
    """
    if not messages:
        return previous_summary or "No prior history."

    safe_messages = [_strip_detail(m) for m in messages]
    conversation = "\n".join(
        f"[{m.role.upper()}] {m.content}" for m in safe_messages
    )
    if previous_summary:
        conversation = f"Previous summary:\n{previous_summary}\n\n---\n\n{conversation}"

    instructions = custom_instructions or MERGE_SUMMARIES_INSTRUCTIONS
    try:
        result = await llm_summarize(conversation, instructions)
        return str(result).strip() or previous_summary or "No prior history."
    except Exception as e:
        logger.warning(f"AgentContext: 摘要生成失败 — {e}")
        return previous_summary or "Summary unavailable."


async def _summarize_chunks(
    messages: list[AgentMessage],
    llm_summarize: Callable,
    max_chunk_tokens: int,
    custom_instructions: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> str:
    """分块逐批摘要 — Level 2"""
    if not messages:
        return previous_summary or "No prior history."
    safe_messages = [_strip_detail(m) for m in messages]
    chunks = _chunk_by_max_tokens(safe_messages, max_chunk_tokens)
    summary = previous_summary
    for chunk in chunks:
        summary = await _generate_summary(
            chunk, llm_summarize, custom_instructions, summary
        )
    return summary or "No prior history."


async def _summarize_with_fallback(
    messages: list[AgentMessage],
    llm_summarize: Callable,
    max_chunk_tokens: int,
    context_window: int,
    custom_instructions: Optional[str] = None,
    previous_summary: Optional[str] = None,
) -> str:
    """Level 3 渐进降级摘要"""
    if not messages:
        return previous_summary or "No prior history."
    try:
        return await _summarize_chunks(
            messages, llm_summarize, max_chunk_tokens,
            custom_instructions, previous_summary
        )
    except Exception as e:
        logger.warning(f"AgentContext: 全量摘要失败, 尝试部分摘要 — {e}")

    small_msgs = []
    oversized_notes = []
    for m in messages:
        if _is_oversized(m, context_window):
            tokens = int(estimate_message_tokens(m) * SAFETY_MARGIN)
            oversized_notes.append(
                f"[Large {m.role} (~{tokens // 1000}K tokens) omitted from summary]"
            )
        else:
            small_msgs.append(m)

    if small_msgs:
        try:
            partial = await _summarize_chunks(
                small_msgs, llm_summarize, max_chunk_tokens,
                custom_instructions, previous_summary
            )
            suffix = "\n\n" + "\n".join(oversized_notes) if oversized_notes else ""
            return partial + suffix
        except Exception as e2:
            logger.warning(f"AgentContext: 部分摘要也失败 — {e2}")

    return (
        f"Context contained {len(messages)} messages "
        f"({len(oversized_notes)} oversized). Summary unavailable due to size limits."
    )


async def _summarize_in_stages(
    messages: list[AgentMessage],
    llm_summarize: Callable,
    max_chunk_tokens: int,
    context_window: int,
    custom_instructions: Optional[str] = None,
    previous_summary: Optional[str] = None,
    parts: int = 2,
    min_messages_for_split: int = 4,
) -> str:
    """Level 4 多阶段摘要合并"""
    if not messages:
        return previous_summary or "No prior history."

    parts = max(1, min(parts, len(messages)))
    total = estimate_messages_tokens(messages)

    if parts <= 1 or len(messages) < min_messages_for_split or total <= max_chunk_tokens:
        return await _summarize_with_fallback(
            messages, llm_summarize, max_chunk_tokens,
            context_window, custom_instructions, previous_summary
        )

    splits = [c for c in _split_by_token_share(messages, parts) if c]
    if len(splits) <= 1:
        return await _summarize_with_fallback(
            messages, llm_summarize, max_chunk_tokens,
            context_window, custom_instructions, previous_summary
        )

    partial_summaries = []
    for chunk in splits:
        ps = await _summarize_with_fallback(
            chunk, llm_summarize, max_chunk_tokens,
            context_window, custom_instructions=None, previous_summary=None
        )
        partial_summaries.append(ps)

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    merge_text = "\n\n---\n\n".join(partial_summaries)
    merge_instructions = MERGE_SUMMARIES_INSTRUCTIONS
    if custom_instructions:
        merge_instructions += f"\n\nAdditional focus:\n{custom_instructions}"

    # 将各部分摘要作为 user 消息合并摘要
    merge_msgs = [
        AgentMessage(role="user", content=ps)
        for ps in partial_summaries
    ]
    return await _summarize_with_fallback(
        merge_msgs, llm_summarize, max_chunk_tokens,
        context_window, merge_instructions, None
    )


# ─── 核心引擎实现 ──────────────────────────────────────────────────────────────

class LegacyContextEngine:
    """
    实现 ContextEngine 完整接口合约的默认压实引擎
    注入 llm_summarize 可替换摘要后端
    """

    def __init__(
        self,
        session_id: str,
        system_prompt: str = "",
        token_budget: int = DEFAULT_TOKEN_BUDGET,
        is_heartbeat: bool = False,
        llm_summarize: Optional[Callable] = None,
    ):
        self.session_id = session_id
        self.system_prompt = system_prompt  # 静态层 — 不可裁减
        self.token_budget = token_budget
        self.is_heartbeat = is_heartbeat
        self._llm_summarize = llm_summarize or _default_llm_summarize

        self._messages: list[AgentMessage] = []
        self._seen_ids: set[str] = set()
        self._total_tokens: int = 0
        self._compacted_summary: Optional[str] = None
        self._system_prompt_addition: Optional[str] = None  # bootstrap 注入
        self._compact_lock = asyncio.Lock()

    # ── bootstrap ─────────────────────────────────────────────────────────────

    async def bootstrap(
        self,
        session_file: str = "",
        prior_knowledge: Optional[str] = None,
    ) -> BootstrapResult:
        """
        初始化阶段: 将先验记忆注入 systemPromptAddition
        prior_knowledge 由调用方从 MemoryIndexManager + Zep 检索汇总后传入
        """
        if not prior_knowledge:
            return BootstrapResult(bootstrapped=False, reason="no prior knowledge")

        self._system_prompt_addition = prior_knowledge.strip()
        logger.info(
            f"AgentContext[{self.session_id}]: bootstrap — "
            f"注入先验知识 {len(prior_knowledge)} 字符"
        )
        return BootstrapResult(bootstrapped=True, imported_messages=0)

    # ── ingest ────────────────────────────────────────────────────────────────

    async def ingest(
        self, message: AgentMessage, is_heartbeat: bool = False
    ) -> IngestResult:
        """单条消息入库; 重复消息返回 ingested=False"""
        if message.message_id in self._seen_ids:
            return IngestResult(ingested=False)

        message.is_heartbeat = is_heartbeat
        self._messages.append(message)
        self._seen_ids.add(message.message_id)
        self._total_tokens += estimate_message_tokens(message)
        return IngestResult(ingested=True)

    async def ingest_batch(
        self, messages: list[AgentMessage], is_heartbeat: bool = False
    ) -> IngestBatchResult:
        """整轮批量入库 — ForumEngine 完整轮次结束后一次性提交"""
        count = 0
        for msg in messages:
            result = await self.ingest(msg, is_heartbeat=is_heartbeat)
            if result.ingested:
                count += 1
        return IngestBatchResult(ingested_count=count)

    # ── after_turn ────────────────────────────────────────────────────────────

    async def after_turn(
        self,
        pre_prompt_message_count: int = 0,
        token_budget: Optional[int] = None,
        is_heartbeat: bool = False,
        **kwargs,
    ) -> None:
        """
        轮次后钩子:
        1. 更新 token_budget
        2. 超过阈值时触发后台压实
        """
        budget = token_budget or self.token_budget
        if self._total_tokens > budget * COMPACT_TRIGGER_RATIO:
            logger.info(
                f"AgentContext[{self.session_id}]: after_turn 触发后台压实 "
                f"({self._total_tokens} > {budget * COMPACT_TRIGGER_RATIO:.0f})"
            )
            asyncio.create_task(self.compact(budget))

    # ── assemble ──────────────────────────────────────────────────────────────

    async def assemble(
        self, token_budget: Optional[int] = None
    ) -> AssembleResult:
        """
        在 Token 预算内组装 messages[]:
        [system_prompt] + [systemPromptAddition] + [历史消息]
        静态层 (system/addition) 优先保留, 不可裁减
        """
        budget = token_budget or self.token_budget

        # 系统层 Token 计算
        system_tokens = estimate_tokens(self.system_prompt)
        addition_tokens = estimate_tokens(self._system_prompt_addition or "")
        compaction_tokens = estimate_tokens(self._compacted_summary or "")
        reserved = system_tokens + addition_tokens + compaction_tokens

        dynamic_budget = max(0, budget - reserved)
        kept_messages = self._fit_messages_to_budget(self._messages, dynamic_budget)

        result: list[dict] = []

        # 系统提示 (静态层)
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})

        # 先验知识注入 (不可裁减)
        if self._system_prompt_addition:
            result.append({
                "role": "system",
                "content": f"[Prior Knowledge]\n{self._system_prompt_addition}"
            })

        # 压实摘要 (已有时注入为 system 消息)
        if self._compacted_summary:
            result.append({
                "role": "system",
                "content": f"[History Summary]\n{self._compacted_summary}"
            })

        # 动态消息流
        result.extend(m.to_dict() for m in kept_messages)

        total_tokens = reserved + estimate_messages_tokens(kept_messages)
        return AssembleResult(
            messages=result,
            estimated_tokens=total_tokens,
            system_prompt_addition=self._system_prompt_addition,
        )

    def _fit_messages_to_budget(
        self, messages: list[AgentMessage], budget: int
    ) -> list[AgentMessage]:
        """从最新消息开始, 保留不超过 budget Token 的消息"""
        kept = []
        used = 0
        for msg in reversed(messages):
            mt = estimate_message_tokens(msg)
            if used + mt > budget:
                break
            kept.append(msg)
            used += mt
        return list(reversed(kept))

    # ── compact ───────────────────────────────────────────────────────────────

    async def compact(
        self,
        token_budget: Optional[int] = None,
        force: bool = False,
        custom_instructions: Optional[str] = None,
        compaction_target: str = "budget",
    ) -> CompactResult:
        """
        四级压实策略 (参考 OpenClaw compaction.ts):
          L1 pruneHistoryForContextShare (maxHistoryShare=0.5)
          L2 summarizeChunks
          L3 summarizeWithFallback
          L4 summarizeInStages
        """
        async with self._compact_lock:
            budget = token_budget or self.token_budget
            tokens_before = estimate_messages_tokens(self._messages)

            if not force and tokens_before <= budget:
                return CompactResult(ok=True, compacted=False,
                                     reason="within budget", tokens_before=tokens_before)

            if not self._messages:
                return CompactResult(ok=True, compacted=False,
                                     reason="empty messages", tokens_before=0)

            logger.info(
                f"AgentContext[{self.session_id}]: compact 开始 "
                f"tokens={tokens_before} budget={budget}"
            )

            # Level 1: 历史裁剪 — 最多保留 50% 用于历史
            history_budget = int(budget * MAX_HISTORY_SHARE)
            kept = list(self._messages)
            dropped_for_summary: list[AgentMessage] = []
            parts = 2

            while kept and estimate_messages_tokens(kept) > history_budget:
                chunks = _split_by_token_share(kept, parts)
                if len(chunks) <= 1:
                    break
                dropped_chunk = chunks[0]
                rest = [m for chunk in chunks[1:] for m in chunk]
                rest = _repair_tool_pairs(rest)
                dropped_for_summary.extend(dropped_chunk)
                kept = rest

            first_kept_id = kept[0].message_id if kept else None

            # Level 2-4: 为被裁剪的历史生成摘要
            summary = self._compacted_summary
            if dropped_for_summary:
                context_window = int(budget / SAFETY_MARGIN)
                max_chunk_tokens = max(
                    1, context_window - SUMMARIZATION_OVERHEAD
                )
                summary = await _summarize_in_stages(
                    dropped_for_summary,
                    self._llm_summarize,
                    max_chunk_tokens=max_chunk_tokens,
                    context_window=context_window,
                    custom_instructions=custom_instructions,
                    previous_summary=self._compacted_summary,
                    parts=2,
                )

            self._messages = kept
            self._compacted_summary = summary
            self._total_tokens = estimate_messages_tokens(kept)
            tokens_after = self._total_tokens

            logger.info(
                f"AgentContext[{self.session_id}]: compact 完成 "
                f"{tokens_before} → {tokens_after} tokens"
            )
            return CompactResult(
                ok=True,
                compacted=True,
                summary=summary,
                first_kept_entry_id=first_kept_id,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
            )

    # ── subagent lifecycle ────────────────────────────────────────────────────

    async def prepare_subagent_spawn(
        self,
        parent_session_key: str,
        child_session_key: str,
        ttl_ms: Optional[int] = None,
    ) -> dict:
        """子智能体衍生前准备 — 返回 rollback 回调"""
        logger.debug(
            f"AgentContext: prepare_subagent_spawn "
            f"parent={parent_session_key} child={child_session_key}"
        )
        snapshot = list(self._messages)

        async def rollback():
            self._messages = snapshot
            logger.warning(
                f"AgentContext: subagent spawn rollback for child={child_session_key}"
            )

        return {"rollback": rollback}

    async def on_subagent_ended(
        self, child_session_key: str, reason: str
    ) -> None:
        """子智能体生命周期结束通知 (deleted/completed/swept/released)"""
        logger.info(
            f"AgentContext[{self.session_id}]: subagent ended "
            f"child={child_session_key} reason={reason}"
        )

    # ── 属性 ──────────────────────────────────────────────────────────────────

    @property
    def messages(self) -> list[AgentMessage]:
        return list(self._messages)

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def get_compacted_summary(self) -> Optional[str]:
        return self._compacted_summary

    def clear(self) -> None:
        """重置上下文 (保留系统提示和先验注入)"""
        self._messages.clear()
        self._seen_ids.clear()
        self._total_tokens = 0
        self._compacted_summary = None


# ─── 默认摘要后端 (Fallback) ──────────────────────────────────────────────────

async def _default_llm_summarize(
    conversation_text: str, instructions: Optional[str] = None
) -> str:
    """
    默认摘要后端 — 简单截断 (实际使用时替换为真实 LLM 调用)
    调用方应通过 AgentContext(llm_summarize=...) 注入真实 LLM 客户端
    """
    max_chars = 2000
    truncated = conversation_text[:max_chars]
    if len(conversation_text) > max_chars:
        truncated += f"\n... [truncated {len(conversation_text) - max_chars} chars]"
    return f"[Summary]\n{truncated}"


# ─── 引擎注册表 (Registry Pattern) ──────────────────────────────────────────────

_CONTEXT_ENGINES: dict[str, Callable[..., ContextEngine]] = {}

def register_context_engine(name: str, factory: Callable[..., ContextEngine]) -> None:
    """注册一个新的 ContextEngine 工厂"""
    _CONTEXT_ENGINES[name] = factory


def resolve_context_engine(name: str, **kwargs) -> ContextEngine:
    """解析并实例化 Context Engine"""
    factory = _CONTEXT_ENGINES.get(name)
    if not factory:
        logger.warning(f"ContextEngine '{name}' 未找到，回退至 'legacy'")
        factory = _CONTEXT_ENGINES.get("legacy")
        if not factory:
            raise ValueError("严重错误：连 'legacy' 引擎也没有注册！")
    return factory(**kwargs)


# 注册默认引擎
register_context_engine("legacy", lambda **kwargs: LegacyContextEngine(**kwargs))


# ─── 工厂函数 ─────────────────────────────────────────────────────────────────

def create_agent_context(
    session_id: Optional[str] = None,
    system_prompt: str = "",
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    is_heartbeat: bool = False,
    llm_summarize: Optional[Callable] = None,
    engine_name: str = "legacy",
) -> ContextEngine:
    """创建并解析 ContextEngine 实例 (向前兼容原先的 AgentContext)"""
    sid = session_id or str(uuid.uuid4())
    return resolve_context_engine(
        engine_name,
        session_id=sid,
        system_prompt=system_prompt,
        token_budget=token_budget,
        is_heartbeat=is_heartbeat,
        llm_summarize=llm_summarize,
    )
