from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


def optional_string_enum(*args):
    """Placeholder for description representing enums"""
    return " | ".join(args)

# ----------------------------------------------------------------------------
# Message Tool
# ----------------------------------------------------------------------------

class ChannelTargetParams(BaseModel):
    channelId: Optional[str] = None
    channelIds: Optional[List[str]] = None
    guildId: Optional[str] = None
    userId: Optional[str] = None
    authorId: Optional[str] = None
    authorIds: Optional[List[str]] = None
    roleId: Optional[str] = None
    roleIds: Optional[List[str]] = None
    participant: Optional[str] = None

class MessageToolParams(BaseModel):
    action: str = Field(description="Action to perform: send, reply, thread-reply, broadcast, react, delete, poll, pin, unpin, edit, fetch, etc.")
    
    # Routing
    channel: Optional[str] = None
    target: Optional[ChannelTargetParams] = None
    targets: Optional[List[ChannelTargetParams]] = None
    accountId: Optional[str] = None
    dryRun: Optional[bool] = None
    
    # Send
    message: Optional[str] = None
    effectId: Optional[str] = None
    effect: Optional[str] = None
    media: Optional[str] = None
    filename: Optional[str] = None
    buffer: Optional[str] = None
    contentType: Optional[str] = None
    mimeType: Optional[str] = None
    caption: Optional[str] = None
    path: Optional[str] = None
    filePath: Optional[str] = None
    replyTo: Optional[str] = None
    threadId: Optional[str] = None
    asVoice: Optional[bool] = None
    silent: Optional[bool] = None
    quoteText: Optional[str] = None
    bestEffort: Optional[bool] = None
    gifPlayback: Optional[bool] = None
    buttons: Optional[List[List[Dict[str, Any]]]] = None
    card: Optional[Dict[str, Any]] = None
    components: Optional[Dict[str, Any]] = None
    
    # Reactions
    messageId: Optional[str] = None
    message_id: Optional[str] = None
    emoji: Optional[str] = None
    remove: Optional[bool] = None
    targetAuthor: Optional[str] = None
    targetAuthorUuid: Optional[str] = None
    groupId: Optional[str] = None
    
    # Fetch
    limit: Optional[int] = None
    before: Optional[str] = None
    after: Optional[str] = None
    around: Optional[str] = None
    fromMe: Optional[bool] = None
    includeArchived: Optional[bool] = None
    
    # Poll
    pollId: Optional[str] = None
    pollOptionId: Optional[str] = None
    pollOptionIds: Optional[List[str]] = None
    pollOptionIndex: Optional[int] = None
    pollOptionIndexes: Optional[List[int]] = None
    
    # Target Filters
    channelId: Optional[str] = None
    channelIds: Optional[List[str]] = None
    guildId: Optional[str] = None
    userId: Optional[str] = None
    authorId: Optional[str] = None
    authorIds: Optional[List[str]] = None
    roleId: Optional[str] = None
    roleIds: Optional[List[str]] = None
    participant: Optional[str] = None
    
    # Sticker
    emojiName: Optional[str] = None
    stickerId: Optional[List[str]] = None
    stickerName: Optional[str] = None
    stickerDesc: Optional[str] = None
    stickerTags: Optional[str] = None
    
    # Thread
    threadName: Optional[str] = None
    autoArchiveMin: Optional[int] = None
    appliedTags: Optional[List[str]] = None
    
    # Event
    query: Optional[str] = None
    eventName: Optional[str] = None
    eventType: Optional[str] = None
    startTime: Optional[str] = None
    endTime: Optional[str] = None
    desc: Optional[str] = None
    location: Optional[str] = None
    durationMin: Optional[int] = None
    until: Optional[str] = None
    
    # Moderation
    reason: Optional[str] = None
    deleteDays: Optional[int] = None
    
    # Gateway
    gatewayUrl: Optional[str] = None
    gatewayToken: Optional[str] = None
    timeoutMs: Optional[int] = None
    
    # Channel Management
    name: Optional[str] = None
    type: Optional[int] = None
    parentId: Optional[str] = None
    topic: Optional[str] = None
    position: Optional[int] = None
    nsfw: Optional[bool] = None
    rateLimitPerUser: Optional[int] = None
    categoryId: Optional[str] = None
    clearParent: Optional[bool] = None
    
    # Presence
    activityType: Optional[str] = None
    activityName: Optional[str] = None
    activityUrl: Optional[str] = None
    activityState: Optional[str] = None
    status: Optional[str] = None


class MessageTool(Tool):
    @property
    def id(self) -> str:
        return "message"

    @property
    def description(self) -> str:
        return "Send, delete, and manage messages via channel plugins."

    @property
    def parameters(self) -> Type[BaseModel]:
        return MessageToolParams

    async def execute(self, args: MessageToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# TTS Tool
# ----------------------------------------------------------------------------

class TtsToolParams(BaseModel):
    text: str = Field(description="Text to convert to speech.")
    channel: Optional[str] = Field(None, description="Optional channel id to pick output format")


class TtsTool(Tool):
    @property
    def id(self) -> str:
        return "tts"

    @property
    def description(self) -> str:
        return "Convert text to speech. Audio is delivered automatically from the tool result."

    @property
    def parameters(self) -> Type[BaseModel]:
        return TtsToolParams

    async def execute(self, args: TtsToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
