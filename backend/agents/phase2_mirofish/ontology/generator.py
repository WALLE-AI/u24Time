# -*- coding: utf-8 -*-
"""
OntologyGenerator - 社交媒体仿真本体生成器
移植自 MiroFish，基于预设的 10 实体 + 10 关系框架动态实例化。
"""

import json
from typing import List, Dict
from loguru import logger

from utils.llm_client import LLMClient

class OntologyGenerator:
    """
    LLM 生成指定场景下的实体和关系类型定义，
    这些定义后续供 Zep Cloud GraphBuilder 使用。
    """
    MAX_TEXT_LEN = 50_000  # 文本截断长度

    def __init__(self, llm: LLMClient):
        self._llm = llm

    async def generate(self, document_texts: List[str], requirement: str) -> Dict:
        """
        生成本体定义
        :param document_texts: 相关的事件文本、新闻报道
        :param requirement: 仿真目标要求，如“分析用户对XX事件的情绪演化”
        :return: 包含 entity_types, edge_types, analysis_summary 的字典
        """
        logger.info(f"OntologyGenerator: 开始生成本体，包含 {len(document_texts)} 篇参考材料")
        
        combined_text = "\n\n---\n\n".join(document_texts)
        if len(combined_text) > self.MAX_TEXT_LEN:
            combined_text = combined_text[:self.MAX_TEXT_LEN] + "..."

        prompt = f"""
你是一个精通社会网络分析和知识图谱构建的专家系统。
我们需要为一次基于社交媒体（如Twitter、Reddit）的沙盘演化图谱设计一个专属的小型知识图谱本体（Ontology）。

仿真目标需求：
{requirement}

背景参考材料资料：
{combined_text}

请基于上述材料和目标，设计合适的知识图谱实体类型（Entity Types）和边/关系类型（Edge Types）。
图谱必须能够精细刻画“信息在人群中的传播”、“群体情绪的极化”以及“特定事件/话题的演化”。

【强约束要求】：
1. 实体类型 (Entity Types)：设计不多于 10 个核心实体类型。
   - 必须包含代表用户的实体（要求命名为 'Person', 'Organization' 之一）
   - 必须包含代表信息的实体（如 'Post', 'Topic', 'Event', 'Rumor' 等）
   - 必须包含代表情感/立场的实体（如 'Stance', 'Emotion'）
2. 关系类型 (Edge Types)：设计不多于 10 个核心关系类型。
   - 必须能连接上述实体（例如 Person -> Post (POSTED), Person -> Emotion (EXPRESSES), Post -> Post (REPLIES_TO)）
3. 返回格式必须为严格的 JSON。不要有任何额外的文本、Markdown 记号等。
4. JSON 结构如下：
{{
    "analysis_summary": "对当前数据集和需求的简短网络特征分析，说明为什么选择这些实体和边。",
    "entity_types": [
        {{
            "name": "实体类型英文名 (大驼峰，如 Person)",
            "description": "实体类型描述"
        }}
    ],
    "edge_types": [
        {{
            "name": "关系类型英文名 (大写加下划线，如 EXPRESSES)",
            "description": "关系的业务含义"
        }}
    ]
}}
"""
        
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                payload = {
                    "model": self._llm.model,
                    "messages": [
                        {"role": "system", "content": "You are a professional ontology designer. Output strictly JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                }
                
                if "openai" in self._llm.base_url or "api.openai.com" in self._llm.base_url:
                    payload["response_format"] = {"type": "json_object"}

                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}", "Content-Type": "application/json"},
                    json=payload
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"].strip()
                
                # 清洗 JSON
                if content.startswith("```json"):
                    content = content[7:]
                if content.startswith("```"):
                    content = content[3:]
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

                parsed = json.loads(content)
                logger.info(f"OntologyGenerator: 本体生成成功: {len(parsed.get('entity_types', []))} 个实体，{len(parsed.get('edge_types', []))} 个关系")
                
                # 必须拥有兜底的 Person / Organization
                entities = [e["name"].lower() for e in parsed.get("entity_types", [])]
                if "person" not in entities and "organization" not in entities:
                    parsed.setdefault("entity_types", []).append({
                        "name": "Person", "description": "Fallback entity for a user or agent"
                    })
                    
                return parsed
                
        except Exception as e:
            logger.error(f"OntologyGenerator: 本体生成失败 - {e}")
            # Fallback 默认本体
            return {
                "analysis_summary": "Fallback Default Ontology due to generation failure.",
                "entity_types": [
                    {"name": "Person", "description": "A user driving the discussion."},
                    {"name": "Post", "description": "A discrete social media entry."},
                    {"name": "Topic", "description": "The central theme of discussions."}
                ],
                "edge_types": [
                    {"name": "POSTED", "description": "Person -> Post"},
                    {"name": "ABOUT", "description": "Post -> Topic"},
                    {"name": "REPLIED_TO", "description": "Post -> Post"}
                ]
            }
