from typing import Any, Type, Optional, List, Dict, Union
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


# ----------------------------------------------------------------------------
# Canvas Tool
# ----------------------------------------------------------------------------

class CanvasToolParams(BaseModel):
    action: str = Field(description="present|hide|navigate|eval|snapshot|a2ui_push|a2ui_reset")
    gatewayUrl: Optional[str] = None
    gatewayToken: Optional[str] = None
    timeoutMs: Optional[int] = None
    node: Optional[str] = None
    # present
    target: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    # navigate / present (alias)
    url: Optional[str] = None
    # eval
    javaScript: Optional[str] = None
    # snapshot
    outputFormat: Optional[str] = Field(None, description="png|jpg|jpeg")
    maxWidth: Optional[int] = None
    quality: Optional[float] = None
    delayMs: Optional[int] = None
    # a2ui_push
    jsonl: Optional[str] = None
    jsonlPath: Optional[str] = None


class CanvasTool(Tool):
    @property
    def id(self) -> str:
        return "canvas"

    @property
    def description(self) -> str:
        return "Control node canvases (present/hide/navigate/eval/snapshot/A2UI)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return CanvasToolParams

    async def execute(self, args: CanvasToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Cron Tool
# ----------------------------------------------------------------------------

class CronToolParams(BaseModel):
    action: str = Field(description="status|list|add|update|remove|run|runs|wake")
    gatewayUrl: Optional[str] = None
    gatewayToken: Optional[str] = None
    timeoutMs: Optional[int] = None
    includeDisabled: Optional[bool] = None
    job: Optional[Dict[str, Any]] = None
    jobId: Optional[str] = None
    id: Optional[str] = None
    patch: Optional[Dict[str, Any]] = None
    text: Optional[str] = None
    mode: Optional[str] = Field(None, description="now|next-heartbeat")
    runMode: Optional[str] = Field(None, description="due|force")
    contextMessages: Optional[int] = Field(None, ge=0, le=10)


class CronTool(Tool):
    @property
    def id(self) -> str:
        return "cron"

    @property
    def description(self) -> str:
        return "Manage Gateway cron jobs and send wake events."

    @property
    def parameters(self) -> Type[BaseModel]:
        return CronToolParams

    async def execute(self, args: CronToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Gateway Tool
# ----------------------------------------------------------------------------

class GatewayToolParams(BaseModel):
    action: str = Field(description="restart|config.get|config.schema.lookup|config.apply|config.patch|update.run")
    delayMs: Optional[int] = None
    reason: Optional[str] = None
    gatewayUrl: Optional[str] = None
    gatewayToken: Optional[str] = None
    timeoutMs: Optional[int] = None
    path: Optional[str] = None
    raw: Optional[str] = None
    baseHash: Optional[str] = None
    sessionKey: Optional[str] = None
    note: Optional[str] = None
    restartDelayMs: Optional[int] = None


class GatewayTool(Tool):
    @property
    def id(self) -> str:
        return "gateway"

    @property
    def description(self) -> str:
        return "Restart, inspect config, apply config, or update the gateway in-place."

    @property
    def parameters(self) -> Type[BaseModel]:
        return GatewayToolParams

    async def execute(self, args: GatewayToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Nodes Tool
# ----------------------------------------------------------------------------

class NodesToolParams(BaseModel):
    action: str = Field(description="status|describe|pending|approve|reject|notify|camera_snap|camera_list|camera_clip|photos_latest|screen_record|location_get|notifications_list|notifications_action|device_status|device_info|device_permissions|device_health|run|invoke")
    gatewayUrl: Optional[str] = None
    gatewayToken: Optional[str] = None
    timeoutMs: Optional[int] = None
    node: Optional[str] = None
    requestId: Optional[str] = None
    # notify
    title: Optional[str] = None
    body: Optional[str] = None
    sound: Optional[str] = None
    priority: Optional[str] = Field(None, description="passive|active|timeSensitive")
    delivery: Optional[str] = Field(None, description="system|overlay|auto")
    # camera_snap / camera_clip
    facing: Optional[str] = Field(None, description="front|back|both")
    maxWidth: Optional[int] = None
    quality: Optional[float] = None
    delayMs: Optional[int] = None
    deviceId: Optional[str] = None
    limit: Optional[int] = None
    duration: Optional[str] = None
    durationMs: Optional[int] = Field(None, le=300000)
    includeAudio: Optional[bool] = None
    # screen_record
    fps: Optional[int] = None
    screenIndex: Optional[int] = None
    outPath: Optional[str] = None
    # location_get
    maxAgeMs: Optional[int] = None
    locationTimeoutMs: Optional[int] = None
    desiredAccuracy: Optional[str] = Field(None, description="coarse|balanced|precise")
    # notifications_action
    notificationAction: Optional[str] = Field(None, description="open|dismiss|reply")
    notificationKey: Optional[str] = None
    notificationReplyText: Optional[str] = None
    # run
    command: Optional[List[str]] = None
    cwd: Optional[str] = None
    env: Optional[List[str]] = None
    commandTimeoutMs: Optional[int] = None
    invokeTimeoutMs: Optional[int] = None
    needsScreenRecording: Optional[bool] = None
    # invoke
    invokeCommand: Optional[str] = None
    invokeParamsJson: Optional[str] = None


class NodesTool(Tool):
    @property
    def id(self) -> str:
        return "nodes"

    @property
    def description(self) -> str:
        return "Discover and control paired nodes."

    @property
    def parameters(self) -> Type[BaseModel]:
        return NodesToolParams

    async def execute(self, args: NodesToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# File System Tools
# ----------------------------------------------------------------------------
import os
import json

class ReadFileToolParams(BaseModel):
    path: str = Field(description="Path to the file to read")

class ReadFileTool(Tool):
    @property
    def id(self) -> str:
        return "fs_read"
    @property
    def description(self) -> str:
        return "Read the contents of a file."
    @property
    def parameters(self) -> Type[BaseModel]:
        return ReadFileToolParams
    async def execute(self, args: ReadFileToolParams, ctx: ToolContext) -> ToolResult:
        base_dir = ctx.directory or os.getcwd()
        target = os.path.abspath(os.path.join(base_dir, args.path))
        if not target.startswith(os.path.abspath(base_dir)):
            return ToolResult(output=json.dumps({"error": "Access denied"}), success=False, error="Security violation")
        try:
            with open(target, 'r', encoding='utf-8') as f:
                content = f.read()
            return ToolResult(output=content, success=True)
        except Exception as e:
            return ToolResult(output=str(e), success=False, error=str(e))


class WriteFileToolParams(BaseModel):
    path: str = Field(description="Path to the file to write")
    content: str = Field(description="Content to write to the file")

class WriteFileTool(Tool):
    @property
    def id(self) -> str:
        return "fs_write"
    @property
    def description(self) -> str:
        return "Write content to a file."
    @property
    def parameters(self) -> Type[BaseModel]:
        return WriteFileToolParams
    async def execute(self, args: WriteFileToolParams, ctx: ToolContext) -> ToolResult:
        base_dir = ctx.directory or os.getcwd()
        target = os.path.abspath(os.path.join(base_dir, args.path))
        if not target.startswith(os.path.abspath(base_dir)):
            return ToolResult(output=json.dumps({"error": "Access denied"}), success=False, error="Security violation")
        try:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, 'w', encoding='utf-8') as f:
                f.write(args.content)
            return ToolResult(output=json.dumps({"status": "success", "path": args.path}), success=True)
        except Exception as e:
            return ToolResult(output=str(e), success=False, error=str(e))


class ListDirToolParams(BaseModel):
    path: str = Field(default=".", description="Directory path to list")

class ListDirTool(Tool):
    @property
    def id(self) -> str:
        return "list_dir"
    @property
    def description(self) -> str:
        return "List contents of a directory."
    @property
    def parameters(self) -> Type[BaseModel]:
        return ListDirToolParams
    async def execute(self, args: ListDirToolParams, ctx: ToolContext) -> ToolResult:
        base_dir = ctx.directory or os.getcwd()
        target = os.path.abspath(os.path.join(base_dir, args.path))
        if not target.startswith(os.path.abspath(base_dir)):
            return ToolResult(output=json.dumps({"error": "Access denied"}), success=False, error="Security violation")
        try:
            items = os.listdir(target)
            return ToolResult(output=json.dumps({"items": items}), success=True)
        except Exception as e:
            return ToolResult(output=str(e), success=False, error=str(e))


class SearchFileToolParams(BaseModel):
    query: str = Field(description="String to search for in files")
    path: str = Field(".", description="Directory to search in")

class SearchFileTool(Tool):
    @property
    def id(self) -> str:
        return "file_search"
    @property
    def description(self) -> str:
        return "Search for a string pattern in files within a directory."
    @property
    def parameters(self) -> Type[BaseModel]:
        return SearchFileToolParams
    async def execute(self, args: SearchFileToolParams, ctx: ToolContext) -> ToolResult:
        base_dir = ctx.directory or os.getcwd()
        target_dir = os.path.abspath(os.path.join(base_dir, args.path))
        if not target_dir.startswith(os.path.abspath(base_dir)):
            return ToolResult(output=json.dumps({"error": "Access denied"}), success=False, error="Security violation")
        
        results = []
        try:
            for root, _, files in os.walk(target_dir):
                for f in files:
                    full_path = os.path.join(root, f)
                    try:
                        with open(full_path, "r", encoding="utf-8") as file:
                            for idx, line in enumerate(file):
                                if args.query in line:
                                    rel_path = os.path.relpath(full_path, base_dir)
                                    results.append({"file": rel_path, "line": idx+1, "content": line.strip()})
                    except:
                        pass
            return ToolResult(output=json.dumps({"results": results}), success=True)
        except Exception as e:
            return ToolResult(output=str(e), success=False, error=str(e))
