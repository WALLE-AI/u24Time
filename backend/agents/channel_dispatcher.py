# -*- coding: utf-8 -*-
"""
ChannelDispatcher — 多渠道推送分发网关
深度参考 OpenClaw channels/ 模块实现

支持渠道:
  - SSE (Server-Sent Events) — 前端实时流
  - WebSocket — 双向实时通信
  - Webhook — Telegram Bot API / 企业微信 / 飞书

策略:
  - HeartbeatPolicy: 纯 ACK 心跳包静默跳过推送
  - InboundDebounce: 控制命令/媒体不防抖
  - 媒体消息永不被 HeartbeatPolicy 过滤
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from loguru import logger

# ─── SSE 事件队列 ─────────────────────────────────────────────────────────────

_sse_queues: dict[str, asyncio.Queue] = {}  # run_id → Queue
_ws_connections: dict[str, Any] = {}        # run_id → WebSocket

SSE_QUEUE_SIZE = 100


def get_or_create_sse_queue(run_id: str) -> asyncio.Queue:
    if run_id not in _sse_queues:
        _sse_queues[run_id] = asyncio.Queue(maxsize=SSE_QUEUE_SIZE)
    return _sse_queues[run_id]


def remove_sse_queue(run_id: str) -> None:
    _sse_queues.pop(run_id, None)


# ─── Webhook 配置 ─────────────────────────────────────────────────────────────

@dataclass
class WebhookConfig:
    name: str
    url: str
    events: list[str] = field(default_factory=lambda: ["final_report"])
    headers: dict = field(default_factory=dict)
    timeout_s: float = 10.0


# ─── 心跳令牌 (参考 OpenClaw heartbeat-policy.ts) ────────────────────────────

_HEARTBEAT_ACK_TOKENS = frozenset({
    "[ok]", "[heartbeat-ok]", "heartbeat-ok", "ok", "✓", "✔", "☑", "✅",
})

ACK_MAX_CHARS = 50


def _is_heartbeat_ack_only(text: Optional[str], has_media: bool = False) -> bool:
    """
    判断是否为纯心跳 ACK (参考 shouldSkipHeartbeatOnlyDelivery):
      - 有媒体 → 永不跳过
      - 文本 strip 后是 ACK 令牌 → 跳过
    """
    if has_media:
        return False
    if not text:
        return True
    stripped = text.strip()[:ACK_MAX_CHARS].lower()
    return stripped in _HEARTBEAT_ACK_TOKENS


# ─── 主类 ──────────────────────────────────────────────────────────────────────

class ChannelDispatcher:
    """
    多渠道推送分发器
    """

    def __init__(self, webhooks: Optional[list[WebhookConfig]] = None):
        self._webhooks = webhooks or []

    def register_webhook(self, config: WebhookConfig) -> None:
        """注册 Webhook 目标"""
        self._webhooks.append(config)
        logger.info(f"ChannelDispatcher: 注册 webhook '{config.name}' → {config.url}")

    def register_ws(self, run_id: str, ws) -> None:
        """注册 WebSocket 连接"""
        _ws_connections[run_id] = ws
        logger.debug(f"ChannelDispatcher: WS 连接 run={run_id}")

    def unregister_ws(self, run_id: str) -> None:
        _ws_connections.pop(run_id, None)

    # ── 主推送入口 ────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        event: str,
        payload: dict,
        run_id: str,
        is_heartbeat: bool = False,
        has_media: bool = False,
    ) -> None:
        """
        统一分发事件到所有已注册渠道

        is_heartbeat=True 时应用 HeartbeatPolicy:
          - 纯 ACK 文本 → 跳过推送
          - 有媒体 → 不跳过
        """
        if is_heartbeat:
            text = payload.get("text") or payload.get("content", "")
            if _is_heartbeat_ack_only(text, has_media):
                logger.debug(
                    f"ChannelDispatcher: 跳过心跳纯 ACK 推送 run={run_id}"
                )
                return

        push_tasks = []

        # SSE
        push_tasks.append(self._push_sse(run_id, event, payload))

        # WebSocket
        if run_id in _ws_connections:
            push_tasks.append(self._push_ws(run_id, event, payload))

        # Webhooks
        for wh in self._webhooks:
            if event in wh.events or "*" in wh.events:
                push_tasks.append(self._push_webhook(wh, event, payload, run_id))

        if push_tasks:
            results = await asyncio.gather(*push_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"ChannelDispatcher: 推送异常 — {r}")

    # ── SSE 推送 ──────────────────────────────────────────────────────────────

    async def _push_sse(self, run_id: str, event: str, payload: dict) -> None:
        """写入 SSE 队列"""
        queue = get_or_create_sse_queue(run_id)
        message = {
            "event": event,
            "data": payload,
            "timestamp": time.time(),
            "run_id": run_id,
        }
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                f"ChannelDispatcher: SSE 队列已满 run={run_id}, 丢弃最旧事件"
            )
            try:
                queue.get_nowait()  # 丢弃最旧
                queue.put_nowait(message)
            except Exception:
                pass

    # ── WebSocket 推送 ────────────────────────────────────────────────────────

    async def _push_ws(self, run_id: str, event: str, payload: dict) -> None:
        """向 WebSocket 连接推送消息"""
        ws = _ws_connections.get(run_id)
        if not ws:
            return
        message = json.dumps({"event": event, "data": payload, "run_id": run_id})
        try:
            await ws.send_text(message)
        except Exception as e:
            logger.warning(
                f"ChannelDispatcher: WS 推送失败 run={run_id} — {e}"
            )
            self.unregister_ws(run_id)

    # ── Webhook 推送 ──────────────────────────────────────────────────────────

    async def _push_webhook(
        self, wh: WebhookConfig, event: str, payload: dict, run_id: str
    ) -> None:
        """HTTP POST 到 Webhook 目标"""
        try:
            import httpx
            body = {
                "event": event,
                "run_id": run_id,
                "timestamp": time.time(),
                "data": payload,
            }
            async with httpx.AsyncClient(
                timeout=wh.timeout_s, headers=wh.headers
            ) as client:
                resp = await client.post(wh.url, json=body)
                if resp.status_code >= 400:
                    logger.warning(
                        f"ChannelDispatcher: webhook '{wh.name}' "
                        f"返回 {resp.status_code}"
                    )
        except Exception as e:
            logger.warning(
                f"ChannelDispatcher: webhook '{wh.name}' 推送失败 — {e}"
            )

    # ── 广播 ──────────────────────────────────────────────────────────────────

    async def broadcast(
        self,
        event: str,
        payload: dict,
        is_heartbeat: bool = False,
    ) -> None:
        """向所有活跃连接广播"""
        tasks = []
        for run_id in list(_ws_connections.keys()):
            tasks.append(self.dispatch(event, payload, run_id, is_heartbeat))
        for run_id in list(_sse_queues.keys()):
            if run_id not in _ws_connections:
                tasks.append(self._push_sse(run_id, event, payload))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ── SSE 流生成器 (供 FastAPI StreamingResponse 使用) ────────────────────

    @staticmethod
    async def sse_stream(run_id: str, timeout_s: float = 300.0):
        """
        SSE 流生成器
        Usage:
            return StreamingResponse(
                ChannelDispatcher.sse_stream(run_id),
                media_type="text/event-stream"
            )
        """
        queue = get_or_create_sse_queue(run_id)
        deadline = time.time() + timeout_s
        try:
            while time.time() < deadline:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=1.0)
                    data = json.dumps(msg["data"])
                    yield f"event: {msg['event']}\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield "event: ping\ndata: {}\n\n"
        finally:
            remove_sse_queue(run_id)

    def status(self) -> dict:
        return {
            "sse_queues": len(_sse_queues),
            "ws_connections": len(_ws_connections),
            "webhooks": [{"name": w.name, "url": w.url} for w in self._webhooks],
        }


# ─── 单例管理 ─────────────────────────────────────────────────────────────────

_dispatcher_instance: Optional[ChannelDispatcher] = None


def get_channel_dispatcher() -> ChannelDispatcher:
    global _dispatcher_instance
    if _dispatcher_instance is None:
        _dispatcher_instance = ChannelDispatcher()
        logger.info("ChannelDispatcher: 全局实例已初始化")
    return _dispatcher_instance
