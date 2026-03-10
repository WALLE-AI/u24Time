"""
Web 抓取工具

从 URL 获取网页内容，支持转换为 Markdown
参考 opencode webfetch.ts 实现
"""
import os
from typing import Literal, Optional

from pydantic import BaseModel, Field

from agents.tools.base import Tool, ToolContext, ToolResult
from agents.tools.config import get_config


MAX_RESPONSE_SIZE = 5 * 1024 * 1024  # 5MB (将被配置覆盖)
DEFAULT_TIMEOUT = 30  # seconds (将被配置覆盖)

# 配置（保持向后兼容）
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

# Jina Reader 配置
JINA_API_KEY = os.getenv("JINA_API_KEY")
JINA_READER_BASE = "https://r.jina.ai"


class WebFetchParams(BaseModel):
    """Web 抓取参数"""
    url: str = Field(..., description="要抓取的 URL")
    format: Literal["text", "markdown", "html"] = Field(
        default="markdown",
        description="返回格式: text, markdown, html (默认: markdown)",
    )
    timeout: int = Field(
        default=DEFAULT_TIMEOUT,
        description=f"超时秒数 (默认: {DEFAULT_TIMEOUT})",
    )
    # 新增可选参数（保持向后兼容）
    use_playwright: bool = Field(
        default=False,
        description="使用 Playwright 处理动态内容（JavaScript 渲染）"
    )
    use_firecrawl: bool = Field(
        default=False,
        description="使用 Firecrawl API 进行高质量内容提取"
    )
    use_jina: bool = Field(
        default=False,
        description="使用 Jina Reader API 进行高质量正文提取（免费可用，有 JINA_API_KEY 时解除限速）"
    )
    extract_target: Literal["main_content", "full_page"] = Field(
        default="main_content",
        description="提取目标策略: 'main_content' (智能提取正文, 过滤导航/广告) 或 'full_page' (保留完整网页结构)"
    )


