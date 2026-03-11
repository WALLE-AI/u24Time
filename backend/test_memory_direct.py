import asyncio
import os
import shutil
from pathlib import Path
from agents.tools.base import ToolContext
import agents.file_processor # Triggers ToolContext model rebuild
from agents.tools.memory import MemorySearchTool, MemoryGetTool, MemorySearchToolParams, MemoryGetToolParams

async def main():
    test_dir = Path("./test_workspace_memory_direct")
    test_dir.mkdir(exist_ok=True)
    
    with open(test_dir / "MEMORY.md", "w", encoding="utf-8") as f:
        f.write("# Agent Memory\\n\\nThe project name is Project Alpha.\\nWe use FastAPI for the backend.\\nImportant contact: Bob at bob@example.com.")
    
    memory_sub_dir = test_dir / "memory"
    memory_sub_dir.mkdir(exist_ok=True)
    with open(memory_sub_dir / "database.md", "w", encoding="utf-8") as f:
        f.write("# Database Architecture\\n\\nWe decided to use PostgreSQL instead of MySQL because of JSONB support.\\nThe migration will happen next month.")

    try:
        ctx = ToolContext(
            session_id="test_session",
            message_id="msg_1",
            agent="test_agent",
            user_id="test_user",
            directory=str(test_dir.resolve())
        )
        
        print("=== Testing MemorySearchTool ===")
        search_tool = MemorySearchTool()
        args = MemorySearchToolParams(query="PostgreSQL database")
        res = await search_tool.execute(args, ctx)
        print("Result:", res.output)
        
        print("\\n=== Testing MemoryGetTool ===")
        get_tool = MemoryGetTool()
        args2 = MemoryGetToolParams(path="memory/database.md", from_=1, lines=5)
        res2 = await get_tool.execute(args2, ctx)
        print("Result:", res2.output)
    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(main())
