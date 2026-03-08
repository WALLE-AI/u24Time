# -*- coding: utf-8 -*-
"""
SimulationRunner - OASIS 社区模拟运行引擎
控制双平台 (Twitter + Reddit) 的并行模拟推演进程。
"""

import asyncio
import json
import time
from typing import AsyncIterator, Dict, Any, Optional
from loguru import logger
from pydantic import BaseModel

from agents.config import agents_settings

class SimulationState(BaseModel):
    simulation_id: str
    is_running: bool
    current_round: int
    max_rounds: int
    actions_count: int
    platform: str
    status_msg: str

class SimulationRunner:
    """
    负责启动、停止和状态监控由 OASIS 驱动的仿真进程。
    需要 OASIS 环境依赖。
    """
    def __init__(self):
        self._states: Dict[str, SimulationState] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self.default_max_rounds = agents_settings.OASIS_MAX_ROUNDS
        
    async def start(self, simulation_id: str, platform: str = "parallel",
                    max_rounds: Optional[int] = None, graph_id: Optional[str] = None) -> SimulationState:
        """开始一次全新的演化仿真"""
        
        rounds = max_rounds if max_rounds is not None else self.default_max_rounds
        
        state = SimulationState(
            simulation_id=simulation_id,
            is_running=True,
            current_round=0,
            max_rounds=rounds,
            actions_count=0,
            platform=platform,
            status_msg="Initializing OASIS Environment..."
        )
        self._states[simulation_id] = state
        
        # 将实际运行逻辑提交给后台 asyncio.Task
        task = asyncio.create_task(self._run_simulation_loop(simulation_id, graph_id))
        self._tasks[simulation_id] = task
        
        return state

    def get_state(self, simulation_id: str) -> Optional[SimulationState]:
        return self._states.get(simulation_id)
        
    def stop(self, simulation_id: str) -> bool:
        task = self._tasks.get(simulation_id)
        if task and not task.done():
            task.cancel()
            
        state = self._states.get(simulation_id)
        if state:
            state.is_running = False
            state.status_msg = "Terminated by user."
            return True
            
        return False

    async def _run_simulation_loop(self, simulation_id: str, graph_id: Optional[str]):
        """后台轮询执行，模拟 OASIS 仿真"""
        state = self._states.get(simulation_id)
        if not state:
            return
            
        logger.info(f"SimulationRunner: 仿真 {simulation_id} 启动")
            
        try:
            # 检测 OASIS 环境依赖 (此处以 Mock 和旁路逻辑为演示)
            try:
                # from oasis.social import Simulator
                pass
            except ImportError:
                logger.warning("SimulationRunner: OASIS 未安装，进入降级演示模式")
                
            state.status_msg = "Running"
            
            # 模拟执行轮次
            while state.current_round < state.max_rounds and state.is_running:
                # 【实际逻辑】：
                # 1. simulator.step() 
                # 2. 如果提供了 graph_id, 进行 Memory Context 交互
                # 3. 统计本轮 agents 发言数 action_count
                
                await asyncio.sleep(2.0)  # 演示用时间压缩 (真实中可能需要分钟级演算)
                
                state.current_round += 1
                state.actions_count += 5 # 假设每轮产生 5 个 action
                
                if state.current_round % 10 == 0:
                    logger.info(f"SimulationRunner: 仿真 {simulation_id} 进度: {state.current_round}/{state.max_rounds}")
                    
            if state.is_running:
                state.is_running = False
                state.status_msg = "Completed"
                logger.info(f"SimulationRunner: 仿真 {simulation_id} 天然完成")
            
        except asyncio.CancelledError:
            logger.info(f"SimulationRunner: 仿真 {simulation_id} 被强行取消")
            if state:
                state.is_running = False
                state.status_msg = "Cancelled"
        except Exception as e:
            logger.error(f"SimulationRunner: 仿真异常: {e}")
            if state:
                state.is_running = False
                state.status_msg = f"Error: {e}"
        finally:
            if simulation_id in self._tasks:
                del self._tasks[simulation_id]

    async def state_stream(self, simulation_id: str) -> AsyncIterator[dict]:
        """SSE 流，实时向前端报告推演状态"""
        while True:
            state = self._states.get(simulation_id)
            if not state:
                yield {"status": "error", "message": "Simulation not found"}
                break
                
            # 发送状态快照
            yield state.model_dump()
            
            if not state.is_running:
                break
                
            await asyncio.sleep(2)
