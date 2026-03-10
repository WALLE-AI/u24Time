# -*- coding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import List, Optional

class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = 0.0
    sentiment: Optional[str] = None  # 情感标签 (pos, neg, neu)

class DeepSearchState(BaseModel):
    """
    BetaFish Phase 1 - 深度查询分析状态流转对象
    """
    original_query: str
    current_queries: List[str] = Field(default_factory=list)
    search_results: List[SearchResult] = Field(default_factory=list)
    reflections_count: int = 0
    max_reflections: int = 2
    summarized_paragraph: str = ""
    is_completed: bool = False
