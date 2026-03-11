import asyncio
import logging
import os
import shutil
import sys
import os

# 确保 backend 目录在 sys.path 中
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path
from agents.runner.agent_runner import AgentRunner
from agents.tools.memory import MemorySearchTool, MemoryGetTool
import agents.file_processor # Needed for ToolContext Pydantic validation

logging.basicConfig(level=logging.INFO)

async def main():
    # Setup test workspace
    test_dir = Path("./test_workspace_memory")
    test_dir.mkdir(exist_ok=True)
    
    with open(test_dir / "MEMORY.md", "w", encoding="utf-8") as f:
        f.write("# Agent Memory\\n\\nThe project name is Project Alpha.\\nWe use FastAPI for the backend.\\nImportant contact: Bob at bob@example.com.")
    
    memory_sub_dir = test_dir / "memory"
    memory_sub_dir.mkdir(exist_ok=True)
    with open(memory_sub_dir / "database.md", "w", encoding="utf-8") as f:
        f.write("# Database Architecture\\n\\nWe decided to use PostgreSQL instead of MySQL because of JSONB support.\\nThe migration will happen next month.")

    from utils.llm_client import get_llm_client
    from agents.context_engine import create_agent_context

    llm = get_llm_client()
    ctx_engine = create_agent_context(session_id="test_memory_session")

    # Initialize runner with memory tools
    runner = AgentRunner(
        llm=llm,
        context_engine=ctx_engine,
        tools=[MemorySearchTool(), MemoryGetTool()],
        max_iterations=5
    )

    try:
        # User prompt that triggers memory search
        user_prompt = "What database are we using and why? Also, who is the contact person for the project?"
        print(f"User: {user_prompt}")
        
        async def stream_handler(event):
            e_type = event["type"]
            if e_type == "thinking":
                print(f"🤔 Thinking: {event['content'][:100]}...\\n")
            elif e_type == "tool_use":
                print(f"🛠️ Tool Use: {event['name']}({event['args']})")
            elif e_type == "tool_result":
                content = event['content']
                print(f"✅ Tool Result: {content[:300]}...\\n")
            elif e_type == "message":
                print(f"\\n🤖 Final Message: {event['content']}")

        response = await runner.run(
            user_prompt, 
            stream_cb=stream_handler, 
            tool_context={"directory": str(test_dir.resolve())}
        )
                
        print("\\n\\n[Test Completed]")
    finally:
        # Cleanup
        if test_dir.exists():
            shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(main())
