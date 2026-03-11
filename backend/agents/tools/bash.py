import asyncio
import uuid
import os
import json
import logging
from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult

logger = logging.getLogger(__name__)

# Global dictionary to track running processes
_process_registry = {}

# ----------------------------------------------------------------------------
# Exec Tool
# ----------------------------------------------------------------------------

class ExecToolParams(BaseModel):
    command: str = Field(description="Shell command to execute")
    workdir: Optional[str] = Field(None, description="Working directory (defaults to cwd)")
    env: Optional[Dict[str, str]] = Field(None, description="Environment variables")
    yieldMs: Optional[int] = Field(None, description="Milliseconds to wait before backgrounding (default 10000)")
    background: Optional[bool] = Field(None, description="Run in background immediately")
    timeout: Optional[int] = Field(None, description="Timeout in seconds (optional, kills process on expiry)")
    pty: Optional[bool] = Field(None, description="Run in a pseudo-terminal (PTY) when available (TTY-required CLIs, coding agents)")
    elevated: Optional[bool] = Field(None, description="Run on the host with elevated permissions (if allowed)")
    host: Optional[str] = Field(None, description="Exec host (sandbox|gateway|node)")
    security: Optional[str] = Field(None, description="Exec security mode (deny|allowlist|full)")
    ask: Optional[str] = Field(None, description="Exec ask mode (off|on-miss|always)")
    node: Optional[str] = Field(None, description="Node id/name for host=node")

class ExecTool(Tool):
    @property
    def id(self) -> str:
        return "exec"

    @property
    def description(self) -> str:
        return "Execute bash commands in a sandbox or host environment."

    @property
    def parameters(self) -> Type[BaseModel]:
        return ExecToolParams

    async def execute(self, args: ExecToolParams, ctx: ToolContext) -> ToolResult:
        cwd = args.workdir or ctx.directory or os.getcwd()
        command = args.command
        
        session_id = str(uuid.uuid4())[:8]
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env={**os.environ, **(args.env or {})}
        )
        
        _process_registry[session_id] = {
            "process": process,
            "stdout": b"",
            "stderr": b"",
            "command": command
        }
        
        async def _read_stream(stream, key):
            while True:
                line = await stream.read(4096)
                if not line:
                    break
                if session_id in _process_registry:
                    _process_registry[session_id][key] += line

        asyncio.create_task(_read_stream(process.stdout, "stdout"))
        asyncio.create_task(_read_stream(process.stderr, "stderr"))
        
        if args.background:
            return ToolResult(
                output=json.dumps({"sessionId": session_id, "status": "backgrounded"}),
                success=True
            )
            
        yield_ms = args.yieldMs if args.yieldMs is not None else 10000
        
        try:
            await asyncio.wait_for(process.wait(), timeout=yield_ms / 1000.0)
            status = "exited"
            code = process.returncode
        except asyncio.TimeoutError:
            status = "running"
            code = None
            
        if session_id in _process_registry:
            out = _process_registry[session_id]["stdout"].decode("utf-8", "replace")
            err = _process_registry[session_id]["stderr"].decode("utf-8", "replace")
        else:
            out, err = "", ""
            
        return ToolResult(
            output=json.dumps({
                "sessionId": session_id,
                "status": status,
                "code": code,
                "stdout": out[-4000:], # keep reasonable length
                "stderr": err[-4000:]
            }),
            success=True
        )

# ----------------------------------------------------------------------------
# Process Tool
# ----------------------------------------------------------------------------

class ProcessToolParams(BaseModel):
    action: str = Field(description="Process action (list|poll|log|write|send-keys|submit|paste|kill|clear|remove)")
    sessionId: Optional[str] = Field(None, description="Session id for actions other than list")
    data: Optional[str] = Field(None, description="Data to write for write")
    keys: Optional[List[str]] = Field(None, description="Key tokens to send for send-keys")
    hex: Optional[List[str]] = Field(None, description="Hex bytes to send for send-keys")
    literal: Optional[str] = Field(None, description="Literal string for send-keys")
    text: Optional[str] = Field(None, description="Text to paste for paste")
    bracketed: Optional[bool] = Field(None, description="Wrap paste in bracketed mode")
    eof: Optional[bool] = Field(None, description="Close stdin after write")
    offset: Optional[int] = Field(None, description="Log offset")
    limit: Optional[int] = Field(None, description="Log length")
    timeout: Optional[int] = Field(None, ge=0, description="For poll: wait up to this many milliseconds before returning")

class ProcessTool(Tool):
    @property
    def id(self) -> str:
        return "process"

    @property
    def description(self) -> str:
        return "Manage running exec sessions: list, poll, log, write, send-keys, submit, paste, kill."

    @property
    def parameters(self) -> Type[BaseModel]:
        return ProcessToolParams

    async def execute(self, args: ProcessToolParams, ctx: ToolContext) -> ToolResult:
        if args.action == "list":
            sessions = []
            for sid, pinfo in _process_registry.items():
                p = pinfo["process"]
                sessions.append({"sessionId": sid, "command": pinfo["command"], "running": p.returncode is None})
            return ToolResult(output=json.dumps({"sessions": sessions}), success=True)
            
        sid = args.sessionId
        if not sid or sid not in _process_registry:
            return ToolResult(output=json.dumps({"error": f"Session {sid} not found"}), success=False, error="Session missing")
            
        pinfo = _process_registry[sid]
        p = pinfo["process"]
        
        if args.action == "kill":
            if p.returncode is None:
                p.terminate()
            return ToolResult(output=json.dumps({"status": "killed"}), success=True)
            
        if args.action == "log":
            out = pinfo["stdout"].decode("utf-8", "replace")
            err = pinfo["stderr"].decode("utf-8", "replace")
            return ToolResult(output=json.dumps({
                "stdout": out[-4000:],
                "stderr": err[-4000:],
                "exited": p.returncode is not None,
                "code": p.returncode
            }), success=True)
            
        if args.action == "poll":
            timeout = (args.timeout or 1000) / 1000.0
            if p.returncode is None:
                try:
                    await asyncio.wait_for(p.wait(), timeout=timeout)
                except asyncio.TimeoutError:
                    pass
            out = pinfo["stdout"].decode("utf-8", "replace")
            err = pinfo["stderr"].decode("utf-8", "replace")
            return ToolResult(output=json.dumps({
                "exited": p.returncode is not None,
                "code": p.returncode,
                "stdout": out[-4000:],
                "stderr": err[-4000:]
            }), success=True)
            
        return ToolResult(output=json.dumps({"error": f"Action {args.action} partially unimplemented"}), success=False)
