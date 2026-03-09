# -*- coding: utf-8 -*-
"""
HeartbeatScheduler — 心跳调度引擎
深度参考 OpenClaw src/cron/heartbeat-policy.ts + service.ts + subagent-registry.ts

核心特性:
  - APScheduler AsyncIO 驱动
  - isHeartbeat 标志区分定时触发 vs 手动触发
  - 防重入锁 (全局/阶段级别)
  - HeartbeatPolicy: 媒体消息不跳过; 纯 ACK 静默跳过
  - InboundDebounce: 控制命令/媒体不防抖, 普通文本合并
  - 指数退避重试 (1→2→4→8s, MAX_RETRY=3)
  - 15s LIFECYCLE_ERROR_RETRY_GRACE_MS 宽限期
  - Sweeper@60s 定期清档
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from loguru import logger

# APScheduler 3.x (asyncio 调度器)
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    AsyncIOScheduler = None
    CronTrigger = None
    IntervalTrigger = None

from agents.subagent_registry import (
    SubagentRegistry,
    LIFECYCLE_ERROR_RETRY_GRACE_MS,
    MAX_ANNOUNCE_RETRY_COUNT,
    MIN_RETRY_DELAY_MS,
    MAX_RETRY_DELAY_MS,
)

# ─── 常量 ─────────────────────────────────────────────────────────────────────
DEFAULT_HEARTBEAT_CRON   = "0 * * * *"   # 每小时整点
DEFAULT_SWEEPER_INTERVAL = 60            # 秒
HEARTBEAT_ACK_TOKENS     = {"[ok]", "[heartbeat-ok]", "heartbeat-ok", "ok", "✓"}


# ─── HeartbeatPolicy (参考 OpenClaw heartbeat-policy.ts) ─────────────────────

class HeartbeatPolicy:
    """心跳推送过滤策略"""

    def __init__(self, ack_max_chars: int = 50):
        self._ack_max_chars = ack_max_chars

    def should_skip_delivery(
        self, text: Optional[str] = None, has_media: bool = False
    ) -> bool:
        """
        是否跳过心跳推送:
          - 有媒体附件 → 不跳过 (保留)
          - 纯 ACK 文本 (心跳令牌) → 跳过
        参考: shouldSkipHeartbeatOnlyDelivery
        """
        if has_media:
            return False
        if not text:
            return True
        stripped = text.strip()[:self._ack_max_chars].lower()
        return stripped in HEARTBEAT_ACK_TOKENS or bool(
            re.match(r'^[✓✔☑✅]\s*$', stripped)
        )

    def should_enqueue_cron_summary(
        self,
        summary_text: Optional[str],
        delivery_requested: bool,
        delivered: Optional[bool],
        delivery_attempted: Optional[bool],
        suppress_main_summary: bool,
    ) -> bool:
        """
        是否将 cron 主摘要入队:
        参考: shouldEnqueueCronMainSummary
        """
        text = (summary_text or "").strip()
        return bool(
            text
            and delivery_requested
            and not delivered
            and delivery_attempted is not True
            and not suppress_main_summary
        )


# ─── InboundDebounce (参考 OpenClaw channels/inbound-debounce-policy.ts) ─────

class InboundDebouncePolicy:
    """入站消息防抖策略"""

    CONTROL_COMMANDS = {"/run", "/stop", "/status", "/reset", "/help", "/"}

    def should_debounce(
        self,
        text: Optional[str],
        has_media: bool = False,
        allow_debounce: bool = True,
    ) -> bool:
        """
        参考: shouldDebounceTextInbound
          - allow_debounce=False → 不防抖
          - 有媒体 → 不防抖 (即时处理)
          - 含控制命令 (斜杠命令) → 不防抖
          - 普通文本 → 参与防抖
        """
        if not allow_debounce or has_media:
            return False
        if not text:
            return False
        stripped = text.strip()
        if any(stripped.startswith(cmd) for cmd in self.CONTROL_COMMANDS):
            return False
        return True


# ─── HeartbeatScheduler ───────────────────────────────────────────────────────

class HeartbeatScheduler:
    """
    心跳调度引擎 — APScheduler AsyncIO 驱动
    """

    def __init__(
        self,
        pipeline_fn: Callable[[], Any],    # E2E 协调器的 run() 函数
        registry: SubagentRegistry,
        heartbeat_cron: str = DEFAULT_HEARTBEAT_CRON,
        sweeper_interval_s: int = DEFAULT_SWEEPER_INTERVAL,
    ):
        self._pipeline_fn = pipeline_fn
        self._registry = registry
        self._heartbeat_cron = heartbeat_cron
        self._sweeper_interval_s = sweeper_interval_s
        self._heartbeat_policy = HeartbeatPolicy()
        self._debounce_policy = InboundDebouncePolicy()

        # 防重入锁
        self._running: dict[str, bool] = {"heartbeat": False}
        self._run_lock = asyncio.Lock()

        # APScheduler
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._retry_counts: dict[str, int] = {}
        self._task_history: list[dict] = []

    # ── 启动/停止 ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """启动调度器 (在 FastAPI lifespan 中调用)"""
        if not HAS_APSCHEDULER:
            logger.warning(
                "HeartbeatScheduler: apscheduler 未安装 — "
                "请执行 pip install apscheduler"
            )
            # 降级: 仅注册 asyncio 定时任务
            asyncio.create_task(self._fallback_loop())
            return

        self._scheduler = AsyncIOScheduler(timezone="UTC")

        # 心跳任务 (Cron)
        self._scheduler.add_job(
            self._heartbeat_job,
            CronTrigger.from_crontab(self._heartbeat_cron, timezone="UTC"),
            id="heartbeat_main",
            name="E2E Pipeline Heartbeat",
            replace_existing=True,
            max_instances=1,  # 防止重叠执行
        )

        # Sweeper 任务 (Interval)
        self._scheduler.add_job(
            self._sweeper_job,
            IntervalTrigger(seconds=self._sweeper_interval_s),
            id="sweeper",
            name="SubagentRegistry Sweeper",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            f"HeartbeatScheduler: 启动 cron='{self._heartbeat_cron}' "
            f"sweeper_interval={self._sweeper_interval_s}s"
        )

    def stop(self) -> None:
        """停止调度器 (在 FastAPI lifespan shutdown 中调用)"""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("HeartbeatScheduler: 已停止")

    # ── 心跳任务 ──────────────────────────────────────────────────────────────

    async def _heartbeat_job(self) -> None:
        """
        心跳触发器 — 防重入保护 + 使用 isHeartbeat=True 标志
        """
        async with self._run_lock:
            if self._running["heartbeat"]:
                logger.debug("HeartbeatScheduler: 心跳已在运行, 跳过")
                return
            self._running["heartbeat"] = True

        started_at = datetime.now(timezone.utc).isoformat()
        success = False
        error_msg: Optional[str] = None

        try:
            logger.info("HeartbeatScheduler: ▶ 心跳触发")
            await self._run_with_retry(is_heartbeat=True)
            success = True
            self._retry_counts["heartbeat"] = 0
        except Exception as e:
            error_msg = str(e)
            logger.error(f"HeartbeatScheduler: 心跳失败 — {e}")
            # 15s 宽限期后记录错误 (参考 LIFECYCLE_ERROR_RETRY_GRACE_MS)
            asyncio.create_task(
                self._grace_period_error_log("heartbeat", error_msg)
            )
        finally:
            async with self._run_lock:
                self._running["heartbeat"] = False

        self._task_history.append({
            "type": "heartbeat",
            "started_at": started_at,
            "success": success,
            "error": error_msg,
        })
        # 只保留最近 50 条历史
        if len(self._task_history) > 50:
            self._task_history = self._task_history[-50:]

    async def _sweeper_job(self) -> None:
        """Sweeper 任务 — 定期清档到期记录"""
        try:
            archived = await self._registry.sweep()
            if archived:
                logger.debug(f"HeartbeatScheduler: Sweeper 清档 {archived} 条记录")
        except Exception as e:
            logger.error(f"HeartbeatScheduler: Sweeper 异常 — {e}")

    # ── 重试逻辑 ──────────────────────────────────────────────────────────────

    async def _run_with_retry(self, is_heartbeat: bool = True) -> None:
        """
        带指数退避重试的 Pipeline 执行
        MAX_RETRY=3, delay: 1s → 2s → 4s → 8s (capped)
        """
        key = "heartbeat" if is_heartbeat else "manual"
        max_retries = MAX_ANNOUNCE_RETRY_COUNT

        last_error: Optional[Exception] = None
        for attempt in range(max_retries + 1):
            try:
                await self._pipeline_fn(is_heartbeat=is_heartbeat)
                return
            except asyncio.CancelledError:
                raise
            except Exception as e:
                last_error = e
                if attempt >= max_retries:
                    break
                delay_s = self._resolve_retry_delay_s(attempt)
                logger.warning(
                    f"HeartbeatScheduler: 重试 #{attempt + 1}/{max_retries} "
                    f"after {delay_s:.1f}s — {e}"
                )
                self._retry_counts[key] = attempt + 1
                await asyncio.sleep(delay_s)

        raise last_error or RuntimeError("Pipeline failed after retries")

    @staticmethod
    def _resolve_retry_delay_s(retry_count: int) -> float:
        """指数退避: MIN × 2^(retryCount-1), capped at MAX"""
        bounded = max(0, min(retry_count, 10))
        exponent = max(0, bounded - 1)
        base_ms = MIN_RETRY_DELAY_MS * (2 ** exponent)
        return min(base_ms, MAX_RETRY_DELAY_MS) / 1000.0

    # ── 手动触发 ──────────────────────────────────────────────────────────────

    async def trigger_now(self, is_heartbeat: bool = False) -> dict:
        """
        手动触发 Pipeline (is_heartbeat=False 时为用户主动请求)
        返回执行摘要
        """
        async with self._run_lock:
            if self._running.get("heartbeat"):
                return {"status": "busy", "message": "heartbeat 正在运行"}

        started = datetime.now(timezone.utc).isoformat()
        try:
            await self._run_with_retry(is_heartbeat=is_heartbeat)
            return {
                "status": "success",
                "started_at": started,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "is_heartbeat": is_heartbeat,
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "started_at": started,
                "is_heartbeat": is_heartbeat,
            }

    # ── HeartbeatPolicy 集成 ──────────────────────────────────────────────────

    def should_skip_delivery(
        self, text: Optional[str], has_media: bool = False
    ) -> bool:
        """是否跳过心跳推送 (纯 ACK 静默)"""
        return self._heartbeat_policy.should_skip_delivery(text, has_media)

    def should_debounce(
        self, text: Optional[str], has_media: bool = False
    ) -> bool:
        """是否对入站消息防抖"""
        return self._debounce_policy.should_debounce(text, has_media)

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """调度器状态"""
        jobs = []
        if self._scheduler:
            for job in self._scheduler.get_jobs():
                next_run = job.next_run_time
                jobs.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": next_run.isoformat() if next_run else None,
                })
        return {
            "running": self._scheduler.running if self._scheduler else False,
            "heartbeat_cron": self._heartbeat_cron,
            "sweeper_interval_s": self._sweeper_interval_s,
            "is_heartbeat_running": self._running.get("heartbeat", False),
            "retry_counts": dict(self._retry_counts),
            "jobs": jobs,
            "recent_history": self._task_history[-5:],
        }

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    async def _grace_period_error_log(self, key: str, error: str) -> None:
        """LIFECYCLE_ERROR_RETRY_GRACE_MS 宽限期后记录错误"""
        grace_s = LIFECYCLE_ERROR_RETRY_GRACE_MS / 1000.0
        await asyncio.sleep(grace_s)
        # 若 grace period 内已成功恢复, 不记录错误
        if self._retry_counts.get(key, 0) == 0:
            return
        logger.error(
            f"HeartbeatScheduler: {key} 宽限期后仍未恢复 — {error}"
        )

    async def _fallback_loop(self) -> None:
        """APScheduler 不可用时的 asyncio 降级循环"""
        logger.warning("HeartbeatScheduler: 使用 asyncio 降级心跳 (每小时)")
        while True:
            try:
                await asyncio.sleep(3600)
                await self._heartbeat_job()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"HeartbeatScheduler: 降级循环异常 — {e}")


# ─── 单例管理 ─────────────────────────────────────────────────────────────────

_scheduler_instance: Optional[HeartbeatScheduler] = None


def create_heartbeat_scheduler(
    pipeline_fn: Callable,
    registry: SubagentRegistry,
    heartbeat_cron: str = DEFAULT_HEARTBEAT_CRON,
) -> HeartbeatScheduler:
    """创建心跳调度器实例"""
    global _scheduler_instance
    _scheduler_instance = HeartbeatScheduler(
        pipeline_fn=pipeline_fn,
        registry=registry,
        heartbeat_cron=heartbeat_cron,
    )
    return _scheduler_instance


def get_heartbeat_scheduler() -> Optional[HeartbeatScheduler]:
    """获取全局心跳调度器实例"""
    return _scheduler_instance
