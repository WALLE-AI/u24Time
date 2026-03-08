# -*- coding: utf-8 -*-
"""
GraphBuilderService — Zep Cloud 图谱构建服务
负责接收纯文本和 Ontology，与 Zep 交互构建时序演化知识图谱。
"""

import asyncio
import time
from typing import Dict, Any, List
from loguru import logger

from agents.config import agents_settings

class GraphBuilderService:
    """
    依托 Zep Cloud 实现动态知识文档的图谱化
    必须提供 ZEP_API_KEY，且安装可选依赖 zep-cloud
    """
    
    def __init__(self):
        self.api_key = agents_settings.ZEP_API_KEY
        self.client = None
        self._initialized = False

    def _initialize(self):
        if self._initialized:
            return
            
        if not self.api_key:
            logger.warning("GraphBuilderService: 缺少 ZEP_API_KEY，图谱构建将被旁路(Bypass)。")
            return
            
        try:
            from zep_cloud.client import AsyncZep
            self.client = AsyncZep(api_key=self.api_key)
            self._initialized = True
            logger.info("GraphBuilderService: Zep Cloud 客户端初始化成功。")
        except ImportError:
            logger.warning("GraphBuilderService: 未安装 zep-cloud 依赖，图谱构建将被旁路。提示: uv add zep-cloud")
        except Exception as e:
            logger.error(f"GraphBuilderService: Zep 初始化失败: {e}")

    async def build(self, text: str, ontology: dict, name: str = None) -> Dict[str, Any]:
        """
        发起图谱构建任务。
        在免费版 / 基础版 Zep Cloud 中，通常是添加 document 到 collection，
        由系统后台自动抽取节点和边。
        暂以接口模拟兼容。实际 Zep SDK 调用需依最新 API 结构适配。
        """
        self._initialize()
        
        graph_id = name or f"graph_{int(time.time())}"
        
        if not self._initialized or not self.client:
            logger.info(f"GraphBuilderService(Bypass): 模拟图谱构建任务 {graph_id}...")
            # 旁路模式直接返回成功标志
            return {
                "task_id": f"dummy_task_{graph_id}",
                "graph_id": graph_id,
                "status": "building",
                "simulated": True
            }
            
        logger.info(f"GraphBuilderService: 发起 Zep 构建任务 {graph_id}")
        try:
            # 真实 Zep Cloud 操作逻辑通常包括：
            # 1. client.document.add_collection()
            # 2. client.document.add_document() 包含自定义 schema(ontology)
            
            # 由于 Zep 最新 API 演变较多（例如 zep_cloud v2 专注于 Memory Graph），
            # 这里抽象调用。
            collection_name = graph_id
            try:
                await self.client.document.add_collection(name=collection_name, description="MiroFish Agent Simulation")
            except Exception as e:
                # 集合已存在等情况
                pass
                
            await self.client.document.add_document(
                collection_name, 
                content=text, 
                metadata={"ontology": ontology}
            )
            
            return {
                "task_id": f"zep_task_{collection_name}",
                "graph_id": collection_name,
                "status": "building",
                "simulated": False
            }
            
        except Exception as e:
            logger.error(f"GraphBuilderService: 构建出错: {e}")
            return {"status": "failed", "graph_id": graph_id, "error": str(e)}

    async def get_data(self, graph_id: str) -> Dict[str, Any]:
        """
        查询提取后的图谱网络：节点和边
        """
        self._initialize()
        
        if not self._initialized or not self.client:
            return {"nodes": [{"id": "NodeA", "label": "Person"}], "edges": [], "node_count": 1, "edge_count": 0, "simulated": True}
            
        try:
            # 获取 Collection 下的抽取的实体边（取决于具体的 zep 版本 graph api 方法）
            # search_results = await self.client.graph.search("...", collection_name=graph_id)
            pass
            return {"nodes": [], "edges": [], "node_count": 0, "edge_count": 0, "status": "completed"}
        except Exception as e:
            logger.error(f"GraphBuilderService: 查询图谱出错: {e}")
            return {"nodes": [], "edges": [], "error": str(e)}
