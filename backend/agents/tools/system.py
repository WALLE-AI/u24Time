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
