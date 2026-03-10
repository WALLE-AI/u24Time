"""
Web 搜索工具（统一 Manager 驱动路由版）

架构：
  WebSearchTool.execute()
    └── _build_provider_manager()   构建 Provider 链（按 SEARCH_PROVIDER_PRIORITY 或指定 provider）
    └── manager.search_with_fallback()  自动降级执行搜索
    └── _fetch_and_assemble()       统一 URL 抓取 + Markdown 组装（只此一份）

支持的搜索提供商：
  - exa        (EXA_API_KEY 必须)
  - bocha      (BOCHA_API_KEY 必须)
  - brave      (BRAVE_API_KEY 必须)
  - perplexity (PERPLEXITY_API_KEY 必须)
  - grok       (XAI_API_KEY 必须)
  - ddgs       (无需 API Key，免费 Fallback)
"""
import re
import asyncio
import time
import os
from pathlib import Path
from typing import Optional
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from agents.tools.base import Tool, ToolContext, ToolResult
from agents.tools.utils import ReadabilityExtractor
from agents.tools.config import get_config
from agents.tools.web_fetch import WebFetchTool, WebFetchParams

# DuckDuckGo Search
try:
    from ddgs import DDGS
except ImportError:
    DDGS = None

# Exa Search
try:
    from exa_py import Exa
except ImportError:
    Exa = None

# ========== 环境变量 ==========
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "exa")
EXA_API_KEY = os.getenv("EXA_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY")


# ========== 参数模型 ==========

class WebSearchParams(BaseModel):
    """Web 搜索参数"""
    query_or_url: str = Field(..., description="搜索查询 (例如: 'AI 最新进展') 或 直接 URL (例如: 'https://example.com')")
    num_results: int = Field(default=5, description="返回结果数量 (仅当输入为查询时有效, 默认: 5)")
    provider: Optional[str] = Field(default=None, description="指定搜索提供商 (brave, perplexity, grok, exa, ddgs, bocha)；不指定则按 SEARCH_PROVIDER_PRIORITY 自动选择")
    country: Optional[str] = Field(default=None, description="国家代码 (用于 Brave Search, 例如: US, CN)")
    search_lang: Optional[str] = Field(default=None, description="搜索语言 (用于 Brave Search, 例如: en, zh)")
    freshness: Optional[str] = Field(default=None, description="时间过滤：pd=past day, pw=past week, pm=past month, py=past year。Brave/Bocha 均支持")


# ========== 搜索结果模型 ==========

class SearchResult(BaseModel):
    """搜索结果"""
    title: str
    url: str
    description: Optional[str] = None
    age: Optional[str] = None


# ========== 搜索提供商抽象基类 ==========

class SearchProvider(ABC):
    """搜索提供商抽象基类"""

    @abstractmethod
    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """执行搜索"""
        pass


# ========== Exa 搜索提供商 ==========

class ExaSearchProvider(SearchProvider):
    """Exa Search 提供商"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """执行 Exa 搜索"""
        if not Exa:
            raise ValueError("exa_py package not installed. Please run: uv add exa-py")

        exa = Exa(api_key=self.api_key)

        search_response = await asyncio.to_thread(
            exa.search_and_contents,
            query,
            num_results=count,
            text={"max_characters": 20000},
        )

        if not search_response.results:
            return []

        results = []
        for r in search_response.results:
            results.append(SearchResult(
                title=r.title or "",
                url=r.url or "",
                description=r.text[:500] if r.text else None,
            ))
        return results


# ========== DuckDuckGo 搜索提供商 ==========

class DDGSSearchProvider(SearchProvider):
    """DuckDuckGo Search 提供商（免费 Fallback）"""

    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """执行 DuckDuckGo 搜索，含中文区域 + 日期多级降级"""
        if DDGS is None:
            raise ValueError("ddgs package not installed. Please run: uv add ddgs")

        # 检测中文，设置区域
        region = "cn-zh" if re.search(r'[\u4e00-\u9fff]', query) else "wt-wt"

        def _search_sync(q, r):
            with DDGS() as ddgs:
                return list(ddgs.text(q, region=r, max_results=count))

        results = await asyncio.to_thread(_search_sync, query, region)

        # 降级 1: 中文无结果 → 全球搜索
        if not results and region == "cn-zh":
            results = await asyncio.to_thread(_search_sync, query, "wt-wt")

        # 降级 2: 含日期无结果 → 去掉日期重搜
        if not results:
            date_pattern = r'\d{4}-\d{2}-\d{2}'
            if re.search(date_pattern, query):
                clean_query = re.sub(date_pattern, '', query).strip()
                results = await asyncio.to_thread(_search_sync, clean_query, region)
                if not results and region == "cn-zh":
                    results = await asyncio.to_thread(_search_sync, clean_query, "wt-wt")

        if not results:
            return []

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("href", ""),
                description=r.get("body"),
            )
            for r in results
            if r.get("href", "").startswith("http")
        ]


# ========== Brave 搜索提供商 ==========

class BraveSearchProvider(SearchProvider):
    """Brave Search 提供商"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.search.brave.com/res/v1/web/search"

    async def search(
        self,
        query: str,
        count: int = 5,
        country: str = "US",
        search_lang: str = "en",
        ui_lang: str = "en",
        freshness: Optional[str] = None,
        **kwargs
    ) -> list[SearchResult]:
        """执行 Brave 搜索"""
        import httpx

        config = get_config()
        timeout = config.web_search_timeout

        params = {
            "q": query,
            "count": str(count),
            "country": country,
            "search_lang": search_lang,
            "ui_lang": ui_lang,
        }
        if freshness:
            params["freshness"] = freshness

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                response = await client.get(
                    self.endpoint,
                    params=params,
                    headers={
                        "X-Subscription-Token": self.api_key,
                        "Accept": "application/json",
                    }
                )
                response.raise_for_status()
                data = response.json()

            return [
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    description=item.get("description"),
                    age=item.get("age"),
                )
                for item in data.get("web", {}).get("results", [])
            ]
        except Exception as e:
            print(f"Brave Search failed: {e}")
            return []


