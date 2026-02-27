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

    async def generate_summary(self, domain_groups: dict[str, list[dict]], target_domain: Optional[str] = None) -> str:
        """
        根据各领域的情报条目生成分领域的综述。
        如果指定了 target_domain，则生成该领域的深度综述。
        """
        if not self.api_key:
            logger.warning("LLMClient: LLM_API_KEY 未配置，返回模拟摘要")
            return self._mock_domain_summary(domain_groups, target_domain)

        # 构建上下文文字
        context_parts = []
        domain_names = {
            "economy": "经济",
            "technology": "技术",
            "academic": "学术",
            "global": "全球监控"
        }

        for domain, items in domain_groups.items():
            if not items:
                continue
            name = domain_names.get(domain, domain)
            group_text = f"【{name} 领域】:\n" + "\n".join([
                f"- {item.get('title')}: {item.get('body', '')[:100]}..." if item.get('body') else f"- {item.get('title')}"
                for item in items[:15]
            ])
            context_parts.append(group_text)
        
        context = "\n\n".join(context_parts)

        if target_domain and target_domain != "all":
            domain_cn = domain_names.get(target_domain, target_domain)
            prompt = (
                f"你是一个资深情报分析专家。请针对选定的【{domain_cn}】领域进行深度情报综述。\n"
                "要求：\n"
                f"1. 仅针对 {domain_cn} 领域的内容进行总结，不要混入其他领域。\n"
                "2. 归纳当前该领域的核心趋势、重大事件及其潜在影响。\n"
                "3. 语气要极其专业、客观、敏锐。\n"
                "4. 字数控制在 300 字以内。\n"
                "5. 必须使用中文，采用 Markdown 格式（可以包含加粗、列表）。\n\n"
                "情报内容：\n"
                f"{context}\n\n"
                "综述："
            )
        else:
            prompt = (
                "你是一个资深全球情报分析师。请针对以下各领域的最新动态，提供一份综合简报。\n"
                "要求：\n"
                "1. 按领域（经济、技术、学术、全球监控）进行综述。\n"
                "2. 每个领域的总结要精炼，突出最重要的高热度或高严重度事件。\n"
                "3. 语气要专业、冷静。\n"
                "4. 总字数控制在 250 字以内。\n"
                "5. 必须使用中文，采用 Markdown 格式（使用 ## 分段）。\n\n"
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
                        "max_tokens": 500
                    }
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                return content

        except Exception as e:
            logger.error(f"LLMClient: 生成摘要失败: {e}")
            return f"智能化综述暂时不可用 (Error: {str(e)[:50]}...)"

    def _mock_domain_summary(self, domain_groups: dict[str, list[dict]], target_domain: Optional[str] = None) -> str:
        """分领域的模拟摘要"""
        if target_domain and target_domain != "all":
            name = target_domain
            items = domain_groups.get(target_domain, [])
            return f"### {name} 领域深度分析 (模拟)\n\n该领域目前监测到 {len(items)} 条重要动态。主要趋势包括 {items[0].get('title') if items else '暂无数据'} 等。建议持续关注后续演化。"

        lines = ["## 全球情报综述 (模拟数据)"]
        
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
