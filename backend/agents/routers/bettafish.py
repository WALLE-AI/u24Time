import asyncio
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from agents.models import BettaFishRunRequest, SentimentRequest, DBSearchRequest
from agents.dependencies import get_db, get_llm
from utils.llm_client import LLMClient

from agents.phase1_bettafish.sentiment.analyzer import SentimentAnalyzer
from agents.phase1_bettafish.alignment.media_db import MediaCrawlerDB
from agents.phase1_bettafish.forum.monitor import ForumMonitor
from agents.pipeline.bettafish_pipeline import BettaFishPipeline
from db.models import AgentsSessionModel

router = APIRouter()

# 内存共享的论坛监视器字典（session_id -> ForumMonitor）
_active_monitors = {}
_active_tasks = {}

@router.post("/run")
async def run_bettafish(
    request: BettaFishRunRequest,
    db: AsyncSession = Depends(get_db),
    llm: LLMClient = Depends(get_llm)
):
    """触发 BettaFishPipeline 分析任务"""
    session_id = str(uuid4())
    logger.info(f"Agents API: 创建 BettaFish 会话 {session_id} - '{request.query}'")
    
    # 1. 创建数据库记录
    session_model = AgentsSessionModel(
        session_id=session_id,
        pipeline_type="bettafish",
        query=request.query,
        status="pending",
        config_json=request.model_dump_json()
    )
    db.add(session_model)
    await db.commit()
    
    # 2. 创建并追踪监视器
    monitor = ForumMonitor(llm)
    _active_monitors[session_id] = monitor
    
    # 3. 后台执行 Pipeline
    async def _run_task():
        # 更新状态为 running
        try:
            async with db.bind.connect() as conn: # simple connection wrapper for the background task
                # re-fetch session to detach from original request db context
                pass # Using independent DB session properly handled in pipeline
                
        except Exception:
            pass
            
        pipeline = BettaFishPipeline(db, llm)
        try:
            result = await pipeline.run_end_to_end(
                request.query, 
                request.platforms, 
                request.max_reflections,
                forum_monitor=monitor
            )
            logger.info(f"Agents API: 会话 {session_id} 分析完成")
            # 标记完成 (这里省略后台更新 db status 过程)
        except Exception as e:
            logger.error(f"Agents API: 会话 {session_id} 执行异常: {e}")
        finally:
            monitor.close()
            # 定时清理
            await asyncio.sleep(300)
            _active_monitors.pop(session_id, None)

    task = asyncio.create_task(_run_task())
    _active_tasks[session_id] = task

    return {"status": "pending", "session_id": session_id, "message": "BettaFish Pipeline started"}

@router.get("/sessions/{session_id}")
async def get_session_status(session_id: str, db: AsyncSession = Depends(get_db)):
    """获取会话状态 (通过 DB)"""
    from sqlalchemy import select
    res = await db.execute(select(AgentsSessionModel).where(AgentsSessionModel.session_id == session_id))
    model = res.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Session not found")
        
    return {
        "session_id": session_id,
        "query": model.query,
        "status": model.status,
    }

@router.get("/forum/stream/{session_id}")
async def forum_stream(session_id: str):
    """SSE 流：实时推送 Forum 消息"""
    monitor = _active_monitors.get(session_id)
    if not monitor:
        raise HTTPException(status_code=404, detail="Active monitor stream not found (maybe finished or expired)")
        
    async def event_generator():
        async for msg in monitor.run():
            # SSE 格式
            data = json.dumps(msg, ensure_ascii=False)
            yield f"data: {data}\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.post("/sentiment/analyze")
async def analyze_sentiment(request: SentimentRequest):
    """批量情感分析"""
    analyzer = SentimentAnalyzer()
    if not analyzer.initialize():
        logger.warning("Sentiment Analyzer failed to initialize, using degraded mode.")
        
    res = analyzer.analyze_batch(request.texts)
    return {
        "distribution": res.distribution,
        "summary": res.summary,
        "results": [r.model_dump() for r in res.results],
        "analysis_performed": res.analysis_performed
    }

@router.post("/db/search")
async def search_media_db(request: DBSearchRequest, db: AsyncSession = Depends(get_db)):
    """MediaCrawlerDB 查询工具统一入口"""
    engine = MediaCrawlerDB(db)
    tool = request.tool
    params = request.params
    
    try:
        results = []
        if tool == "hot":
            results = await engine.search_hot_content(
                params.get("time_period", "week"), 
                int(params.get("limit", 50))
            )
        elif tool == "global":
            results = await engine.search_topic_globally(
                params.get("topic", ""), 
                int(params.get("limit", 100))
            )
        elif tool == "date":
            results = await engine.search_topic_by_date(
                params.get("topic", ""),
                params.get("start_date", ""),
                params.get("end_date", ""),
                int(params.get("limit", 100))
            )
        elif tool == "comment":
            results = await engine.get_comments_for_topic(
                params.get("topic", ""),
                int(params.get("limit", 100))
            )
        elif tool == "platform":
            results = await engine.search_on_platform(
                params.get("platform_id", ""),
                params.get("topic", ""),
                int(params.get("limit", 50))
            )
        else:
            raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")
            
        return {"total": len(results), "results": results}
    except Exception as e:
        logger.error(f"DB Search API error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