# ========== Perplexity 搜索提供商 ==========

class PerplexitySearchProvider(SearchProvider):
    """Perplexity Search 提供商（也用于 Grok/xAI）"""

    def __init__(self, api_key: str, base_url: str = "https://api.perplexity.ai"):
        self.api_key = api_key
        self.base_url = base_url

    async def search(
        self,
        query: str,
        count: int = 5,
        model: str = "sonar",
        **kwargs
    ) -> list[SearchResult]:
        """执行 Perplexity 搜索，返回 AI 摘要 + 引用链接"""
        import httpx

        config = get_config()
        timeout = config.web_search_timeout

        body = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Search query: {query}\n\nProvide a comprehensive answer with citations."
                }
            ],
            "return_citations": True,
        }

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    }
                )
                response.raise_for_status()
                data = response.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            citations = data.get("citations", [])

            results = []
            if content:
                results.append(SearchResult(
                    title="AI Summary (Perplexity)",
                    url=citations[0] if citations else "",
                    description=content[:500] if len(content) > 500 else content,
                ))
            for i, url in enumerate(citations[1:count], start=2):
                results.append(SearchResult(
                    title=f"Citation {i}",
                    url=url,
                ))
            return results
        except Exception as e:
            print(f"Perplexity Search failed: {e}")
            return []


# ========== Bocha 搜索提供商 ==========

class BochaSearchProvider(SearchProvider):
    """Bocha Search 提供商（博查）"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.bocha.cn/v1/web-search"

    async def search(
        self,
        query: str,
        count: int = 5,
        freshness: Optional[str] = None,
        **kwargs
    ) -> list[SearchResult]:
        """执行 Bocha 搜索，支持 freshness 透传"""
        import httpx

        config = get_config()
        timeout = config.web_search_timeout

        body = {
            "query": query,
            "freshness": freshness if freshness else "noLimit",  # 支持调用方传入
            "summary": True,
            "count": count,
        }

        try:
            async with httpx.AsyncClient(timeout=float(timeout)) as client:
                response = await client.post(
                    self.endpoint,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    }
                )
                response.raise_for_status()
                data = response.json()

            results = []
            if data.get("code") == 200 and data.get("data"):
                for item in data["data"].get("webPages", {}).get("value", []):
                    results.append(SearchResult(
                        title=item.get("name", ""),
                        url=item.get("url", ""),
                        description=item.get("snippet"),
                        age=item.get("dateLastCrawled"),
                    ))
            return results
        except Exception as e:
            print(f"Bocha Search failed: {e}")
            return []


# ========== 搜索提供商管理器 ==========

class SearchProviderManager:
    """搜索提供商管理器"""

    def __init__(self):
        self.providers: dict[str, SearchProvider] = {}
        self.priority: list[tuple[int, str]] = []

    def register(self, name: str, provider: SearchProvider, priority: int = 0):
        """注册提供商"""
        self.providers[name] = provider
        self.priority.append((priority, name))
        self.priority.sort(reverse=True)

    async def search_with_fallback(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> tuple[list[SearchResult], str]:
        """带降级的搜索：按优先级依次尝试，第一个返回非空结果即停止"""
        last_error = None

        for _, provider_name in self.priority:
            provider = self.providers.get(provider_name)
            if not provider:
                continue

            try:
                print(f"Searching with {provider_name}: {query}")
                results = await provider.search(query, count, **kwargs)
                if results:
                    return results, provider_name
            except Exception as e:
                print(f"Provider '{provider_name}' failed: {e}")
                last_error = e
                continue

        if last_error:
            raise last_error

        return [], "none"


# ========== Web 搜索工具主类 ==========

class WebSearchTool(Tool):
    """
    高级 Web 搜索工具（统一 Manager 驱动路由）

    支持搜索查询和直接访问 URL。使用 Playwright 处理动态内容，并使用 Readability 提取文章主体。
    所有搜索提供商统一经由 SearchProviderManager 调度，支持自动降级。
    """

    @property
    def id(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return """Searches the web or visits a specific URL to extract its content.
