# -*- coding: utf-8 -*-
"""
ForumHost - 论坛主持人 Agent
每隔 N 条消息触发，引导讨论走向
"""

from typing import List
from loguru import logger

from utils.llm_client import LLMClient

class ForumHost:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def generate_speech(self, recent_speeches: List[dict]) -> str:
        """
        基于最近的对话记录生成主持人发言
        recent_speeches: [{"source": "QUERY", "content": "..."}, ...]
        """
        if not recent_speeches:
            return "欢迎各位专家，请开始就本次事件发表洞见。"
            
        context_lines = []
        for i, speech in enumerate(recent_speeches):
            context_lines.append(f"[{speech['source']}] 发言: {speech['content']}")
            
        context = "\n".join(context_lines)
        
        prompt = (
            f"你是一个名为 [HOST] 的资深舆情研判会议主持人。\n"
            f"以下是参会专家(QUERY, MEDIA, INSIGHT)近期的发言记录:\n"
            f"{context}\n\n"
            f"请你基于以上发言，对当前的讨论进行一次极简的阶段性总结（1-2句），"
            f"并抛出一个具有启发性的问题，引导专家们进一步深入探讨事件的关键矛盾或未来走向。\n"
            f"直接输出你的发言内容，不需要加 [HOST] 前缀，字数控制在 100 字以内。"
        )
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}"},
                    json={
                        "model": self._llm.model,
                        "messages": [
                            {"role": "system", "content": "You are a Forum Host Agent driving deep analytical discussions."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.5,
                    }
                )
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"ForumHost: 生成发言失败: {e}")
            return "各位专家的分析都很到位，我们继续关注事件的后续发酵。"
