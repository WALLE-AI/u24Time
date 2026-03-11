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

# 导入以触发 Pydantic model rebuild 机制
import agents.file_processor

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    # 1. 准备组件
    llm = get_llm_client()
    ctx_engine = create_agent_context(session_id="test_real_tools_session")
    
    # 实例化需要测试的真实工具
    web_search = WebSearchTool()
    tools = [web_search]
    
    runner = AgentRunner(llm=llm, context_engine=ctx_engine, tools=tools)
    
    # 2. 回调函数用于显示流
    async def stream_handler(event):
        e_type = event["type"]
        if e_type == "thinking":
            print(f"🤔 Thinking: {event['content']}\n")
        elif e_type == "tool_use":
            print(f"🛠️ Tool Use: {event['name']}({event['args']})")
        elif e_type == "tool_result":
            content = event['content']
            if len(content) > 500:
                print(f"✅ Tool Result: {content[:500]} ... [截断，共 {len(content)} 字符]\n")
            else:
                print(f"✅ Tool Result: {content}\n")
        elif e_type == "message":
            print(f"🤖 Final Message: {event['content']}\n")

    # 3. 运行推演
    prompt = "查一下最近关于 DeepSeek 的最新消息，用中文总结一下不超过100字"
    print(f"User: {prompt}\n")
    print("=" * 40)
    
    response = await runner.run(prompt, stream_cb=stream_handler)
    
    print("=" * 40)
    print(f"Runner Response:\n{response}")

if __name__ == "__main__":
    asyncio.run(main())
