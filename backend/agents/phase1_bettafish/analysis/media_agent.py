# -*- coding: utf-8 -*-
"""
MediaAgent — 多模态内容分析
聚焦多媒体内容摘要（文本+图片alt）
"""

from typing import List, Callable, Optional
from loguru import logger
from pydantic import BaseModel

from utils.llm_client import LLMClient
from data_alignment.schema import CanonicalItem

class AgentReport(BaseModel):
    source: str
    paragraph: str

class MediaAgent:
    """
    负责提取和分析图片中的信息，形成跨模态摘要
    """
    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def run(self, query: str, related_items: List[CanonicalItem], broadcast_cb: Optional[Callable] = None) -> AgentReport:
        logger.info(f"MediaAgent: 开始分析 '{query}' 相关的图片和多媒体内容...")
        
        # 1. 抽取多媒体标记 (由于大部分图片URL无法直接被分析，提取 alt text 或关联标题)
        multimedia_context = self._extract_multimedia_context(related_items)
        
        # 2. 调用 LLM 融合多媒体信息
        paragraph = await self._summarize(query, multimedia_context)
        
        if broadcast_cb:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(broadcast_cb):
                    await broadcast_cb("MEDIA", paragraph)
                else:
                    broadcast_cb("MEDIA", paragraph)
            except Exception as e:
                logger.error(f"MediaAgent: 无法广播消息 - {e}")
                
        return AgentReport(source="media", paragraph=paragraph)
        
    def _extract_multimedia_context(self, items: List[CanonicalItem]) -> str:
        """从相关的 CanonicalItem 提取多感官特征"""
        if not items:
            return "未在数据库中找到关于该事件的多媒体(图片或视频)资源描述。"
            
        lines = []
        for idx, item in enumerate(items[:20]):
            meta = item.raw_metadata or {}
            visual_desc = ""
            if "images" in meta and meta["images"]:
                visual_desc = f"[发现 {len(meta['images'])} 张关连图片]"
            elif "image_url" in meta or "cover_url" in meta:
                visual_desc = f"[发现封面图]"
            elif "video" in meta or "bvid" in meta or item.source_id.endswith("bilibili") or item.source_id.endswith("douyin"):
                visual_desc = f"[发现关联短视频]"
                
            if visual_desc:
                lines.append(f"素材 {idx+1}: {item.title} {visual_desc}。互动量: {item.hotness_score:.1f}")
                
        if not lines:
            return "数据库中该事件缺乏多媒体特征信息，主要以文本为主。"
            
        return "相关多媒体资源线索:\n" + "\n".join(lines)
        
    async def _summarize(self, query: str, context: str) -> str:
        """基于多感官线索总结"""
        prompt = (
            f"目标主题: '{query}'\n"
            f"多媒体关联线索:\n{context}\n\n"
            f"请以【Media 视觉情报】的口吻，评价该事件在富媒体传播上的特征。 "
            f"（例如：是否存在广泛流传的照片或短视频、图像是否加剧了情绪等）。\n"
            f"如果线索不足，也请简短说明缺乏直观的视觉材料印证。\n"
            f"字数控制在 100 字左右。"
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
                            {"role": "system", "content": "You are a Media Analyst Agent extracting visual cues."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                    }
                )
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"MediaAgent: 分析失败: {e}")
            return "多媒体情报提取受阻。"
