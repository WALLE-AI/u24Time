import asyncio
import logging
import sys
import os

# 确保 backend 目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.llm_client import get_llm_client
from agents.context_engine import create_agent_context
from agents.runner.agent_runner import AgentRunner
from agents.tools.base import Tool, ToolResult
from pydantic import Field, BaseModel

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 定义一个测试工具
class MockWeatherParams(BaseModel):
    city: str = Field(..., description="The city to get weather for")

class MockWeatherTool(Tool):
    id = "get_weather"
    description = "Get the current weather for a city"
    parameters = MockWeatherParams

    async def execute(self, args, ctx):
        city = args.get("city")
        logger.info(f"Tool Executed: get_weather for {city}")
        return ToolResult(
            success=True,
            output=f"The weather in {city} is sunny, 25°C."
        )

async def main():
    # 1. 准备组件
    llm = get_llm_client()
    ctx_engine = create_agent_context(session_id="test_react_session")
    tools = [MockWeatherTool()]
    
    runner = AgentRunner(llm=llm, context_engine=ctx_engine, tools=tools)
    
    # 2. 回调函数用于显示流
    async def stream_handler(event):
        e_type = event["type"]
        if e_type == "thinking":
            print(f"🤔 Thinking: {event['content']}\n")
        elif e_type == "tool_use":
            print(f"🛠️ Tool Use: {event['name']}({event['args']})")
        elif e_type == "tool_result":
            print(f"✅ Tool Result: {event['content']}\n")
        elif e_type == "message":
            print(f"🤖 Final Message: {event['content']}")

    # 3. 运行推演
    prompt = "What is the weather in Tokyo?"
    print(f"User: {prompt}\n")
    
    response = await runner.run(prompt, stream_cb=stream_handler)
    
    print("-" * 20)
    print(f"Runner Response: {response}")

if __name__ == "__main__":
    asyncio.run(main())