If the input is a URL, it visits it directly. If it's a query, it searches and visits the top result.
Returns the extracted content in Markdown format, truncated to 30000 characters."""

    @property
    def parameters(self) -> type[BaseModel]:
        return WebSearchParams

    def _build_provider_manager(self, args: WebSearchParams) -> SearchProviderManager:
        """
        构建 SearchProviderManager。

        逻辑：
          - 若 args.provider 指定了具体 provider → 只注册该一个（优先级 100）
          - 否则 → 读取 SEARCH_PROVIDER_PRIORITY 环境配置，注册全部可用 provider
        """
        manager = SearchProviderManager()

        if args.provider:
            # ===== 指定 Provider 模式 =====
            p = args.provider.lower()
            if p == "exa" and Exa and EXA_API_KEY:
                manager.register("exa", ExaSearchProvider(EXA_API_KEY), priority=100)
            elif p == "bocha" and BOCHA_API_KEY:
                manager.register("bocha", BochaSearchProvider(BOCHA_API_KEY), priority=100)
            elif p == "brave" and BRAVE_API_KEY:
                manager.register("brave", BraveSearchProvider(BRAVE_API_KEY), priority=100)
            elif p == "perplexity" and PERPLEXITY_API_KEY:
                manager.register("perplexity", PerplexitySearchProvider(PERPLEXITY_API_KEY), priority=100)
            elif p == "grok" and XAI_API_KEY:
                manager.register("grok", PerplexitySearchProvider(XAI_API_KEY, base_url="https://api.x.ai/v1"), priority=100)
            elif p == "ddgs" and DDGS is not None:
                manager.register("ddgs", DDGSSearchProvider(), priority=100)
            # 未匹配：manager.providers 为空，调用方会处理错误
            return manager

        # ===== 自动 Provider 链模式（按 SEARCH_PROVIDER_PRIORITY）=====
        config = get_config()
        priority_list = config.search_provider_priority  # e.g. ["exa", "bocha", "ddgs"]

        for i, name in enumerate(priority_list):
            score = 100 - i * 10  # exa=100, bocha=90, ddgs=80 …
            name = name.strip().lower()
            if name == "exa" and Exa and EXA_API_KEY:
                manager.register("exa", ExaSearchProvider(EXA_API_KEY), priority=score)
            elif name == "bocha" and BOCHA_API_KEY:
                manager.register("bocha", BochaSearchProvider(BOCHA_API_KEY), priority=score)
            elif name == "brave" and BRAVE_API_KEY:
                manager.register("brave", BraveSearchProvider(BRAVE_API_KEY), priority=score)
            elif name == "perplexity" and PERPLEXITY_API_KEY:
                manager.register("perplexity", PerplexitySearchProvider(PERPLEXITY_API_KEY), priority=score)
            elif name == "grok" and XAI_API_KEY:
                manager.register("grok", PerplexitySearchProvider(XAI_API_KEY, base_url="https://api.x.ai/v1"), priority=score)
            elif name == "ddgs" and DDGS is not None:
                manager.register("ddgs", DDGSSearchProvider(), priority=score)

        # 兜底：确保自动模式下至少有一个 provider（DDGS 免费，无需 Key）
        if not manager.providers and DDGS is not None:
            print("[web_search] No configured provider available, falling back to DDGS")
            manager.register("ddgs", DDGSSearchProvider(), priority=0)

        return manager

    async def execute(
        self,
        args: WebSearchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """执行 Web 搜索或抓取"""
        query_or_url = args.query_or_url.strip()

        # 判断是 URL 还是搜索词
        is_url = bool(re.match(r'^https?://', query_or_url.lower()))

        search_context = ""
        urls_to_visit = []

        if is_url:
            urls_to_visit = [query_or_url]
        else:
            # ===== 统一 Manager 搜索路由 =====
            manager = self._build_provider_manager(args)

            if not manager.providers:
                # 没有任何可用 provider
                provider_label = args.provider or "(auto)"
                return ToolResult(
                    title=f"Web search: {query_or_url}",
                    output=f"Error: Provider '{provider_label}' is not available or API key is not configured.",
                    metadata={"query": query_or_url, "provider": provider_label, "error": "provider_unavailable"}
                )

            # 组装搜索参数（透传给各 provider）
            search_kwargs = {}
            if args.country:
                search_kwargs["country"] = args.country
            if args.search_lang:
                search_kwargs["search_lang"] = args.search_lang
            if args.freshness:
                search_kwargs["freshness"] = args.freshness

            try:
                results, provider_name = await manager.search_with_fallback(
                    query_or_url,
                    args.num_results,
                    **search_kwargs
                )
            except Exception as e:
                return ToolResult(
                    title=f"Web search: {query_or_url}",
                    output=f"Error during search: {str(e)}",
                    metadata={"query": query_or_url, "error": str(e)}
                )

            if not results:
                return ToolResult(
                    title=f"Web search: {query_or_url}",
                    output=f"No search results found for query: {query_or_url}",
                    metadata={"query": query_or_url}
                )

            # 格式化搜索摘要
            search_context = f"### Search Results (via {provider_name.title()}):\n"
            for i, r in enumerate(results):
                search_context += f"{i+1}. [{r.title}]({r.url})\n"
                if r.description:
                    search_context += f"   {r.description}\n"
                if r.age:
                    search_context += f"   Age: {r.age}\n"
                search_context += "\n"

                # 取前 2 个有效 URL 用于深度抓取
                if len(urls_to_visit) < 2 and r.url and r.url.startswith("http"):
                    urls_to_visit.append(r.url)

        # ===== 公共抓取收尾 =====
        return await self._fetch_and_assemble(
            query_or_url, urls_to_visit, search_context, is_url, ctx
        )

    async def _fetch_and_assemble(
        self,
        query: str,
        urls: list[str],
        search_context: str,
        is_url: bool,
        ctx: ToolContext,
        _depth: int = 0,
    ) -> ToolResult:
        """
        并发抓取 URL 内容（最多 2 个），组装最终 Markdown 输出。

        _depth: 递归深度保护，最多递归 1 次（URL 访问失败时降级为搜索）
        """
        fetch_tool = WebFetchTool()
        fetched_contents = []
        valid_urls = []
        first_error = None

        async def fetch_single(url: str):
            params = WebFetchParams(
                url=url,
                format="markdown",
                use_playwright=True,
                extract_target="main_content"
            )
            return await fetch_tool.execute(params, ctx), url

        tasks = [fetch_single(u) for u in urls[:2]]
        if tasks:
            fetch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in fetch_results:
                if isinstance(res, tuple):
                    fetch_result, url = res
                    if "Error:" not in fetch_result.output:
                        fetched_contents.append(
                            f"### Content from [{url}]({url})\n\n{fetch_result.output}"
                        )
                        valid_urls.append(url)
                    else:
                        if not first_error:
                            first_error = fetch_result.output
                else:
                    print(f"Fetch exception: {res}")

        # URL 直接访问失败 → 递归降级为搜索（最多 1 次）
        if not valid_urls and is_url and _depth == 0:
            fallback_query = re.sub(r'[^\w\s]', ' ', query).strip()
            if fallback_query:
                return await self.execute(WebSearchParams(query_or_url=fallback_query), ctx)

        # 组装 Markdown
        parts = []
        if search_context:
            parts.append(search_context)
        if fetched_contents:
            parts.extend(fetched_contents)
        elif not search_context:
            parts.append(first_error or "Empty content.")

        markdown_content = "\n\n---\n\n".join(parts)

        # 保存到磁盘备份（静默失败）
        try:
            output_dir = Path("output/search_results")
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^\w\-_.]', '_', (urls[0] if urls else query))[:100]
            filename = f"{safe_name}_{int(time.time())}.md"
            with open(output_dir / filename, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
        except Exception:
            pass

        # 截断至 30000 字符
        target_limit = 30000
        if len(markdown_content) > target_limit:
            markdown_content = markdown_content[:target_limit] + "\n\n... (Output truncated for brevity) ..."

        return ToolResult(
            title=f"Web search: {query}",
            output=markdown_content,
            metadata={
                "query_or_url": query,
                "visited_urls": valid_urls,
                "is_url": is_url,
                "length": len(markdown_content),
            }
        )
