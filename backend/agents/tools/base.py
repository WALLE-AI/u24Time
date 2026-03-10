"""
智能体工具基础设施

基于 opencode Tool.define 模式:
- Tool 抽象基类
- ToolContext 执行上下文
- ToolResult 返回结果

## File Access in Tools

Tools can access uploaded files through the ToolContext. When users upload files
(images, videos, audio, documents) in their messages, these files are processed
and made available to tools via ctx.files.

### Example: Accessing Uploaded Files

```python
from agents.tools.base import Tool, ToolContext, ToolResult
from pydantic import BaseModel

class MyToolParams(BaseModel):
    query: str

class MyTool(Tool):
    @property
    def id(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "Process user query with uploaded files"
    
    @property
    def parameters(self) -> type[BaseModel]:
        return MyToolParams
    
    async def execute(self, args: MyToolParams, ctx: ToolContext) -> ToolResult:
        # Get all uploaded files
        all_files = ctx.get_files()
        
        # Get only image files
        images = ctx.get_files_by_type('image/')
        
        # Get a specific file by name
        specific_file = ctx.get_file_content('screenshot.png')
        
        # Process files based on content type
        for file in all_files:
            if file.content_type == 'base64':
                # Handle base64-encoded content (images, audio, video thumbnails)
                print(f"Base64 file: {file.filename}")
            elif file.content_type == 'text':
                # Handle extracted text content (documents)
                print(f"Text content from {file.filename}: {file.content[:100]}...")
            elif file.content_type == 'error':
                # Handle processing errors
                print(f"Error processing {file.filename}: {file.content}")
        
        return ToolResult(
            output=f"Processed {len(all_files)} files",
            metadata={"file_count": len(all_files)}
        )
```

### ProcessedFile Structure

Each file in ctx.files is a ProcessedFile object with:
- mime_type: str - MIME type (e.g., 'image/png', 'application/pdf')
- filename: str - Original filename
- content_type: Literal['base64', 'text', 'error'] - How content is encoded
- content: str - File content (base64 string, extracted text, or error message)
- metadata: dict - Additional info (dimensions, size, etc.)

### File Access Methods

- `ctx.get_files()` - Returns all uploaded files
- `ctx.get_files_by_type(mime_prefix)` - Filters files by MIME type prefix
- `ctx.get_file_content(filename)` - Gets a specific file by name
"""
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar, TYPE_CHECKING
import asyncio
import time
import logging

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agents.file_processor import ProcessedFile

logger = logging.getLogger(__name__)


# ========== Forward Reference Resolution ==========
# This will be called after ProcessedFile is defined to resolve the forward reference
def rebuild_tool_context_model():
    """Rebuild ToolContext model after ProcessedFile is defined."""
    try:
        from agents.file_processor import ProcessedFile
        ToolContext.model_rebuild()
    except Exception as e:
        logger.warning(f"Failed to rebuild ToolContext model: {e}")


# ========== 工具结果 ==========

class ToolResult(BaseModel):
    """工具执行结果"""
    title: str = ""
    output: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


# ========== 执行上下文 ==========

class ToolContext(BaseModel):
    """工具执行上下文"""
    session_id: str
    message_id: str
    agent: str
    user_id: str
    
    # 工作空间目录（遵循 oh-my-opencode 的 ctx.directory 模式）
    directory: str | None = None
    
    # 数据库会话（可选）
    db: Any | None = None
    
    # ✅ Processed files from user message (Task 7.3, updated in Task 14.1)
    files: list['ProcessedFile'] = Field(default_factory=list)
    
    # 控制信号
    abort: asyncio.Event | None = None
    
    # 回调函数 (运行时注入)
    _metadata_callback: Callable[[dict], None] | None = None
    _permission_callback: Callable[[str, list[str]], bool] | None = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def update_metadata(self, metadata: dict[str, Any]) -> None:
        """实时更新元数据 (用于流式输出进度)"""
        if self._metadata_callback:
            self._metadata_callback(metadata)
    
    async def ask_permission(
        self,
        permission: str,
        patterns: list[str],
    ) -> bool:
        """
        请求权限
        
        Args:
            permission: 权限类型 (bash, edit, webfetch, etc.)
            patterns: 权限模式列表
            
        Returns:
            是否授权
        """
        if self._permission_callback:
            return self._permission_callback(permission, patterns)
        # 默认允许
        return True
    
    def is_aborted(self) -> bool:
        """检查是否已中止"""
        if self.abort:
            return self.abort.is_set()
        return False
    
    # ========== File Access Methods (Task 14.2) ==========
    
    def get_files(self) -> list['ProcessedFile']:
        """Get all uploaded files from the current message.
        
        Returns:
            List of ProcessedFile objects containing file content and metadata.
            
        Example:
            >>> files = ctx.get_files()
            >>> for file in files:
            ...     print(f"File: {file.filename}, Type: {file.mime_type}")
        """
        return self.files
    
    def get_files_by_type(self, mime_prefix: str) -> list['ProcessedFile']:
        """Filter files by MIME type prefix.
        
        Args:
            mime_prefix: MIME type prefix to filter by (e.g., 'image/', 'video/', 'application/pdf')
            
        Returns:
            List of ProcessedFile objects matching the MIME type prefix.
            
        Example:
            >>> # Get all image files
            >>> images = ctx.get_files_by_type('image/')
            >>> 
            >>> # Get all PDF documents
            >>> pdfs = ctx.get_files_by_type('application/pdf')
        """
        return [f for f in self.files if f.mime_type.startswith(mime_prefix)]
    
    def get_file_content(self, filename: str) -> 'ProcessedFile | None':
        """Get a specific file by filename.
        
        Args:
            filename: Name of the file to retrieve
            
        Returns:
            ProcessedFile object if found, None otherwise.
            
        Example:
            >>> file = ctx.get_file_content('screenshot.png')
            >>> if file and file.content_type == 'base64':
            ...     # Process base64 image content
            ...     image_data = file.content
        """
        for f in self.files:
            if f.filename == filename:
                return f
        return None


