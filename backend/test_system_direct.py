import asyncio
from agents.tools.base import ToolContext
from agents.tools.system import ReadFileTool, ReadFileToolParams, WriteFileTool, WriteFileToolParams, ListDirTool, ListDirToolParams, SearchFileTool, SearchFileToolParams
import agents.file_processor # Needs to trigger ToolContext rebuild
import os
import shutil
from pathlib import Path

async def main():
    test_dir = Path("./test_workspace_system")
    test_dir.mkdir(exist_ok=True)
    
    ctx = ToolContext(
        session_id="test_session",
        message_id="msg_1",
        agent="test_agent",
        user_id="test_user",
        directory=str(test_dir.resolve())
    )
    
    try:
        print("=== Testing WriteFileTool ===")
        write_tool = WriteFileTool()
        args_w = WriteFileToolParams(path="test_file.txt", content="Hello FS Tools!\\nLine 2 is here.")
        res_w = await write_tool.execute(args_w, ctx)
        print("Write Result:", res_w.output)
        
        print("\\n=== Testing ReadFileTool ===")
        read_tool = ReadFileTool()
        args_r = ReadFileToolParams(path="test_file.txt")
        res_r = await read_tool.execute(args_r, ctx)
        print("Read Result:", res_r.output)
        
        print("\\n=== Testing ListDirTool ===")
        list_tool = ListDirTool()
        args_l = ListDirToolParams(path=".")
        res_l = await list_tool.execute(args_l, ctx)
        print("List Result:", res_l.output)
        
        print("\\n=== Testing SearchFileTool ===")
        search_tool = SearchFileTool()
        args_s = SearchFileToolParams(query="FS Tools", path=".")
        res_s = await search_tool.execute(args_s, ctx)
        print("Search Result:", res_s.output)
        
        print("\\n=== Testing Security (Out of Bounds) ===")
        args_sec = ReadFileToolParams(path="../system.py")
        res_sec = await read_tool.execute(args_sec, ctx)
        print("Security Result:", res_sec.output)
        
    finally:
        shutil.rmtree(test_dir)

if __name__ == "__main__":
    asyncio.run(main())
