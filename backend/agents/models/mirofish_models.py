# -*- coding: utf-8 -*-
"""
Pydantic Models for MiroFish
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field

class OntologyRequest(BaseModel):
    document_texts: List[str] = Field(..., description="用于生成本体的文本文档列表")
    simulation_requirement: str = Field(..., description="仿真环境与目标分析需求")
    additional_context: Optional[str] = Field(None, description="附加指令/上下文")

class GraphBuildRequest(BaseModel):
    text: str = Field(..., description="用于构建知识图谱的原始文本")
    ontology: dict = Field(..., description="OntologyGenerator 生成的本体定义(JSON)")
    graph_name: Optional[str] = Field(None, description="Zep Cloud 图谱名称")

class SimulateRequest(BaseModel):
    simulation_id: str = Field(..., description="唯一仿真 ID")
    platform: Literal["twitter", "reddit", "parallel"] = Field(default="parallel", description="要模拟的平台环境")
    max_rounds: Optional[int] = Field(None, description="最大覆盖轮次")
    graph_id: Optional[str] = Field(None, description="绑定的知识图谱 ID(更新记忆)")

class PredictRequest(BaseModel):
    simulation_id: str = Field(..., description="执行预测的仿真环境 ID")
    graph_id: str = Field(..., description="要查询参考的图谱 ID")
    query: str = Field(..., description="预测用户的提问/预测问题")