# ========== 工具基类 ==========

T = TypeVar("T", bound=BaseModel)


class Tool(ABC):
    """
    工具抽象基类
    
    每个工具需要实现:
    - id: 工具唯一标识
    - description: 工具描述 (给 LLM 看)
    - parameters: Pydantic 模型 (参数定义)
    - execute: 异步执行方法
    - metadata: 工具元数据 (可选，包含分类标签、依赖声明等)
    """
    
    @property
    @abstractmethod
    def id(self) -> str:
        """工具唯一标识"""
        ...
    
    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        ...
    
    @property
    @abstractmethod
    def parameters(self) -> type[BaseModel]:
        """参数 Pydantic 模型"""
        ...
    
    @property
    def metadata(self) -> dict[str, Any]:
        """
        工具元数据 (可选)
        
        包含:
        - categories: 分类标签列表 (如 ["web", "browser"])
        - dependencies: 依赖声明列表 (如 ["playwright", "chromium"])
        - permissions: 权限要求列表 (如 ["network", "filesystem"])
        - version: 工具版本 (如 "1.0.0")
        - author: 工具作者 (可选)
        - tags: 额外标签 (可选)
        """
        return {
            "categories": [],
            "dependencies": [],
            "permissions": [],
            "version": "1.0.0",
        }
    
    @abstractmethod
    async def execute(
        self,
        args: BaseModel,
        ctx: ToolContext,
    ) -> ToolResult:
        """
        执行工具
        
        Args:
            args: 参数 (已验证的 Pydantic 模型实例)
            ctx: 执行上下文
            
        Returns:
            ToolResult: 执行结果
        """
        ...
    
    def to_openai_function(self) -> dict[str, Any]:
        """
        转换为 OpenAI function calling 格式 (自动扁平化以提高兼容性)
        """
        schema = self.parameters.model_json_schema()
        
        # 提取 $defs
        defs = schema.get("$defs", {})
        
        def _resolve_refs(obj: Any) -> Any:
            """递归解析 $ref 引用"""
            if isinstance(obj, dict):
                if "$ref" in obj:
                    ref_path = obj["$ref"]
                    # 仅支持简单的 $defs 引用，如 #/$defs/MyModel
                    if ref_path.startswith("#/$defs/"):
                        ref_name = ref_path.split("/")[-1]
                        if ref_name in defs:
                            # 递归解析引用的内容 (防止嵌套引用)
                            return _resolve_refs(defs[ref_name].copy())
                
                # 递归处理所有字段
                return {k: _resolve_refs(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_resolve_refs(item) for item in obj]
            return obj

        # 移除不需要的字段，提取 properties 和 required
        properties = _resolve_refs(schema.get("properties", {}))
        required = schema.get("required", [])
        
        parameters = {
            "type": "object",
            "properties": properties,
            "required": required,
        }
            
        return {
            "type": "function",
            "function": {
                "name": self.id,
                "description": self.description,
                "parameters": parameters,
            },
        }
    
    async def run(
        self,
        args_dict: dict[str, Any],
        ctx: ToolContext,
    ) -> ToolResult:
        """
        运行工具 (带参数验证和日志记录)
        
        Args:
            args_dict: 参数字典
            ctx: 执行上下文
            
        Returns:
            ToolResult: 执行结果
        """
        # 1. 尝试直接验证
        try:
            args = self.parameters.model_validate(args_dict)
        except Exception as e:
            # 2. 尝试纠正参数并重新验证 (处理 LLM 幻觉和格式错误)
            new_args_dict = args_dict.copy()
            
            # 2.1 尝试解析所有字符串形式的 JSON
            import json
            for k, v in new_args_dict.items():
                if isinstance(v, str) and (v.strip().startswith('[') or v.strip().startswith('{')):
                    try:
                        new_args_dict[k] = json.loads(v)
                    except Exception:
                        pass
            
            # 2.2 尝试进行参数模糊匹配与 Alias 纠正
            schema = self.parameters.model_json_schema()
            required_fields = schema.get("required", [])
            properties = schema.get("properties", {})
            provided_fields = list(new_args_dict.keys())
            
            # 定义常见别名映射 (针对模型容易幻觉的参数名)
            common_aliases = {
                "file_path": ["path", "filepath", "file", "location"],
                "content": ["text", "code", "data", "value", "body"],
                "arguments": ["args", "params", "parameters"],
                "todos": ["todo_list", "items", "todo_items", "tasks"],
                "task_id": ["id", "taskId", "taskID", "todo_id", "todoId"],
            }
            
            modified = False
            for req in required_fields:
                if req in new_args_dict:
                    continue
                
                # 2.2.1 检查内置别名
                found_alias = False
                if req in common_aliases:
                    for alias in common_aliases[req]:
                        if alias in new_args_dict:
                            new_args_dict[req] = new_args_dict.pop(alias)
                            found_alias = True
                            modified = True
                            break
                if found_alias:
                    continue

                # 2.2.2 寻找可能的模糊匹配
                # 寻找可能的替代项 (如果有且仅有一个其他字段，且 required 只有一个)
                if len(provided_fields) == 1 and len(required_fields) == 1:
                    actual_key = provided_fields[0]
                    new_args_dict[req] = new_args_dict.pop(actual_key)
                    modified = True
                    break
                
                # 基于常见前缀/后缀匹配
                potential_matches = [
                    k for k in provided_fields 
                    if req in k or k in req or k.strip('_') == req or req.strip('_') == k
                ]
                if len(potential_matches) == 1:
                    new_args_dict[req] = new_args_dict.pop(potential_matches[0])
                    modified = True
            
            # 2.2.3 🔧 特殊逻辑：如果是 Todo 类的工具，且传入的是对象而非列表，自动转换
            if self.id == "todo_write" and "todos" in new_args_dict:
                val = new_args_dict["todos"]
                if isinstance(val, dict):
                    new_args_dict["todos"] = [val]
                    modified = True
            
            # 2.2.4 🔧 处理空参数的情况 - 给 LLM 明确的提示
            if not new_args_dict or (len(new_args_dict) == 0):
                # LLM 传了空对象 {}，这通常意味着它不确定如何调用工具
                # 提供一个有用的错误消息而不是让验证失败
                error_msg = (
                    f"Tool '{self.id}' was called with empty parameters. "
                    f"This tool requires specific parameters. "
                    f"Please review the tool description and provide the required parameters:\n"
                    f"{self.description[:500]}"
                )
                # 不调用 end_execution，因为 start_execution 还没被调用
                raise ValueError(error_msg)

            # 2.3 再次尝试验证
            try:
                args = self.parameters.model_validate(new_args_dict)
            except Exception as final_e:
                # 记录详细的验证错误，供调试使用
                logger.error(f"Tool '{self.id}' validation failed after correction attempt: {final_e}. Best guess args: {new_args_dict}")
                error_msg = (
                    f"Tool '{self.id}' received invalid arguments: {e}\n"
                    f"Please rewrite the input to satisfy the expected schema."
                )
                # 不调用 end_execution，因为 start_execution 还没被调用
                raise ValueError(error_msg) from final_e
        
        # 参数验证成功后，开始日志记录
        # 导入日志记录器
        from app.agents.tools.tool_logger import get_tool_logger
        
        # 创建日志记录器（如果有数据库会话则使用）
        tool_logger = get_tool_logger(ctx.db)
        
        # 记录执行开始
        await tool_logger.start_execution(
            tool_id=self.id,
            session_id=ctx.session_id,
            user_id=ctx.user_id,
            agent_id=ctx.agent,
            message_id=ctx.message_id,
            args=args_dict,
        )
        
        try:
            # 执行
            start_time = time.time()
            result = await self.execute(args, ctx)
            elapsed = time.time() - start_time
            
            # 添加执行时间到 metadata
            result.metadata["elapsed_seconds"] = round(elapsed, 2)
            
            # 记录执行成功
            await tool_logger.end_execution(
                success=True,
                output=result.output,
                metadata=result.metadata,
            )
            
            return result
            
        except Exception as e:
            # 记录执行错误
            await tool_logger.log_error(e)
            await tool_logger.end_execution(
                success=False,
                error=str(e),
            )
            raise


# ========== 工具装饰器 (简化定义) ==========

def define_tool(
    tool_id: str,
    description: str,
    parameters: type[BaseModel],
):
    """
    工具定义装饰器
    
    用法:
        @define_tool("my_tool", "工具描述", MyParams)
        async def my_tool(args: MyParams, ctx: ToolContext) -> ToolResult:
            return ToolResult(output="result")
    """
    def decorator(func: Callable[[T, ToolContext], ToolResult]):
        class DecoratedTool(Tool):
            @property
            def id(self) -> str:
                return tool_id
            
            @property
            def description(self) -> str:
                return description
            
            @property
            def parameters(self) -> type[BaseModel]:
                return parameters
            
            async def execute(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
                return await func(args, ctx)
        
        return DecoratedTool()
    
    return decorator
