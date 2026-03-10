"""
Web æç´¢å·¥å·ï¼ç»ä¸ Manager é©±å¨è·¯ç±çï¼

æ¶æï¼?
  WebSearchTool.execute()
    âââ _build_provider_manager()   æå»º Provider é¾ï¼æ?SEARCH_PROVIDER_PRIORITY ææå®?providerï¼?
    âââ manager.search_with_fallback()  èªå¨éçº§æ§è¡æç´¢
    âââ _fetch_and_assemble()       ç»ä¸ URL æå + Markdown ç»è£ï¼åªæ­¤ä¸ä»½ï¼

æ¯æçæç´¢æä¾åï¼?
  - exa        (EXA_API_KEY å¿é¡»)
  - bocha      (BOCHA_API_KEY å¿é¡»)
  - brave      (BRAVE_API_KEY å¿é¡»)
  - perplexity (PERPLEXITY_API_KEY å¿é¡»)
  - grok       (XAI_API_KEY å¿é¡»)
  - ddgs       (æ é API Keyï¼åè´?Fallback)
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

# ========== ç¯å¢åé ==========
SEARCH_BACKEND = os.getenv("SEARCH_BACKEND", "exa")
EXA_API_KEY = os.getenv("EXA_API_KEY")
BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
XAI_API_KEY = os.getenv("XAI_API_KEY")
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY")


# ========== åæ°æ¨¡å ==========

class WebSearchParams(BaseModel):
    """Web æç´¢åæ° (OpenClaw å¯¹é½ç?"""
    query: str = Field(..., description="Search query string.")
    count: Optional[int] = Field(5, ge=1, le=10, description="Number of results to return (1-10).")
    country: Optional[str] = Field(None, description="2-letter country code for region-specific results.")
    language: Optional[str] = Field(None, description="ISO 639-1 language code for results.")
    freshness: Optional[str] = Field(None, description="Filter by time: 'day' (24h), 'week', 'month', or 'year'.")
    date_after: Optional[str] = Field(None, description="Only results published after this date (YYYY-MM-DD).")
    date_before: Optional[str] = Field(None, description="Only results published before this date (YYYY-MM-DD).")
    
    # Brave specific
    search_lang: Optional[str] = Field(None, description="Brave language code for search results.")
    ui_lang: Optional[str] = Field(None, description="Locale code for UI elements.")
    
    # Perplexity specific
    domain_filter: Optional[List[str]] = Field(None, description="Domain filter (max 20).")
    max_tokens: Optional[int] = Field(None, ge=1, le=1000000)
    max_tokens_per_page: Optional[int] = Field(None, ge=1)
    
    # Backward compatibility
    query_or_url: Optional[str] = Field(None, description="Alias for query or a direct URL.")
    num_results: Optional[int] = Field(None, description="Alias for count.")
    provider: Optional[str] = Field(None, description="Specify search provider.")


# ========== æç´¢ç»ææ¨¡å ==========

class SearchResult(BaseModel):
    """æç´¢ç»æ"""
    title: str
    url: str
    description: Optional[str] = None
    age: Optional[str] = None


# ========== æç´¢æä¾åæ½è±¡åºç±?==========

class SearchProvider(ABC):
    """æç´¢æä¾åæ½è±¡åºç±?""

    @abstractmethod
    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """æ§è¡æç´¢"""
        pass


# ========== Exa æç´¢æä¾å?==========

class ExaSearchProvider(SearchProvider):
    """Exa Search æä¾å?""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """æ§è¡ Exa æç´¢"""
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


# ========== DuckDuckGo æç´¢æä¾å?==========

class DDGSSearchProvider(SearchProvider):
    """DuckDuckGo Search æä¾åï¼åè´¹ Fallbackï¼?""

    async def search(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """æ§è¡ DuckDuckGo æç´¢ï¼å«ä¸­æåºå + æ¥æå¤çº§éçº§"""
        if DDGS is None:
            raise ValueError("ddgs package not installed. Please run: uv add ddgs")

        # æ£æµä¸­æï¼è®¾ç½®åºå
        region = "cn-zh" if re.search(r'[\u4e00-\u9fff]', query) else "wt-wt"

        def _search_sync(q, r):
            with DDGS() as ddgs:
                return list(ddgs.text(q, region=r, max_results=count))

        results = await asyncio.to_thread(_search_sync, query, region)

        # éçº§ 1: ä¸­ææ ç»æ?â?å¨çæç´¢
        if not results and region == "cn-zh":
            results = await asyncio.to_thread(_search_sync, query, "wt-wt")

        # éçº§ 2: å«æ¥ææ ç»æ â?å»ææ¥æéæ
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


# ========== Brave æç´¢æä¾å?==========

class BraveSearchProvider(SearchProvider):
    """Brave Search æä¾å?""

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
        """æ§è¡ Brave æç´¢"""
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


# ========== Perplexity æç´¢æä¾å?==========

class PerplexitySearchProvider(SearchProvider):
    """Perplexity Search æä¾åï¼ä¹ç¨äº?Grok/xAIï¼?""

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
        """æ§è¡ Perplexity æç´¢ï¼è¿å?AI æè¦ + å¼ç¨é¾æ¥"""
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


# ========== Bocha æç´¢æä¾å?==========

class BochaSearchProvider(SearchProvider):
    """Bocha Search æä¾åï¼åæ¥ï¼?""

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
        """æ§è¡ Bocha æç´¢ï¼æ¯æ?freshness éä¼ """
        import httpx

        config = get_config()
        timeout = config.web_search_timeout

        body = {
            "query": query,
            "freshness": freshness if freshness else "noLimit",  # æ¯æè°ç¨æ¹ä¼ å?
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


# ========== æç´¢æä¾åç®¡çå¨ ==========

class SearchProviderManager:
    """æç´¢æä¾åç®¡çå¨"""

    def __init__(self):
        self.providers: dict[str, SearchProvider] = {}
        self.priority: list[tuple[int, str]] = []

    def register(self, name: str, provider: SearchProvider, priority: int = 0):
        """æ³¨åæä¾å?""
        self.providers[name] = provider
        self.priority.append((priority, name))
        self.priority.sort(reverse=True)

    async def search_with_fallback(
        self,
        query: str,
        count: int = 5,
        **kwargs
    ) -> tuple[list[SearchResult], str]:
        """å¸¦éçº§çæç´¢ï¼æä¼åçº§ä¾æ¬¡å°è¯ï¼ç¬¬ä¸ä¸ªè¿åéç©ºç»æå³åæ­¢"""
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


# ========== Web æç´¢å·¥å·ä¸»ç±» ==========

class WebSearchTool(Tool):
    """
    é«çº§ Web æç´¢å·¥å·ï¼ç»ä¸ Manager é©±å¨è·¯ç±ï¼?

    æ¯ææç´¢æ¥è¯¢åç´æ¥è®¿é?URLãä½¿ç?Playwright å¤çå¨æåå®¹ï¼å¹¶ä½¿ç?Readability æåæç« ä¸»ä½ã?
    æææç´¢æä¾åç»ä¸ç»ç± SearchProviderManager è°åº¦ï¼æ¯æèªå¨éçº§ã?
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
        æå»º SearchProviderManagerã?

        é»è¾ï¼?
          - è?args.provider æå®äºå·ä½?provider â?åªæ³¨åè¯¥ä¸ä¸ªï¼ä¼åçº?100ï¼?
          - å¦å â?è¯»å SEARCH_PROVIDER_PRIORITY ç¯å¢éç½®ï¼æ³¨åå¨é¨å¯ç?provider
        """
        manager = SearchProviderManager()

        if args.provider:
            # ===== æå® Provider æ¨¡å¼ =====
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
            # æªå¹éï¼manager.providers ä¸ºç©ºï¼è°ç¨æ¹ä¼å¤çéè¯?
            return manager

        # ===== èªå¨ Provider é¾æ¨¡å¼ï¼æ?SEARCH_PROVIDER_PRIORITYï¼?====
        config = get_config()
        priority_list = config.search_provider_priority  # e.g. ["exa", "bocha", "ddgs"]

        for i, name in enumerate(priority_list):
            score = 100 - i * 10  # exa=100, bocha=90, ddgs=80 â?
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

        # ååºï¼ç¡®ä¿èªå¨æ¨¡å¼ä¸è³å°æä¸ä¸?providerï¼DDGS åè´¹ï¼æ é Keyï¼?
        if not manager.providers and DDGS is not None:
            print("[web_search] No configured provider available, falling back to DDGS")
            manager.register("ddgs", DDGSSearchProvider(), priority=0)

        return manager

    async def execute(
        self,
        args: WebSearchParams,
        ctx: ToolContext,
    ) -> ToolResult:
        """æ§è¡ Web æç´¢ææå?""
        query_or_url = args.query_or_url.strip()

        # å¤æ­æ?URL è¿æ¯æç´¢è¯?
        is_url = bool(re.match(r'^https?://', query_or_url.lower()))

        search_context = ""
        urls_to_visit = []

        if is_url:
            urls_to_visit = [query_or_url]
        else:
            # ===== ç»ä¸ Manager æç´¢è·¯ç± =====
            manager = self._build_provider_manager(args)

            if not manager.providers:
                # æ²¡æä»»ä½å¯ç¨ provider
                provider_label = args.provider or "(auto)"
                return ToolResult(
                    title=f"Web search: {query_or_url}",
                    output=f"Error: Provider '{provider_label}' is not available or API key is not configured.",
                    metadata={"query": query_or_url, "provider": provider_label, "error": "provider_unavailable"}
                )

            # ç»è£æç´¢åæ°ï¼éä¼ ç»å providerï¼?
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

            # æ ¼å¼åæç´¢æè¦?
            search_context = f"### Search Results (via {provider_name.title()}):\n"
            for i, r in enumerate(results):
                search_context += f"{i+1}. [{r.title}]({r.url})\n"
                if r.description:
                    search_context += f"   {r.description}\n"
                if r.age:
                    search_context += f"   Age: {r.age}\n"
                search_context += "\n"

                # åå 2 ä¸ªææ?URL ç¨äºæ·±åº¦æå
                if len(urls_to_visit) < 2 and r.url and r.url.startswith("http"):
                    urls_to_visit.append(r.url)

        # ===== å¬å±æåæ¶å°¾ =====
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
        å¹¶åæå URL åå®¹ï¼æå¤?2 ä¸ªï¼ï¼ç»è£æç»?Markdown è¾åºã?

        _depth: éå½æ·±åº¦ä¿æ¤ï¼æå¤éå½ 1 æ¬¡ï¼URL è®¿é®å¤±è´¥æ¶éçº§ä¸ºæç´¢ï¼?
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

        # URL ç´æ¥è®¿é®å¤±è´¥ â?éå½éçº§ä¸ºæç´¢ï¼æå¤?1 æ¬¡ï¼
        if not valid_urls and is_url and _depth == 0:
            fallback_query = re.sub(r'[^\w\s]', ' ', query).strip()
            if fallback_query:
                return await self.execute(WebSearchParams(query_or_url=fallback_query), ctx)

        # ç»è£ Markdown
        parts = []
        if search_context:
            parts.append(search_context)
        if fetched_contents:
            parts.extend(fetched_contents)
        elif not search_context:
            parts.append(first_error or "Empty content.")

        markdown_content = "\n\n---\n\n".join(parts)

        # ä¿å­å°ç£çå¤ä»½ï¼éé»å¤±è´¥ï¼?
        try:
            output_dir = Path("output/search_results")
            output_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r'[^\w\-_.]', '_', (urls[0] if urls else query))[:100]
            filename = f"{safe_name}_{int(time.time())}.md"
            with open(output_dir / filename, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
        except Exception:
            pass

        # æªæ­è?30000 å­ç¬¦
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
