# -*- coding: utf-8 -*-
"""
Pydantic Request/Response Models 
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class BettaFishRunRequest(BaseModel):
    query: str = Field(..., description="事件分析查询词")
    platforms: List[str] = Field(default=["weibo", "bilibili", "douyin", "zhihu"], description="爬取平台")
    max_reflections: int = Field(default=2, ge=0, le=3, description="反思最大轮数")

class SentimentRequest(BaseModel):
    texts: List[str] = Field(..., description="待情感分析的文本列表")
    confidence_threshold: float = Field(default=0.5, description="置信度阈值")

class ForumMessage(BaseModel):
    source: Literal["QUERY", "MEDIA", "INSIGHT", "HOST"] = Field(..., description="消息来源")
    content: str = Field(..., description="消息内容 Markdown")
    timestamp: str = Field(..., description="ISO 时间戳")

class DBSearchRequest(BaseModel):
    tool: Literal["hot", "global", "date", "comment", "platform"] = Field(..., description="搜索查询工具名")
    params: dict = Field(..., description="工具参数")
