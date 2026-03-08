# -*- coding: utf-8 -*-
"""
Forum Monitor - 论坛监控与中间件队列
接收三引擎输出并调度 HOST Agent
支持 FastAPI StreamingResponse
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncIterator, List, Dict
from loguru import logger

from utils.llm_client import LLMClient
from agents.phase1_bettafish.forum.host import ForumHost

class ForumMonitor:
    HOST_THRESHOLD = 5

    def __init__(self, llm: LLMClient):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._history: List[Dict] = []
        self._host = ForumHost(llm)
        self._is_active = True
        
    def is_active(self) -> bool:
        return self._is_active
        
    def close(self):
        self._is_active = False
        
    def get_history(self) -> List[Dict]:
        return self._history

    async def submit(self, source: str, content: str):
        """引擎（QUERY/MEDIA/INSIGHT）提交发言"""
        if not self._is_active:
            return
            
        msg = {
            "source": source,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self._queue.put(msg)
        logger.debug(f"ForumMonitor: 收到 {source} 消息")

    async def run(self) -> AsyncIterator[dict]:
        """
        生成器：持续 yield 论坛消息（供 StreamingResponse 使用）
        当 _is_active 变 False 且 queue 为空时安全退出
        """
        while self._is_active or not self._queue.empty():
            try:
                # 使用 timeout 避免永久阻塞，方便检测 self._is_active 的变化
                msg = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                
                self._history.append(msg)
                yield msg
                self._queue.task_done()
                
                # 触发 HOST
                if len(self._history) % self.HOST_THRESHOLD == 0:
                    logger.info("ForumMonitor: 达到阈值，触发 HOST 发言...")
                    recent = self._history[-self.HOST_THRESHOLD:]
                    host_speech = await self._host.generate_speech(recent)
                    host_msg = {
                        "source": "HOST",
                        "content": host_speech,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                    self._history.append(host_msg)
                    yield host_msg
                    
            except asyncio.TimeoutError:
                # 超时意味着队列暂时为空，继续循环检查 _is_active
                continue
            except asyncio.CancelledError:
                logger.info("ForumMonitor: 客户端连接断开")
                break
            except Exception as e:
                logger.error(f"ForumMonitor: run 异常 {e}")
                
        logger.info("ForumMonitor: 监控流结束")
