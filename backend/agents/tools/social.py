from typing import Any, Type, Optional, List, Dict, Union
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


# ----------------------------------------------------------------------------
# Discord Tool
# ----------------------------------------------------------------------------

class DiscordToolParams(BaseModel):
    action: str = Field(description="react|reactions|sticker|poll|permissions|fetchMessage|readMessages|sendMessage|editMessage|deleteMessage|threadCreate|threadList|threadReply|pinMessage|unpinMessage|listPins|searchMessages|memberInfo|roleInfo|emojiList|emojiUpload|stickerUpload|roleAdd|roleRemove|channelInfo|channelList|voiceStatus|eventList|eventCreate|channelCreate|channelEdit|channelDelete|channelMove|categoryCreate|categoryEdit|categoryDelete|channelPermissionSet|channelPermissionRemove|timeout|kick|ban|setPresence")
    accountId: Optional[str] = None
    # Action specific parameters (simplified for Phase 1)
    to: Optional[str] = None
    content: Optional[str] = None
    messageId: Optional[str] = None
    channelId: Optional[str] = None
    guildId: Optional[str] = None
    userId: Optional[str] = None
    emoji: Optional[str] = None
    # ... Many more possible params from deep in discord-actions-*.ts


class DiscordTool(Tool):
    @property
    def id(self) -> str:
        return "discord"

    @property
    def description(self) -> str:
        return "Perform various actions on Discord (messaging, guild management, moderation, presence)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return DiscordToolParams

    async def execute(self, args: DiscordToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Slack Tool
# ----------------------------------------------------------------------------

class SlackToolParams(BaseModel):
    action: str = Field(description="sendMessage|editMessage|deleteMessage|readMessages|downloadFile|react|reactions|pinMessage|unpinMessage|listPins|memberInfo|emojiList")
    accountId: Optional[str] = None
    channelId: Optional[str] = None
    messageId: Optional[str] = None
    to: Optional[str] = None
    content: Optional[str] = None
    userId: Optional[str] = None
    limit: Optional[int] = None
    before: Optional[str] = None
    after: Optional[str] = None
    threadId: Optional[str] = None
    fileId: Optional[str] = None


class SlackTool(Tool):
    @property
    def id(self) -> str:
        return "slack"

    @property
    def description(self) -> str:
        return "Perform various actions on Slack (messaging, reactions, pins, member info)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return SlackToolParams

    async def execute(self, args: SlackToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Telegram Tool
# ----------------------------------------------------------------------------

class TelegramToolParams(BaseModel):
    action: str = Field(description="react|sendMessage|poll|deleteMessage|editMessage|sendSticker|searchSticker|stickerCacheStats|createForumTopic")
    accountId: Optional[str] = None
    chatId: Optional[Union[str, int]] = None
    to: Optional[str] = None
    messageId: Optional[int] = None
    content: Optional[str] = None
    question: Optional[str] = None
    answers: Optional[List[str]] = None
    # ... Many more


class TelegramTool(Tool):
    @property
    def id(self) -> str:
        return "telegram"

    @property
    def description(self) -> str:
        return "Perform various actions on Telegram (messaging, stickers, polls, forum topics)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return TelegramToolParams

    async def execute(self, args: TelegramToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# WhatsApp Tool
# ----------------------------------------------------------------------------

class WhatsAppToolParams(BaseModel):
    action: str = Field(description="react")
    accountId: Optional[str] = None
    chatJid: Optional[str] = None
    messageId: Optional[str] = None
    emoji: Optional[str] = None


class WhatsAppTool(Tool):
    @property
    def id(self) -> str:
        return "whatsapp"

    @property
    def description(self) -> str:
        return "Perform actions on WhatsApp (currently supports reactions)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return WhatsAppToolParams

    async def execute(self, args: WhatsAppToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")


# ----------------------------------------------------------------------------
# Feishu Tool
# ----------------------------------------------------------------------------

class FeishuToolParams(BaseModel):
    action: str = Field(description="members|info|bitable_get_meta|bitable_list_fields|bitable_list_records|bitable_get_record|bitable_create_record|bitable_update_record|bitable_create_app|bitable_create_field|doc_read|doc_create|doc_append|doc_clear|doc_image_upload|doc_file_upload|wiki_get_node|wiki_list_nodes")
    accountId: Optional[str] = None
    chat_id: Optional[str] = None
    app_token: Optional[str] = None
    table_id: Optional[str] = None
    record_id: Optional[str] = None
    document_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    content: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None
    # ... many more possible params


class FeishuTool(Tool):
    @property
    def id(self) -> str:
        return "feishu"

    @property
    def description(self) -> str:
        return "Perform various actions on Feishu (messaging, bitable, docx, wiki)."

    @property
    def parameters(self) -> Type[BaseModel]:
        return FeishuToolParams

    async def execute(self, args: FeishuToolParams, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError("Phase 1: Tool definitions only")
