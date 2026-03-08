# -*- coding: utf-8 -*-
"""
PredictionReportAgent - 基于演化仿真结果及知识图谱提供预测报告
"""

import json
from typing import Dict, Any, List
from loguru import logger

from utils.llm_client import LLMClient
from agents.phase2_mirofish.graph.builder import GraphBuilderService
from agents.phase2_mirofish.simulation.runner import SimulationRunner

class PredictionReportAgent:
    """
    接收用户关于未来演化的提问，结合 Graph 数据与 Simulation 过程
    生成深度的 Markdown 报告。
    """
    
    def __init__(self, llm: LLMClient, graph_builder: GraphBuilderService, sim_runner: SimulationRunner):
        self._llm = llm
        self._graph = graph_builder
        self._sim = sim_runner

    async def generate_report(self, simulation_id: str, graph_id: str, query: str) -> str:
        """
        生成 Markdown 格式预测报告
        """
        logger.info(f"PredictionReportAgent: 正在为仿真 {simulation_id} (图谱 {graph_id}) 处理提问: {query}")
        
        # 1. 查询基础网络结构 (旁路或调用 Zep)
        # 例如查询核心实体、影响链条
        graph_data = await self._graph.get_data(graph_id)
        
        # 2. 查询仿真过程记录状态 (从 Runner 获取状态和可能保存的事件流水)
        state = self._sim.get_state(simulation_id)
        
        # 构建整合的分析上下文 (这里是简化的文本构造)
        context = ""
        context += "=== 知识图谱记忆网络 ===\n"
        if "nodes" in graph_data and graph_data["nodes"]:
            context += f"当前记忆包含 {graph_data.get('node_count', 0)} 个节点，{graph_data.get('edge_count', 0)} 条逻辑关联边。\n"
        else:
            context += "图谱系统暂时缺电(Bypass/BypassMock)，仅维持拓扑结构的逻辑认知。\n"
            
        context += "\n=== 仿真推演状态 ===\n"
        if state:
            context += f"平台模式: {state.platform}\n"
            context += f"运行轮次: {state.current_round} / {state.max_rounds}\n"
            context += f"交互行为频次: {state.actions_count}\n"
            context += f"当前终态: {state.status_msg}\n"
        else:
            context += "仿真系统记录未命中或未启动。\n"
            
        # 3. 交由 LLM 生成正式预测报告
        prompt = f"""
你是一个未来学与社会网络推演专家系统（MiroFish Prediction Engine）。
你现在持有一个正在进行或已完成的【仿真推演引擎状态】，以及一个代表该话题深层逻辑的【隐匿知识图谱脉络】。

用户提问/推演方向：
"{query}"

客观数据与状态参考：
{context}

请撰写一份结构严谨、具备预见性的分析报告。报告须涵盖：
1. **现状推演剖面**：基于现有推演状态及网络结构，指出主要矛盾或阻点。
2. **多节点演化预测**：设想在双平台（如果适用）中的裂变情况（预测高低潮，节点转移）。
3. **干预建议(Policy Options)**：列出3条可行的应对策略。

要求：
- 使用 Markdown 语法，层次分明，适当使用列表、加粗、区块引用。
- 语气客观专业（以国家智库或者资深分析师视角写作）。
- 篇幅不低于 500 字。
"""

        try:
            import httpx
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self._llm.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._llm.api_key}"},
                    json={
                        "model": self._llm.model,
                        "messages": [
                            {"role": "system", "content": "You are a professional social simulation analyst."},
                            {"role": "user", "content": prompt}
                        ],
                        "temperature": 0.4,
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
                
        except Exception as e:
            logger.error(f"PredictionReportAgent: 报告生成失败 - {e}")
            return f"推演分析生成受到外部网络因素影响，暂时未能完成。\n\n异常反馈：{e}"

    async def chat_with_agent(self, simulation_id: str, agent_id: str, message: str) -> str:
        """与 OASIS 仿真环境中特定的 Agent/Persona 沟通 (未来拓展接口)"""
        return "Not implemented directly. Requires active hook into OASIS environment step loop."
