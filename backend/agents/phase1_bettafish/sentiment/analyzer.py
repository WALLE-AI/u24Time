# -*- coding: utf-8 -*-
"""
WeiboMultilingualSentimentAnalyzer 情感分析器
采用可选依赖: transformers, torch
"""

import sys
from typing import List, Dict, Tuple
from loguru import logger
from pydantic import BaseModel

from agents.config import agents_settings
from data_alignment.schema import CanonicalItem

class SentimentResult(BaseModel):
    label: str
    score: float
    raw_scores: Dict[str, float]
    analysis_performed: bool = True

class BatchSentimentResult(BaseModel):
    distribution: Dict[str, int]
    summary: str
    results: List[SentimentResult]
    analysis_performed: bool = True

class SentimentAnalyzer:
    """
    多语言情感分析器（懒加载深度学习模型）
    无 torch 环境时安全降级
    """
    
    # 根据模型输出映射到 CanonicalItem.sentiment 字段 (-1.0 to 1.0)
    SENTIMENT_SCORE_MAP = {
        0: -1.0,  # "非常负面" / "very_negative"
        1: -0.5,  # "负面" / "negative"
        2:  0.0,  # "中性" / "neutral"
        3:  0.5,  # "正面" / "positive"
        4:  1.0,  # "非常正面" / "very_positive"
    }

    LABEL_NAME_MAP = {
        0: "非常负面",
        1: "负面",
        2: "中立",
        3: "正面",
        4: "非常正面"
    }

    def __init__(self, enabled: bool = None):
        if enabled is None:
            enabled = agents_settings.SENTIMENT_MODEL_ENABLED
            
        self.enabled = enabled
        self.model_name = agents_settings.SENTIMENT_MODEL_NAME
        self.pipeline = None
        self._is_initialized = False
        
    def initialize(self) -> bool:
        """懒启动模型，无依赖则返回 False 不抛异常"""
        if not self.enabled:
            logger.info("SentimentAnalyzer: 模型被配置为禁用 (SENTIMENT_MODEL_ENABLED=False)")
            return False
            
        if self._is_initialized:
            return True
            
        try:
            import torch
            from transformers import pipeline
            from transformers.utils.logging import set_verbosity_error
            set_verbosity_error()
            
            # 检测设备
            device = -1 # default CPU
            if torch.cuda.is_available():
                device = 0
                logger.info("SentimentAnalyzer: 使用 CUDA")
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                device = "mps"
                logger.info("SentimentAnalyzer: 使用 Apple MPS (Metal)")
            else:
                logger.info("SentimentAnalyzer: 使用 CPU")
                
            logger.info(f"SentimentAnalyzer: 正在加载模型 {self.model_name}...")
            self.pipeline = pipeline(
                "sentiment-analysis", 
                model=self.model_name, 
                device=device,
                top_k=None # 返回所有分数的分布
            )
            self._is_initialized = True
            logger.info("SentimentAnalyzer: 模型加载完成")
            return True
            
        except ImportError as e:
            logger.warning(f"SentimentAnalyzer: 缺少模型运行库 ({e})。降级为存根模式。提示: uv add torch transformers")
            self.enabled = False
            return False
        except Exception as e:
            logger.error(f"SentimentAnalyzer: 模型加载失败 ({e})。降级为存根模式。")
            self.enabled = False
            return False

    def analyze_single(self, text: str) -> SentimentResult:
        if not self._is_initialized and self.enabled:
            self.initialize()
            
        if not self._is_initialized or not self.pipeline:
            return SentimentResult(
                label="unknown", 
                score=0.0, 
                raw_scores={}, 
                analysis_performed=False
            )
            
        try:
            # Pipeline(top_k=None) 返回 List[List[Dict[label, score]]]
            predictions = self.pipeline(text[:512]) # 截断长度限制
            dist = {p['label']: p['score'] for p in predictions[0]}
            
            # Find the top label by parsing label name like "4 stars" or "very positive"
            # Since model output formats vary, fallback simple finding max score
            top_label = max(dist.items(), key=lambda x: x[1])
            
            return SentimentResult(
                label=str(top_label[0]),
                score=top_label[1],
                raw_scores=dist,
                analysis_performed=True
            )
        except Exception as e:
            logger.error(f"SentimentAnalyzer: 分析异常 - {e}")
            return SentimentResult(label="error", score=0.0, raw_scores={}, analysis_performed=False)

    def analyze_batch(self, texts: List[str]) -> BatchSentimentResult:
        if not texts:
            return BatchSentimentResult(distribution={}, summary="No texts provided", results=[])
            
        # 安全降级模式
        if not self._is_initialized and self.enabled:
            self.initialize()
            
        if not self._is_initialized or not self.pipeline:
            dummy_res = SentimentResult(label="unknown", score=0.0, raw_scores={}, analysis_performed=False)
            return BatchSentimentResult(
                distribution={}, 
                summary="Sentiment model not loaded", 
                results=[dummy_res for _ in texts],
                analysis_performed=False
            )
            
        results = []
        distribution = {label: 0 for label in self.LABEL_NAME_MAP.values()}
        
        # 实际生产中可使用 dataset 形式通过 pipeline 获得更高吞吐量
        for text in texts:
            if not text.strip():
                continue
            res = self.analyze_single(text)
            results.append(res)
            
            # 将模型的 raw label 转为友好的分布名称
            # 这是一个启发式转换，假设模型基于 1-5 评论极性分类 (例如 1 star, 5 stars)
            simplified_label = "中立"
            raw_label_str = res.label.lower()
            if "5" in raw_label_str or "very_positive" in raw_label_str:
                simplified_label = "非常正面"
            elif "4" in raw_label_str or "positive" in raw_label_str:
                simplified_label = "正面"
            elif "1" in raw_label_str or "very_negative" in raw_label_str:
                simplified_label = "非常负面"
            elif "2" in raw_label_str or "negative" in raw_label_str:
                simplified_label = "负面"
                
            distribution[simplified_label] = distribution.get(simplified_label, 0) + 1
            
        # 简单结论生成
        total = len(results)
        pos = distribution.get("正面", 0) + distribution.get("非常正面", 0)
        neg = distribution.get("负面", 0) + distribution.get("非常负面", 0)
        
        if pos > neg * 2:
            summary = "总体呈现明显正向情绪"
        elif neg > pos * 2:
            summary = "总体呈现明显负面且存在一定舆情危机"
        else:
            summary = "情绪分布较均匀，无明显偏向"
            
        return BatchSentimentResult(
            distribution=distribution,
            summary=summary,
            results=results
        )

    async def analyze_canonical_items(self, items: List[CanonicalItem]) -> List[CanonicalItem]:
        """为一批库模型填充 sentiment 字段并返回"""
        if not items:
            return []
            
        texts = [i.title + " " + (i.body or "") for i in items]
        batch_res = self.analyze_batch(texts)
        
        if not batch_res.analysis_performed:
            return items
            
        for item, res in zip(items, batch_res.results):
            raw_label_str = res.label.lower()
            score = 0.0 # 默认为中性
            if "5" in raw_label_str or "very_positive" in raw_label_str:
                score = 1.0
            elif "4" in raw_label_str or "positive" in raw_label_str:
                score = 0.5
            elif "1" in raw_label_str or "very_negative" in raw_label_str:
                score = -1.0
            elif "2" in raw_label_str or "negative" in raw_label_str:
                score = -0.5
                
            item.sentiment = score
            
        return items
