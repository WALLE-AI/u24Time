# -*- coding: utf-8 -*-
"""
LLMClient — 外部大模型接入工具
支持 OpenAI 兼容接口（如 GPT-4, Qwen, DeepSeek 等）
"""

import json
from typing import Any, Optional

import httpx
from loguru import logger

from config import settings


class LLMClient:
    """
    统一 LLM 访问客户端。
    优先从 settings 中获取配置。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or settings.LLM_API_KEY
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL_NAME
        self.timeout = 30.0

    async def generate_summary(self, domain_groups: dict[str, list[dict]]) -> str:
        """
        根据各领域的情报条目生成分领域的综述。
        """
        if not self.api_key:
            logger.warning("LLMClient: LLM_API_KEY 未配置，返回模拟摘要")
            return self._mock_domain_summary(domain_groups)

        # 构建分领域的上下文
        context_parts = []
        for domain, items in domain_groups.items():
            if not items:
                continue
            group_text = f"【{domain} 领域】:\n" + "\n".join([
                f"- {item.get('title')}" for item in items[:10]
            ])
            context_parts.append(group_text)
        
        context = "\n\n".join(context_parts)

        prompt = (
            "你是一个资深全球情报分析师。请针对以下各领域的最新动态，提供一份综合简报。\n"
            "要求：\n"
            "1. 按领域（经济、技术、学术、全球监控）进行综述。\n"
            "2. 每个领域的总结要精炼，突出最重要的高热度或高严重度事件。\n"
            "3. 如果某个领域内容较少，可合并或简略描述。\n"
            "4. 总字数控制在 250 字以内，使用专业、冷静的语气。\n"
            "5. 必须使用中文，采用清晰的分段格式。\n\n"
            "情报内容：\n"
            f"{context}\n\n"
            "综述："
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": "You are a professional intelligence analyst."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.3,
                        "max_tokens": 300
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                return content

        except Exception as e:
            logger.error(f"LLMClient: 生成摘要失败: {e}")
            return f"智能化综述暂时不可用 (Error: {str(e)[:50]}...)"

    def _mock_domain_summary(self, domain_groups: dict[str, list[dict]]) -> str:
        """分领域的模拟摘要"""
        lines = ["【系统综述 (模拟数据)】"]
        
        mapping = {
            "economy": "经济域",
            "technology": "技术域",
            "academic": "学术域",
            "global": "全球监控"
        }

        for domain, items in domain_groups.items():
            if not items:
                continue
            name = mapping.get(domain, domain)
            count = len(items)
            lines.append(f"- {name}: 监测到 {count} 条动态，主要涵盖 {items[0].get('title')[:30]} 等热点。")
            
        lines.append("\n(注：请在后端配置 LLM_API_KEY 以通过 Qwen/GPT 获取真实的 AI 深度分析)")
        return "\n".join(lines)
