# -*- coding: utf-8 -*-
"""
SubagentRegistry — 子智能体生命周期管理
深度参考 OpenClaw src/agents/subagent-registry.ts

核心特性:
  - 完整状态机: PENDING → RUNNING → COMPLETED | FAILED | KILLED → ARCHIVED
  - 指数退避重试: 1s → 2s → 4s → 8s (最多 3 次)
  - LIFECYCLE_ERROR_RETRY_GRACE_MS = 15s 错误宽限期
  - Sweeper@60s: archiveAfterMinutes=60 分钟后归档
  - 磁盘持久化: 支持进程重启恢复
  - 孤儿调和: 找不到对应 SessionEntry 的 Run 自动标记为 error
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from loguru import logger

# ─── 常量 (对齐 OpenClaw subagent-registry.ts) ──────────────────────────────
MIN_RETRY_DELAY_MS               = 1_000
MAX_RETRY_DELAY_MS               = 8_000
MAX_ANNOUNCE_RETRY_COUNT         = 3
ANNOUNCE_EXPIRY_MS               = 5 * 60_000
ANNOUNCE_COMPLETION_HARD_EXPIRY  = 30 * 60_000
LIFECYCLE_ERROR_RETRY_GRACE_MS   = 15_000
FROZEN_TEXT_MAX_BYTES            = 100 * 1024
SWEEPER_INTERVAL_S               = 60
ARCHIVE_AFTER_MINUTES            = 60
PERSIST_FILE_NAME                = "subagent_runs.json"


# ─── 状态枚举 ─────────────────────────────────────────────────────────────────

class SubagentStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    KILLED    = "killed"
    ARCHIVED  = "archived"


class SubagentEndReason(str, Enum):
    COMPLETE  = "complete"
    ERROR     = "error"
    KILLED    = "killed"
    SWEPT     = "swept"
    RELEASED  = "released"


# ─── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class SubagentOutcome:
    status: str                 # "ok" | "error" | "timeout"
    error: Optional[str] = None


@dataclass
class SubagentRunRecord:
    """子智能体运行记录 — 对齐 OpenClaw SubagentRunRecord"""
    run_id: str
    child_session_key: str
    stage: str                              # phase0_crawl / phase1_align / ...
    status: SubagentStatus = SubagentStatus.PENDING
    parent_run_id: Optional[str] = None

    started_at: Optional[float] = None
    ended_at: Optional[float] = None
    outcome: Optional[SubagentOutcome] = None
    ended_reason: Optional[str] = None      # SubagentEndReason

    announce_retry_count: int = 0
    last_announce_retry_at: Optional[float] = None
    cleanup_handled: bool = False
    cleanup_completed_at: Optional[float] = None
    archive_at_ms: Optional[float] = None   # archiveAfterMinutes

    frozen_result_text: Optional[str] = None
    frozen_result_captured_at: Optional[float] = None

    workspace_dir: Optional[str] = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        if self.outcome:
            d["outcome"] = asdict(self.outcome)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SubagentRunRecord":
        d = dict(d)
        d["status"] = SubagentStatus(d.get("status", "pending"))
        if d.get("outcome"):
            d["outcome"] = SubagentOutcome(**d["outcome"])
        return cls(**d)


# ─── 主类 ──────────────────────────────────────────────────────────────────────

class SubagentRegistry:
    """
    子智能体注册表 — 完整生命周期管理
    """

    def __init__(
        self,
        data_dir: str = "data",
        archive_after_minutes: int = ARCHIVE_AFTER_MINUTES,
        on_subagent_ended: Optional[Callable] = None,
    ):
        self._data_dir = data_dir
        self._persist_path = os.path.join(data_dir, PERSIST_FILE_NAME)
        self._archive_after_ms = archive_after_minutes * 60 * 1000
        self._on_subagent_ended = on_subagent_ended

        self._runs: dict[str, SubagentRunRecord] = {}
        self._pending_lifecycle_errors: dict[str, asyncio.Task] = {}
        self._sweeper_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        Path(data_dir).mkdir(parents=True, exist_ok=True)

    # ── 生命周期 ──────────────────────────────────────────────────────────────

    def register(
        self,
        stage: str,
        parent_run_id: Optional[str] = None,
        workspace_dir: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> SubagentRunRecord:
        """注册新的子智能体运行记录"""
        run_id = str(uuid.uuid4())
        child_key = f"{stage}:{run_id}"
        archive_at = time.time() * 1000 + self._archive_after_ms

        record = SubagentRunRecord(
            run_id=run_id,
            child_session_key=child_key,
            stage=stage,
            parent_run_id=parent_run_id,
            workspace_dir=workspace_dir,
            archive_at_ms=archive_at,
            metadata=metadata or {},
        )
        self._runs[run_id] = record
        self._persist_sync()
        logger.debug(f"SubagentRegistry: 注册 run={run_id} stage={stage}")
        return record

    async def start(self, run_id: str) -> None:
        """标记为 RUNNING"""
        record = self._runs.get(run_id)
        if not record:
            return
        # 取消待处理的错误宽限期 (若有)
        self._cancel_lifecycle_error(run_id)
        record.status = SubagentStatus.RUNNING
        record.started_at = time.time()
        self._persist_sync()
        logger.debug(f"SubagentRegistry: 开始 run={run_id}")

    async def complete(
        self,
        run_id: str,
        outcome: Optional[SubagentOutcome] = None,
        frozen_result: Optional[str] = None,
    ) -> None:
        """标记为 COMPLETED"""
        self._cancel_lifecycle_error(run_id)
        record = self._runs.get(run_id)
        if not record:
            return
        record.status = SubagentStatus.COMPLETED
        record.ended_at = time.time()
        record.outcome = outcome or SubagentOutcome(status="ok")
        record.ended_reason = SubagentEndReason.COMPLETE.value
        if frozen_result:
            record.frozen_result_text = self._cap_frozen_text(frozen_result)
            record.frozen_result_captured_at = time.time()
        self._persist_sync()
        logger.info(f"SubagentRegistry: 完成 run={run_id} stage={record.stage}")

    async def fail(
        self,
        run_id: str,
        error: Optional[str] = None,
        use_grace_period: bool = False,
    ) -> None:
        """
        标记为 FAILED.
        use_grace_period=True 时使用 15s 宽限期
        (等待 Provider 重试取消此错误, 参考 LIFECYCLE_ERROR_RETRY_GRACE_MS)
        """
        if use_grace_period:
            self._schedule_lifecycle_error(run_id, error)
            return
        self._cancel_lifecycle_error(run_id)
        record = self._runs.get(run_id)
        if not record:
            return
        # 如果已经是 COMPLETED, 不覆盖
        if record.status == SubagentStatus.COMPLETED and record.outcome and \
                record.outcome.status == "ok":
            return
        record.status = SubagentStatus.FAILED
        record.ended_at = time.time()
        record.outcome = SubagentOutcome(status="error", error=error)
        record.ended_reason = SubagentEndReason.ERROR.value
        self._persist_sync()
        logger.warning(f"SubagentRegistry: 失败 run={run_id} error={error}")

    async def kill(self, run_id: str) -> None:
        """标记为 KILLED"""
        self._cancel_lifecycle_error(run_id)
        record = self._runs.get(run_id)
        if not record:
            return
        record.status = SubagentStatus.KILLED
        record.ended_at = time.time()
        record.outcome = SubagentOutcome(status="error", error="killed")
        record.ended_reason = SubagentEndReason.KILLED.value
        self._persist_sync()
        logger.warning(f"SubagentRegistry: Kill run={run_id}")

    # ── 错误宽限期 (LIFECYCLE_ERROR_RETRY_GRACE_MS) ───────────────────────────

    def _schedule_lifecycle_error(self, run_id: str, error: Optional[str]) -> None:
        """15s 宽限期: 等待可能到来的 start 事件取消此错误"""
        self._cancel_lifecycle_error(run_id)
        grace_s = LIFECYCLE_ERROR_RETRY_GRACE_MS / 1000.0

        async def _deferred():
            await asyncio.sleep(grace_s)
            pending = self._pending_lifecycle_errors.pop(run_id, None)
            if not pending:
                return  # 已被取消
            # 检查是否已被 complete() 覆盖
            record = self._runs.get(run_id)
            if record and record.status not in (SubagentStatus.COMPLETED, SubagentStatus.RUNNING):
                await self.fail(run_id, error, use_grace_period=False)

        task = asyncio.create_task(_deferred())
        self._pending_lifecycle_errors[run_id] = task
        logger.debug(f"SubagentRegistry: 调度错误宽限期 run={run_id} grace={grace_s}s")

    def _cancel_lifecycle_error(self, run_id: str) -> None:
        """取消待处理的错误宽限期"""
        task = self._pending_lifecycle_errors.pop(run_id, None)
        if task and not task.done():
            task.cancel()

    # ── 指数退避重试 ──────────────────────────────────────────────────────────

    def resolve_retry_delay_s(self, retry_count: int) -> float:
        """
        指数退避延迟计算 (参考 OpenClaw resolveAnnounceRetryDelayMs)
        retry#1=1s, retry#2=2s, retry#3=4s → MAX=8s
        """
        bounded = max(0, min(retry_count, 10))
        exponent = max(0, bounded - 1)
        base_ms = MIN_RETRY_DELAY_MS * (2 ** exponent)
        return min(base_ms, MAX_RETRY_DELAY_MS) / 1000.0

    def should_give_up(
        self, record: SubagentRunRecord, is_completion: bool = False
    ) -> bool:
        """判断是否应放弃重试"""
        if record.announce_retry_count >= MAX_ANNOUNCE_RETRY_COUNT:
            logger.warning(
                f"SubagentRegistry: 放弃重试(retry-limit) run={record.run_id} "
                f"retries={record.announce_retry_count}"
            )
            return True
        if not is_completion and record.ended_at:
            age_ms = (time.time() - record.ended_at) * 1000
            if age_ms > ANNOUNCE_EXPIRY_MS:
                logger.warning(
                    f"SubagentRegistry: 放弃重试(expiry) run={record.run_id}"
                )
                return True
        if is_completion and record.ended_at:
            age_ms = (time.time() - record.ended_at) * 1000
            if age_ms > ANNOUNCE_COMPLETION_HARD_EXPIRY:
                logger.warning(
                    f"SubagentRegistry: 放弃 completion(hard-expiry) run={record.run_id}"
                )
                return True
        return False

    # ── Sweeper ───────────────────────────────────────────────────────────────

    def start_sweeper(self) -> None:
        """启动 60s 间隔的 Sweeper 任务"""
        if self._sweeper_task and not self._sweeper_task.done():
            return
        self._sweeper_task = asyncio.create_task(self._sweeper_loop())
        logger.info("SubagentRegistry: Sweeper 已启动")

    def stop_sweeper(self) -> None:
        """停止 Sweeper"""
        if self._sweeper_task and not self._sweeper_task.done():
            self._sweeper_task.cancel()
        self._sweeper_task = None

    async def _sweeper_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(SWEEPER_INTERVAL_S)
                await self.sweep()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SubagentRegistry: Sweeper 异常 — {e}")

    async def sweep(self) -> int:
        """
        归档到期的子智能体记录 (archiveAtMs)
        参考 OpenClaw sweepSubagentRuns()
        """
        now_ms = time.time() * 1000
        archived = []
        async with self._lock:
            for run_id, record in list(self._runs.items()):
                if record.archive_at_ms and record.archive_at_ms <= now_ms:
                    archived.append(run_id)
                    del self._runs[run_id]

        if archived:
            for run_id in archived:
                logger.info(f"SubagentRegistry: Sweeper 归档 run={run_id}")
                # 通知 ContextEngine
                if self._on_subagent_ended:
                    try:
                        await self._on_subagent_ended(run_id, SubagentEndReason.SWEPT.value)
                    except Exception as e:
                        logger.warning(f"SubagentRegistry: onSubagentEnded 失败 — {e}")
            self._persist_sync()

        return len(archived)

    # ── 查询 ──────────────────────────────────────────────────────────────────

    def get(self, run_id: str) -> Optional[SubagentRunRecord]:
        return self._runs.get(run_id)

    def list_by_stage(self, stage: str) -> list[SubagentRunRecord]:
        return [r for r in self._runs.values() if r.stage == stage]

    def list_active(self) -> list[SubagentRunRecord]:
        active_statuses = {SubagentStatus.PENDING, SubagentStatus.RUNNING}
        return [r for r in self._runs.values() if r.status in active_statuses]

    def list_all(self) -> list[SubagentRunRecord]:
        return list(self._runs.values())

    def count_active(self) -> int:
        return len(self.list_active())

    def active_run_ids(self) -> list[str]:
        return [r.run_id for r in self.list_active()]

    # ── 磁盘持久化 ────────────────────────────────────────────────────────────

    def _persist_sync(self) -> None:
        """同步写入持久化文件 (参考 persistSubagentRunsToDisk)"""
        try:
            data = {run_id: record.to_dict() for run_id, record in self._runs.items()}
            tmp_path = self._persist_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._persist_path)
        except Exception as e:
            logger.warning(f"SubagentRegistry: 持久化失败 — {e}")

    def restore_from_disk(self) -> int:
        """
        从磁盘恢复 runs (参考 restoreSubagentRunsFromDisk + orphan reconciliation)
        Returns: 恢复的记录数
        """
        if not os.path.exists(self._persist_path):
            return 0
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            restored = 0
            for run_id, d in data.items():
                try:
                    record = SubagentRunRecord.from_dict(d)
                    # 孤儿调和: PENDING/RUNNING 状态的孤儿重标记为 error
                    if record.status in (SubagentStatus.PENDING, SubagentStatus.RUNNING):
                        logger.warning(
                            f"SubagentRegistry: 孤儿运行记录调和 run={run_id} "
                            f"stage={record.stage} → 标记为 error"
                        )
                        record.status = SubagentStatus.FAILED
                        record.ended_at = time.time()
                        record.outcome = SubagentOutcome(
                            status="error", error="orphaned on restart"
                        )
                        record.ended_reason = SubagentEndReason.ERROR.value
                    self._runs[run_id] = record
                    restored += 1
                except Exception as e:
                    logger.warning(f"SubagentRegistry: 跳过无法恢复的记录 {run_id} — {e}")
            if restored:
                self._persist_sync()
            logger.info(f"SubagentRegistry: 从磁盘恢复 {restored} 条记录")
            return restored
        except Exception as e:
            logger.error(f"SubagentRegistry: 磁盘恢复失败 — {e}")
            return 0

    # ── 工具函数 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _cap_frozen_text(text: str) -> str:
        """冻结结果 100KB 上限 (参考 capFrozenResultText)"""
        if not text:
            return ""
        encoded = text.encode("utf-8")
        if len(encoded) <= FROZEN_TEXT_MAX_BYTES:
            return text
        cut = encoded[:FROZEN_TEXT_MAX_BYTES].decode("utf-8", errors="ignore")
        kb = len(encoded) // 1024
        notice = f"\n\n[truncated: frozen output exceeded {FROZEN_TEXT_MAX_BYTES // 1024}KB ({kb}KB)]"
        return cut[:FROZEN_TEXT_MAX_BYTES - len(notice)] + notice

    def status_summary(self) -> dict:
        counts: dict[str, int] = {}
        for record in self._runs.values():
            counts[record.status.value] = counts.get(record.status.value, 0) + 1
        return {
            "total": len(self._runs),
            "by_status": counts,
            "active": self.count_active(),
        }


# ─── 上下文管理器包装 (供 E2E Coordinator 使用) ──────────────────────────────

class PhaseRunner:
    """
    阶段运行器 — 自动管理 register → start → complete/fail 状态机
    """

    def __init__(self, registry: SubagentRegistry, stage: str, parent_id: Optional[str] = None):
        self._registry = registry
        self._stage = stage
        self._parent_id = parent_id
        self._record: Optional[SubagentRunRecord] = None

    async def __aenter__(self) -> SubagentRunRecord:
        self._record = self._registry.register(
            stage=self._stage, parent_run_id=self._parent_id
        )
        await self._registry.start(self._record.run_id)
        return self._record

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._record:
            return
        if exc_type is None:
            await self._registry.complete(self._record.run_id)
        else:
            await self._registry.fail(
                self._record.run_id,
                error=str(exc_val) if exc_val else None
            )
        return False  # 不吞异常


# ─── 单例管理 ─────────────────────────────────────────────────────────────────

_registry_instance: Optional[SubagentRegistry] = None


def get_subagent_registry(data_dir: str = "data") -> SubagentRegistry:
    """获取全局 SubagentRegistry 单例"""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = SubagentRegistry(data_dir=data_dir)
        _registry_instance.restore_from_disk()
        logger.info("SubagentRegistry: 全局实例已初始化")
    return _registry_instance
