# -*- coding: utf-8 -*-
"""
MiroFish API Routers — 知识图谱与沙盒推演系统
"""

import asyncio
from typing import Dict, Any
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from agents.models import OntologyRequest, GraphBuildRequest, SimulateRequest, PredictRequest
from agents.dependencies import get_db, get_llm
from utils.llm_client import LLMClient

# Import Services
from agents.phase2_mirofish.ontology.generator import OntologyGenerator
from agents.phase2_mirofish.graph.builder import GraphBuilderService
from agents.phase2_mirofish.simulation.runner import SimulationRunner
from agents.phase2_mirofish.prediction.report_agent import PredictionReportAgent

from agents.pipeline.mirofish_pipeline import MiroFishPipeline
from db.models import AgentsSessionModel

router = APIRouter()

# 共享 Runner 实例以维持状态
_shared_runner = SimulationRunner()
# 共享 Graph 服务缓存初始化
_shared_graph = GraphBuilderService()

@router.post("/ontology/generate")
async def generate_ontology(request: OntologyRequest, llm: LLMClient = Depends(get_llm)):
    generator = OntologyGenerator(llm)
    res = await generator.generate(request.document_texts, request.simulation_requirement)
    return res

@router.post("/graph/build")
async def build_graph(request: GraphBuildRequest):
    res = await _shared_graph.build(request.text, request.ontology, request.graph_name)
    return res

@router.get("/graph/{graph_id}")
async def get_graph(graph_id: str):
    res = await _shared_graph.get_data(graph_id)
    return res

@router.post("/simulate/start")
async def start_simulation(request: SimulateRequest):
    state = await _shared_runner.start(
        simulation_id=request.simulation_id,
        platform=request.platform,
        max_rounds=request.max_rounds,
        graph_id=request.graph_id
    )
    return state.model_dump()

@router.get("/simulate/{simulation_id}")
async def get_simulation(simulation_id: str):
    state = _shared_runner.get_state(simulation_id)
    if not state:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return state.model_dump()

@router.post("/simulate/{simulation_id}/stop")
async def stop_simulation(simulation_id: str):
    success = _shared_runner.stop(simulation_id)
    if not success:
        raise HTTPException(status_code=404, detail="Failed to stop (maybe already stopped or not found)")
    return {"status": "stopped", "simulation_id": simulation_id}

@router.get("/simulate/{simulation_id}/stream")
async def stream_simulation(simulation_id: str):
    """SSE 推送仿真状态更新"""
    state = _shared_runner.get_state(simulation_id)
    if not state:
        raise HTTPException(status_code=404, detail="Simulation not found")
        
    async def ev_gen():
        import json
        async for s_dict in _shared_runner.state_stream(simulation_id):
            yield f"data: {json.dumps(s_dict, ensure_ascii=False)}\n\n"
            
    return StreamingResponse(ev_gen(), media_type="text/event-stream")

@router.post("/predict")
async def predict_report(request: PredictRequest, llm: LLMClient = Depends(get_llm)):
    reporter = PredictionReportAgent(llm, _shared_graph, _shared_runner)
    report_md = await reporter.generate_report(request.simulation_id, request.graph_id, request.query)
    return {"report": report_md}

@router.post("/pipeline/run")
async def run_mirofish_pipeline(
    request: OntologyRequest, 
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm)
):
    """
    接收 Ontology 生成参数，直接执行全流水线
    """
    pipeline_id = str(uuid4())
    logger.info(f"Agents API: 创建 MiroFish 会话 {pipeline_id}")
    
    # 落库
    session_model = AgentsSessionModel(
        session_id=pipeline_id,
        pipeline_type="mirofish",
        query=request.simulation_requirement,
        status="running",
        config_json=request.model_dump_json()
    )
    db.add(session_model)
    await db.commit()
    
    # 因为此服务较为重型且耗时较长，通过后台任务分离
    async def background_pipeline():
        pipeline = MiroFishPipeline(db, llm)
        pipeline.graph = _shared_graph
        pipeline.runner = _shared_runner
        
        try:
            res = await pipeline.run_end_to_end(
                simulation_id=pipeline_id,
                document_texts=request.document_texts,
                requirement=request.simulation_requirement,
                max_rounds=144
            )
            logger.info(f"Agents API [MiroFish]: {pipeline_id} Pushed to Runner.")
            # db mark success省略
        except Exception as e:
            logger.error(f"Agents API [MiroFish]: {pipeline_id} Failed - {e}")
            
    asyncio.create_task(background_pipeline())
    
    return {"pipeline_id": pipeline_id, "status": "initializing_ontology_and_graph"}
