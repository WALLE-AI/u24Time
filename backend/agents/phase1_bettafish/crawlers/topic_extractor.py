# -*- coding: utf-8 -*-
"""
BroadTopicExtraction — 话题提取器
调用 CrawlerEngine 的 run_hotsearch() 获取热搜数据，再用 LLM 提炼核心关键词。
"""

import json
from typing import List
from loguru import logger

from utils.llm_client import LLMClient
from crawler_engine.engine import CrawlerEngine
from data_alignment.schema import CanonicalItem
from agents.tools.web_fetch import WebFetchTool, WebFetchParams
from agents.tools.base import ToolContext

class TopicExtractor:
    def __init__(self, engine: CrawlerEngine, llm: LLMClient):
        self._engine = engine
        self._llm = llm

    async def run(self, count: int = 100) -> List[str]:
        """
        执行话题提取管线
        1. 运行全局热搜采集 (NewsNow + GitHub Trending 等)
        2. 提取文本标题
        3. LLM 数据降维，提取核心词
        """
        logger.info("TopicExtractor: 开始获取全局热搜数据...")
        try:
            # 1. 采集热搜数据 (内部已落库 CanonicalItem)
            items: List[CanonicalItem] = await self._engine.run_hotsearch()
            logger.info(f"TopicExtractor: 成功获取 {len(items)} 条热搜数据")
            
            if not items:
                return []

            # 2. 提取有效标题集合 (去重)
            texts = list({item.title.strip() for item in items if item.title and len(item.title.strip()) > 2})
            
            # API 限制或性能考虑，最多取前 300 条供 LLM 提炼
            texts_subset = texts[:300]
            logger.info(f"TopicExtractor: 准备向 LLM 输入 {len(texts_subset)} 条独立标题提取关键词")
            
            # 3. LLM 提炼
            keywords = await self._extract_keywords_llm(texts_subset, count)
            logger.info(f"TopicExtractor: 成功提炼 {len(keywords)} 个核心关键词")
            
            return keywords

        except Exception as e:
            logger.error(f"TopicExtractor: 提取失败: {e}")
            return []

    async def _extract_keywords_llm(self, texts: List[str], count: int) -> List[str]:
        """
        调用 LLM，提炼 count 个核心名词关键词（不重复、中英混合）
        """
        if not self._llm.api_key:
            logger.warning("TopicExtractor: 未配置 LLM_API_KEY，降级为直接截取高频词 (模拟)")
            return [t[:6] for t in texts[:count]]

        prompt = (
            f"你是一个资深的新闻舆情分析师。下面是今天各大平台的即时热搜列表。\n"
            f"请从这 {len(texts)} 条标题中，提炼出当前最受关注的 {count} 个核心独立事件/实体关键词（名词为主）。\n"
            f"要求：\n"
            f"1. 主要是专有名词、人名、公司名、地名、事件简略名（如 'OpenAI'、'英伟达'、'中东冲突'、'A股'）。\n"
            f"2. 中英混合皆可，去除无意义的语气词。\n"
            f"3. 必须输出严格的 JSON 数组格式，例如: [\"词1\", \"词2\"...]\n\n"
            f"热搜标题列表：\n"
            + "\n".join([f"- {t}" for t in texts])
        )

        try:
            # Call the standard self._llm.chat which handles provider switching cleanly
            # First, check if texts are URLs
            processed_texts = []
            web_fetcher = WebFetchTool()
            ctx = ToolContext(
                session_id="topic_extractor",
                message_id="topic_extractor",
                agent="topic_extractor",
                user_id="system"
            )
            
            for text in texts:
                if text.startswith("http://") or text.startswith("https://"):
                    # Extract Markdown from URL
                    try:
                        logger.info(f"TopicExtractor: Fetching content parsing URL {text}")
                        result = await web_fetcher.execute(WebFetchParams(url=text, format="markdown", use_jina=True), ctx)
                        if result.output and not result.output.startswith("Error:"):
                            # Only keep first 2000 chars of markdown to avoid bloating context
                            processed_texts.append(f"Source URL: {text}\nContent Snippet: {result.output[:2000]}")
                        else:
                            processed_texts.append(text)
                    except Exception as e:
                        logger.warning(f"TopicExtractor: Failed to fetch {text}: {e}")
                        processed_texts.append(text)
                else:
                    processed_texts.append(text)
            
            # Reconstruct prompt with processed texts (which might now be markdown summaries)
            prompt = (
                f"你是一个资深的新闻舆情分析师。下面是一组即时热搜标题或网页正文内容摘要。\n"
                f"请从中提炼出当前最受关注的 {count} 个核心独立事件/实体关键词（名词为主）。\n"
                f"要求：\n"
                f"1. 主要是专有名词、人名、公司名、地名、事件简略名（如 'OpenAI'、'英伟达'、'中东冲突'、'A股'）。\n"
                f"2. 中英混合皆可，去除无意义的语气词。\n"
                f"3. 必须输出严格的 JSON 数组格式，例如: [\"词1\", \"词2\"...]\n\n"
                f"内容列表：\n"
                + "\n\n".join([f"--- Item ---\n{t}" for t in processed_texts])
            )

            response = await self._llm.chat(
                messages=[
                    {"role": "system", "content": "You are a precise data extraction system. Output JSON array only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3
            )
            
            content = response.strip()
            logger.debug(f"TopicExtractor Raw LLM Response: {content}")
            
            # Clean up markdown JSON block if present
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            try:
                # Parse as array
                result = json.loads(content)
                if isinstance(result, list):
                    return result[:count]
                elif isinstance(result, dict):
                    # Attempt to extract from a wrapper
                    for k, v in result.items():
                        if isinstance(v, list):
                            return v[:count]
            except json.JSONDecodeError:
                logger.error(f"TopicExtractor: LLM 返回的不是有效 JSON:\n{content}")
                
            return []
            
        except Exception as e:
            logger.error(f"TopicExtractor: LLM 提取关键词失败: {e}")
            return []