class WebFetchTool(Tool):
    """
    网页抓取工具
    
    从 URL 获取网页内容，可转换为纯文本或 Markdown。
    """
    
    @property
    def id(self) -> str:
        return "web_fetch"
    
    @property
    def description(self) -> str:
        return """Fetch content from a URL and convert it to text or markdown.
Use this tool when you need to:
- Read documentation from a URL
- Extract content from web pages
- Get the text content of articles

Supports automatic HTML to Markdown conversion."""
    
    @property
    def parameters(self) -> type[BaseModel]:
        return WebFetchParams
    
    async def execute(
        self,
        args: WebFetchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """执行网页抓取"""
        # 验证 URL
        if not args.url.startswith(("http://", "https://")):
            return ToolResult(
                title=f"Fetch: {args.url}",
                output="Error: URL must start with http:// or https://",
                metadata={"url": args.url, "error": "invalid_url"},
            )
        
        # 优先级：Firecrawl > Jina Reader > Playwright > httpx
        if args.use_firecrawl and FIRECRAWL_API_KEY:
            return await self._fetch_with_firecrawl(args, ctx)
        elif args.use_jina:
            return await self._fetch_with_jina(args, ctx)
        elif args.use_playwright:
            return await self._fetch_with_playwright(args, ctx)
        else:
            # 使用现有逻辑（完全不变）
            return await self._fetch_with_httpx(args, ctx)
    
    def _html_to_markdown(self, html: str, extract_target: str = "full_page", url: Optional[str] = None) -> str:
        """HTML 转 Markdown"""
        if extract_target == "main_content":
            try:
                from app.agents.tools.utils import ReadabilityExtractor
                extractor = ReadabilityExtractor()
                extracted = extractor.extract_article(html)
                if url:
                    extracted.url = url
                return extracted.to_markdown()
            except ImportError:
                # readability-lxml 未安装，退化为全页转换
                pass

        try:
            from markdownify import markdownify
            return markdownify(html, heading_style="ATX", strip=["script", "style"])
        except ImportError:
            # markdownify 未安装，简单处理
            return self._html_to_text(html)
    
    def _html_to_text(self, html: str) -> str:
        """HTML 转纯文本"""
        import re
        
        # 移除 script 和 style
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        
        # 移除所有 HTML 标签
        html = re.sub(r'<[^>]+>', ' ', html)
        
        # 压缩空白
        html = re.sub(r'\s+', ' ', html)
        
        return html.strip()
    
    async def _fetch_with_httpx(
        self,
        args: WebFetchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """使用 httpx 抓取（现有逻辑）"""
        import httpx
        
        try:
            # 发送请求
            async with httpx.AsyncClient(timeout=args.timeout) as client:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
                }
                
                response = await client.get(args.url, headers=headers, follow_redirects=True)
                response.raise_for_status()
                
                # 检查响应大小
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_RESPONSE_SIZE:
                    return ToolResult(
                        title=f"Fetch: {args.url}",
                        output="Error: Response too large (exceeds 5MB limit)",
                        metadata={"url": args.url, "error": "too_large"},
                    )
                
                content = response.text
                content_type = response.headers.get("content-type", "")
                
                # 根据格式处理内容
                if args.format == "markdown" and "text/html" in content_type:
                    content = self._html_to_markdown(content, extract_target=args.extract_target, url=args.url)
                elif args.format == "text" and "text/html" in content_type:
                    content = self._html_to_text(content)
                
                # 截断过长内容
                if len(content) > MAX_RESPONSE_SIZE:
                    content = content[:MAX_RESPONSE_SIZE] + "\n\n... (truncated)"
                
                return ToolResult(
                    title=f"Fetch: {args.url}",
                    output=content,
                    metadata={
                        "url": args.url,
                        "content_type": content_type,
                        "length": len(content),
                        "method": "httpx",
                    },
                )
                
        except httpx.TimeoutException:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: Request timed out after {args.timeout} seconds",
                metadata={"url": args.url, "error": "timeout"},
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: HTTP {e.response.status_code}",
                metadata={"url": args.url, "error": f"http_{e.response.status_code}"},
            )
        except Exception as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: {str(e)}",
                metadata={"url": args.url, "error": str(e)},
            )
    
    async def _fetch_with_playwright(
        self,
        args: WebFetchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """使用 Playwright 抓取（处理动态内容）"""
        try:
            from playwright.async_api import async_playwright
            import asyncio
        except ImportError:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output="Error: Playwright not installed. Please run: uv add playwright && playwright install chromium",
                metadata={"url": args.url, "error": "playwright_not_installed"},
            )
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = await context.new_page()
                
                # 访问 URL
                response = await page.goto(
                    args.url,
                    wait_until="domcontentloaded",
                    timeout=args.timeout * 1000
                )
                
                if response and response.status >= 400:
                    await browser.close()
                    return ToolResult(
                        title=f"Fetch: {args.url}",
                        output=f"Error: HTTP {response.status}",
                        metadata={"url": args.url, "error": f"http_{response.status}"},
                    )
                
                # 模拟滚动触发懒加载
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                await asyncio.sleep(1)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)
                
                # 等待网络空闲
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except:
                    pass
                
                # 获取内容
                html = await page.content()
                await browser.close()
                
                # 根据格式处理内容
                if args.format == "markdown":
                    content = self._html_to_markdown(html, extract_target=args.extract_target, url=args.url)
                elif args.format == "text":
                    content = self._html_to_text(html)
                else:
                    content = html
                
                # 截断过长内容
                if len(content) > MAX_RESPONSE_SIZE:
                    content = content[:MAX_RESPONSE_SIZE] + "\n\n... (truncated)"
                
                return ToolResult(
                    title=f"Fetch: {args.url}",
                    output=content,
                    metadata={
                        "url": args.url,
                        "length": len(content),
                        "method": "playwright",
                    },
                )
                
        except Exception as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: {str(e)}",
                metadata={"url": args.url, "error": str(e), "method": "playwright"},
            )
    
    async def _fetch_with_firecrawl(
        self,
        args: WebFetchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """使用 Firecrawl API 抓取（高质量内容提取）"""
        import httpx
        
        if not FIRECRAWL_API_KEY:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output="Error: FIRECRAWL_API_KEY not configured",
                metadata={"url": args.url, "error": "api_key_missing"},
            )
        
        try:
            body = {
                "url": args.url,
                "formats": ["markdown"] if args.format == "markdown" else ["html"],
                "onlyMainContent": True if args.extract_target == "main_content" else False,
                "timeout": args.timeout * 1000,
                "maxAge": 172800000,  # 2 days cache
                "storeInCache": True,
            }
            
            async with httpx.AsyncClient(timeout=args.timeout) as client:
                response = await client.post(
                    "https://api.firecrawl.dev/v1/scrape",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {FIRECRAWL_API_KEY}",
                        "Content-Type": "application/json",
                    }
                )
                response.raise_for_status()
                data = response.json()
            
            # 提取内容
            if args.format == "markdown":
                content = data.get("data", {}).get("markdown", "")
            else:
                content = data.get("data", {}).get("html", "")
            
            if args.format == "text":
                content = self._html_to_text(content)
            
            # 截断过长内容
            if len(content) > MAX_RESPONSE_SIZE:
                content = content[:MAX_RESPONSE_SIZE] + "\n\n... (truncated)"
            
            metadata = data.get("data", {}).get("metadata", {})
            
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=content,
                metadata={
                    "url": args.url,
                    "title": metadata.get("title"),
                    "length": len(content),
                    "method": "firecrawl",
                    "status": metadata.get("statusCode"),
                },
            )
            
        except httpx.TimeoutException:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: Firecrawl request timed out after {args.timeout} seconds",
                metadata={"url": args.url, "error": "timeout", "method": "firecrawl"},
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: Firecrawl API returned HTTP {e.response.status_code}",
                metadata={"url": args.url, "error": f"http_{e.response.status_code}", "method": "firecrawl"},
            )
        except Exception as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: {str(e)}",
                metadata={"url": args.url, "error": str(e), "method": "firecrawl"},
            )

    async def _fetch_with_jina(
        self,
        args: WebFetchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """
        使用 Jina Reader API 抓取（高质量正文提取）

        Jina Reader (r.jina.ai) 工作流程：
        1. 接收目标 URL，在服务端访问并渲染（支持 JS）
        2. 基于内部 Readability 提取主要正文内容
        3. 默认直接返回干净的 Markdown，无需本地转换

        免费层有限速；配置 JINA_API_KEY 后携带 Authorization 头可解除限制。
        """
        import httpx

        try:
            # 构建 Jina Reader URL：r.jina.ai/{目标URL}
            jina_url = f"{JINA_READER_BASE}/{args.url}"

            headers = {
                "Accept": "text/plain",           # 接受纯文本响应
                "X-Timeout": str(args.timeout),   # 传递超时给 Jina 服务端
            }

            # 按 format 参数决定 Jina 返回格式
            if args.format == "html":
                headers["X-Return-Format"] = "html"
            else:
                # markdown / text 都让 Jina 直接返回 Markdown，text 再本地转换
                headers["X-Return-Format"] = "markdown"

            # 若配置了 API Key，添加认证头解除限速
            if JINA_API_KEY:
                headers["Authorization"] = f"Bearer {JINA_API_KEY}"

            # 正文模式：告知 Jina 剥离导航栏、页脚、广告等噪音
            if args.extract_target == "main_content":
                headers["X-Remove-Selector"] = "header, footer, nav, .sidebar, .ads, .advertisement"

            async with httpx.AsyncClient(timeout=args.timeout) as client:
                response = await client.get(jina_url, headers=headers, follow_redirects=True)
                response.raise_for_status()
                content = response.text

            # text 格式：Jina 返回 Markdown，再转纯文本
            if args.format == "text":
                content = self._html_to_text(content)
            # html / markdown 格式：Jina 已直接返回相应格式，无需本地处理

            # 截断过长内容
            if len(content) > MAX_RESPONSE_SIZE:
                content = content[:MAX_RESPONSE_SIZE] + "\n\n... (truncated)"

            return ToolResult(
                title=f"Fetch: {args.url}",
                output=content,
                metadata={
                    "url": args.url,
                    "jina_url": jina_url,
                    "length": len(content),
                    "method": "jina",
                    "authenticated": bool(JINA_API_KEY),
                },
            )

        except httpx.TimeoutException:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: Jina Reader request timed out after {args.timeout} seconds",
                metadata={"url": args.url, "error": "timeout", "method": "jina"},
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: Jina Reader API returned HTTP {e.response.status_code}",
                metadata={"url": args.url, "error": f"http_{e.response.status_code}", "method": "jina"},
            )
        except Exception as e:
            return ToolResult(
                title=f"Fetch: {args.url}",
                output=f"Error: {str(e)}",
                metadata={"url": args.url, "error": str(e), "method": "jina"},
            )

