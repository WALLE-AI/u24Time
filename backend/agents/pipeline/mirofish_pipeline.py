# -*- coding: utf-8 -*-
"""
MiroFish Pipeline — 本体-图谱-推演工作流编排
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Dict
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from utils.llm_client import LLMClient
from agents.phase2_mirofish.ontology.generator import OntologyGenerator
from agents.phase2_mirofish.graph.builder import GraphBuilderService
from agents.phase2_mirofish.simulation.runner import SimulationRunner, SimulationState
from agents.phase2_mirofish.prediction.report_agent import PredictionReportAgent

class MiroFishPipeline:
    """
    负责依次执行：
    1. Ontology 生成 (LLM)
    2. 基于 Ontology 和文本提取 Zep 图谱
    3. 启动 OASIS 双平台仿真 (后台轮询)
    4. 仿真时/后 提供推演报告 (LLM)
    """

    def __init__(self, db_session: AsyncSession, llm: LLMClient):
        self._db = db_session
        self._llm = llm
        
        # 服务初始化
        self.ontology = OntologyGenerator(llm)
        self.graph = GraphBuilderService()
        # 由于 runner 需要保持后台状态，一般在全局作用域复用单例。
        # 这里便于集成，暂时局部实例化或引入外部传入。
        # 为了生产级应用，通常将 Runner 绑定在 FastAPI app.state 上
        self.runner = SimulationRunner()
        self.reporter = PredictionReportAgent(llm, self.graph, self.runner)

    async def run_end_to_end(
        self, 
        simulation_id: str,
        document_texts: List[str], 
        requirement: str,
        max_rounds: int = 144
    ) -> Dict:
        """
        全自动化端到端执行链路:
        (注：真实环境中仿真耗时极长，可能只运行前序或将其全部作为后台宏任务。
        这里我们编排同步的预处理 + 异步的仿真启动)
        """
        logger.info(f"MiroFishPipeline: 开始执行端到端演化 '{simulation_id}'")
        
        # 1. 生成 Ontology
        ontology_data = await self.ontology.generate(document_texts, requirement)
        
        # 2. 调度 GraphBuilder，建立图谱
        # 此处简化为使用合并文本作为图谱构建的源干数据
        combined_text = "\n\n".join(document_texts)
        if len(combined_text) > 100_000:
            combined_text = combined_text[:100_000]
            
        graph_task = await self.graph.build(combined_text, ontology_data, name=simulation_id)
        graph_id = graph_task.get("graph_id")
        
        # 3. 启动后台仿真任务
        state: SimulationState = await self.runner.start(
            simulation_id=simulation_id,
            platform="parallel",
            max_rounds=max_rounds,
            graph_id=graph_id
        )
        
        return {
            "simulation_id": simulation_id,
            "ontology": ontology_data,
            "graph_task": graph_task,
            "simulation_state": state.model_dump(),
            "status": "simulation_running",
            "message": "The environment ontology and graph have been initialized. Simulation is now running in the background."
        }
