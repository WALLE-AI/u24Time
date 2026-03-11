import asyncio
from agents.tools.base import ToolContext
from agents.tools.bash import ExecTool, ExecToolParams, ProcessTool, ProcessToolParams
import agents.file_processor # Needs to trigger ToolContext rebuild
import os

async def main():
    ctx = ToolContext(
        session_id="test_session",
        message_id="msg_1",
        agent="test_agent",
        user_id="test_user",
        directory=os.getcwd()
    )
    
    print("=== Testing ExecTool (Foreground) ===")
    exec_tool = ExecTool()
    args_fg = ExecToolParams(command="echo 'Hello Foreground'", yieldMs=5000)
    res_fg = await exec_tool.execute(args_fg, ctx)
    print("Foreground Result:", res_fg.output)
    
    print("\\n=== Testing ExecTool (Background) ===")
    args_bg = ExecToolParams(command="sleep 2 && echo 'Hello Background'", background=True)
    res_bg = await exec_tool.execute(args_bg, ctx)
    print("Background Result:", res_bg.output)
    
    import json
    bg_data = json.loads(res_bg.output)
    session_id = bg_data.get("sessionId")
    
    print("\\n=== Testing ProcessTool (List) ===")
    proc_tool = ProcessTool()
    args_list = ProcessToolParams(action="list")
    res_list = await proc_tool.execute(args_list, ctx)
    print("List Result:", res_list.output)
    
    print("\\n=== Testing ProcessTool (Poll) ===")
    # Wait for the background process to finish sleeping
    args_poll = ProcessToolParams(action="poll", sessionId=session_id, timeout=3000)
    res_poll = await proc_tool.execute(args_poll, ctx)
    print("Poll Result:", res_poll.output)

if __name__ == "__main__":
    asyncio.run(main())
