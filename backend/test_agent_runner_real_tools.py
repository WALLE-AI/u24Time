import asyncio
import logging
import sys
import os

# 确保 backend 目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.llm_client import get_llm_client
from agents.context_engine import create_agent_context
from agents.runner.agent_runner import AgentRunner
from agents.tools.web_search import WebSearchTool
from agents.tools.web_fetch import WebFetchTool
# Import file_processor to trigger rebuild_tool_context_model() and resolve ProcessedFile
import agents.file_processor

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # 1. 准备组件
    llm = get_llm_client()
    ctx_engine = create_agent_context(session_id="test_real_tools_session")
    
    # 实例化真实工具
    tools = [WebSearchTool(), WebFetchTool()]
    
    runner = AgentRunner(llm=llm, context_engine=ctx_engine, tools=tools, max_iterations=5)
    
    # 2. 回调函数用于显示流
    async def stream_handler(event):
        e_type = event["type"]
        if e_type == "thinking":
            # 简单打印 agent thinking 的截断前缀，避免太长
            print(f"🤔 Thinking: {event['content'][:100]}...\n")
        elif e_type == "tool_use":
            print(f"🛠️ Tool Use: {event['name']}({event['args']})")
        elif e_type == "tool_result":
            # 工具结果可能非常长，截断打印
            content = event['content']
            print(f"✅ Tool Result: {content[:150]}...\n")
        elif e_type == "message":
            print(f"🤖 Final Message: {event['content']}")

    # 3. 运行推演 —— 询问一个需要搜索的问题
    prompt = "What are the latest news about SpaceX Starship?"
    print(f"User: {prompt}\n")
    print("=" * 40)
    
    try:
        response = await runner.run(prompt, stream_cb=stream_handler)
        print("=" * 40)
        print(f"Runner Response: {response}")
    except Exception as e:
        logger.error(f"Execution failed: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())
