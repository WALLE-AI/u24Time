# -*- coding: utf-8 -*-
"""
LLMClient v2.0 — 多 Provider 统一接入层
全兼容 openai SDK 范式 (AsyncOpenAI)

支持厂商:
  openrouter   https://openrouter.ai/api/v1
  siliconflow  https://api.siliconflow.cn/v1
  volcengine   https://ark.cn-beijing.volces.com/api/v3  (火山引擎)
  bailian      https://dashscope.aliyuncs.com/compatible-mode/v1  (百炼/DashScope)
  vllm         http://localhost:8000/v1   (本地 vLLM)
  sglang       http://localhost:30000/v1  (本地 sglang)
  openai       https://api.openai.com/v1
  custom       LLM_BASE_URL 环境变量     (向后兼容)

路由策略 (通过 .env 配置, 不改代码):
  LLM_ROUTER_DEFAULT    → 默认任务使用的 Provider
  LLM_ROUTER_FAST       → 快速小模型 (分类/关键词/embedding)
  LLM_ROUTER_ANALYSIS   → 深度分析大模型
  LLM_ROUTER_REPORT     → 长文档报告
  LLM_ROUTER_SUMMARY    → 摘要任务

向后兼容:
  generate_summary()         保留原接口签名 ✅
  classify_items_batch()     保留原接口签名 ✅
  LLMClient(api_key, base_url, model) 保留构造参数 ✅
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Optional

from loguru import logger


# ─── 厂商 base_url 映射表 ──────────────────────────────────────────────────────

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai":       "https://api.openai.com/v1",
    "openrouter":   "https://openrouter.ai/api/v1",
    "siliconflow":  "https://api.siliconflow.cn/v1",
    "volcengine":   "https://ark.cn-beijing.volces.com/api/coding/v3",
    "bailian":      "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "vllm":         "http://118.196.10.206:443/llm_router",
    "sglang":       "http://118.196.10.206:443/llm_router",
    # "custom" は LLM_BASE_URL から読み取る
}

# 各厂商默认模型 (若环境变量未配置时的兜底值)
PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "openai":       "gpt-4o-mini",
    "openrouter":   "openai/gpt-4o-mini",
    "siliconflow":  "Qwen/Qwen2.5-7B-Instruct",
    "volcengine":   "ep-placeholder",
    "bailian":      "qwen-turbo",
    "vllm":         "default",
    "sglang":       "default",
    "custom":       "Qwen3-30B-A3B-Instruct-2507",
}


# ─── 任务类型 ─────────────────────────────────────────────────────────────────

class TaskType(str, Enum):
    DEFAULT    = "default"    # 通用对话
    FAST       = "fast"       # 快速小模型 (分类/关键词)
    ANALYSIS   = "analysis"   # 深度分析
    SUMMARY    = "summary"    # 摘要
    REPORT     = "report"     # 长报告
    EMBEDDING  = "embedding"  # 嵌入
    CODE       = "code"       # 代码生成


# ─── Provider 配置 ────────────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    """单个 LLM Provider 的连接配置"""
    name: str                     # 厂商标识 (openrouter/siliconflow/…)
    api_key: str
    base_url: str
    model: str
    timeout: float = 60.0
    max_retries: int = 2
    extra_headers: dict = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self):
        self.base_url = self.base_url.rstrip("/")

    def to_client_kwargs(self) -> dict:
        """构造 AsyncOpenAI 实例参数"""
        return {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "timeout": self.timeout,
            "max_retries": self.max_retries,
            "default_headers": self.extra_headers or None,
        }


# ─── Provider 注册中心 ────────────────────────────────────────────────────────

class ProviderRegistry:
    """
    管理所有 Provider 配置和 AsyncOpenAI 客户端实例池
    延迟初始化 (首次调用时创建 client 实例)
    """

    def __init__(self):
        self._configs: dict[str, ProviderConfig] = {}
        self._clients: dict[str, Any] = {}  # name → openai.AsyncOpenAI

    def register(self, config: ProviderConfig) -> None:
        if not config.enabled or not config.api_key:
            return
        self._configs[config.name] = config
        logger.debug(f"ProviderRegistry: 注册 '{config.name}' ({config.base_url})")

    def get_client(self, name: str) -> Optional[Any]:
        """获取 AsyncOpenAI 客户端 (懒加载)"""
        if name not in self._configs:
            return None
        if name not in self._clients:
            try:
                from openai import AsyncOpenAI
                cfg = self._configs[name]
                kwargs = cfg.to_client_kwargs()
                # 过滤掉 None 的 default_headers
                if kwargs.get("default_headers") is None:
                    kwargs.pop("default_headers", None)
                self._clients[name] = AsyncOpenAI(**kwargs)
                logger.debug(f"ProviderRegistry: 创建 AsyncOpenAI client '{name}'")
            except ImportError:
                logger.warning("ProviderRegistry: openai package 未安装, 降级为 httpx 模式")
                return None
            except Exception as e:
                logger.error(f"ProviderRegistry: 创建 client '{name}' 失败 — {e}")
                return None
        return self._clients[name]

    def get_config(self, name: str) -> Optional[ProviderConfig]:
        return self._configs.get(name)

    def available(self) -> list[str]:
        return list(self._configs.keys())

    def is_available(self, name: str) -> bool:
        return name in self._configs and bool(self._configs[name].api_key)


# ─── 任务路由器 ───────────────────────────────────────────────────────────────

class TaskRouter:
    """
    按任务类型选择 Provider + Fallback 链
    规则: ENV var > 显式映射 > default
    """

    def __init__(self, registry: ProviderRegistry, task_routes: dict[str, str]):
        self._registry = registry
        self._routes = task_routes  # TaskType.value → provider_name

    def resolve(self, task: TaskType = TaskType.DEFAULT) -> list[str]:
        """
        返回 Provider 优先级列表 (Fallback 顺序)
        至少包含 1 个 Provider
        """
        primary = self._routes.get(task.value) or self._routes.get("default", "custom")

        # 构建 Fallback 链: primary → default → 所有可用
        chain: list[str] = []
        for name in [primary, self._routes.get("default", "custom")]:
            if name and name not in chain and self._registry.is_available(name):
                chain.append(name)

        # 兜底: 加入所有可用 Provider
        for name in self._registry.available():
            if name not in chain:
                chain.append(name)

        return chain or ["custom"]

    def get_model(self, provider_name: str, task: TaskType) -> Optional[str]:
        """获取指定 Provider + 任务的模型名"""
        cfg = self._registry.get_config(provider_name)
        return cfg.model if cfg else None


# ─── httpx Fallback (openai SDK 不可用时) ────────────────────────────────────

async def _httpx_chat(
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
    timeout: float = 60.0,
    extra_headers: Optional[dict] = None,
) -> str:
    """直接用 httpx 调用 OpenAI 兼容 API (SDK 不可用时的降级路径)"""
    import httpx
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **(extra_headers or {}),
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()


# ─── 全局配置构建函数 ─────────────────────────────────────────────────────────

def _build_registry_from_env() -> tuple[ProviderRegistry, TaskRouter]:
    """从环境变量和 settings 构建 Registry + Router"""
    import os
    try:
        from config import settings
        _api_key   = getattr(settings, "LLM_API_KEY", "") or ""
        _base_url  = getattr(settings, "LLM_BASE_URL", "") or ""
        _model     = getattr(settings, "LLM_MODEL_NAME", "") or "Qwen3-30B-A3B-Instruct-2507"
    except Exception:
        _api_key  = os.environ.get("LLM_API_KEY", "")
        _base_url = os.environ.get("LLM_BASE_URL", "")
        _model    = os.environ.get("LLM_MODEL_NAME", "Qwen3-30B-A3B-Instruct-2507")

    def _env(key: str, default: str = "") -> str:
        try:
            from config import settings
            return getattr(settings, key, None) or os.environ.get(key, default) or default
        except Exception:
            return os.environ.get(key, default) or default

    registry = ProviderRegistry()

    # ── custom (现有主 Provider, 向后兼容) ─────────────────────────────────
    if _api_key and _base_url:
        registry.register(ProviderConfig(
            name="custom",
            api_key=_api_key,
            base_url=_base_url,
            model=_model,
        ))

    # ── OpenRouter ──────────────────────────────────────────────────────────
    or_key = _env("OPENROUTER_API_KEY")
    if or_key:
        registry.register(ProviderConfig(
            name="openrouter",
            api_key=or_key,
            base_url=PROVIDER_BASE_URLS["openrouter"],
            model=_env("OPENROUTER_MODEL", PROVIDER_DEFAULT_MODELS["openrouter"]),
            extra_headers={
                "HTTP-Referer": _env("OPENROUTER_SITE_URL", "https://u24time.ai"),
                "X-Title": _env("OPENROUTER_APP_TITLE", "U24Time"),
            },
        ))

    # ── SiliconFlow ─────────────────────────────────────────────────────────
    sf_key = _env("SILICONFLOW_API_KEY")
    if sf_key:
        registry.register(ProviderConfig(
            name="siliconflow",
            api_key=sf_key,
            base_url=PROVIDER_BASE_URLS["siliconflow"],
            model=_env("SILICONFLOW_MODEL", PROVIDER_DEFAULT_MODELS["siliconflow"]),
        ))

    # ── 火山引擎 (Volcengine/Ark) ───────────────────────────────────────────
    vol_key = _env("VOLCENGINE_API_KEY")
    if vol_key:
        registry.register(ProviderConfig(
            name="volcengine",
            api_key=vol_key,
            base_url=PROVIDER_BASE_URLS["volcengine"],
            model=_env("VOLCENGINE_MODEL", PROVIDER_DEFAULT_MODELS["volcengine"]),
        ))

    # ── 百炼 / DashScope (Bailian) ──────────────────────────────────────────
    bl_key = _env("BAILIAN_API_KEY")
    if not bl_key:
        bl_key = _env("DASHSCOPE_API_KEY")  # 兼容旧变量名
    if bl_key:
        registry.register(ProviderConfig(
            name="bailian",
            api_key=bl_key,
            base_url=PROVIDER_BASE_URLS["bailian"],
            model=_env("BAILIAN_MODEL", PROVIDER_DEFAULT_MODELS["bailian"]),
        ))

    # ── 本地 vLLM ───────────────────────────────────────────────────────────
    vllm_url = _env("LOCAL_LLM_BASE_URL") or _env("VLLM_BASE_URL")
    if vllm_url:
        registry.register(ProviderConfig(
            name="vllm",
            api_key=_env("LOCAL_LLM_API_KEY", "EMPTY"),  # vLLM 不需要真实 key
            base_url=vllm_url,
            model=_env("LOCAL_LLM_MODEL", PROVIDER_DEFAULT_MODELS["vllm"]),
            timeout=120.0,
        ))

    # ── 本地 sglang ─────────────────────────────────────────────────────────
    sglang_url = _env("SGLANG_BASE_URL")
    if sglang_url:
        registry.register(ProviderConfig(
            name="sglang",
            api_key=_env("SGLANG_API_KEY", "EMPTY"),
            base_url=sglang_url,
            model=_env("SGLANG_MODEL", PROVIDER_DEFAULT_MODELS["sglang"]),
            timeout=120.0,
        ))

    # ── OpenAI 原生 ─────────────────────────────────────────────────────────
    oai_key = _env("OPENAI_API_KEY")
    if oai_key:
        registry.register(ProviderConfig(
            name="openai",
            api_key=oai_key,
            base_url=PROVIDER_BASE_URLS["openai"],
            model=_env("OPENAI_MODEL", PROVIDER_DEFAULT_MODELS["openai"]),
        ))

    # ── 路由规则 (从 ENV 读取) ──────────────────────────────────────────────
    available = registry.available()
    _default = _env("LLM_ROUTER_DEFAULT", available[0] if available else "custom")

    task_routes = {
        TaskType.DEFAULT.value:  _env("LLM_ROUTER_DEFAULT",  _default),
        TaskType.FAST.value:     _env("LLM_ROUTER_FAST",     _default),
        TaskType.ANALYSIS.value: _env("LLM_ROUTER_ANALYSIS", _default),
        TaskType.SUMMARY.value:  _env("LLM_ROUTER_SUMMARY",  _default),
        TaskType.REPORT.value:   _env("LLM_ROUTER_REPORT",   _default),
        TaskType.CODE.value:     _env("LLM_ROUTER_CODE",     _default),
    }

    router = TaskRouter(registry, task_routes)
    return registry, router


# ─── 全局单例 ─────────────────────────────────────────────────────────────────
_global_registry: Optional[ProviderRegistry] = None
_global_router: Optional[TaskRouter] = None


def _ensure_globals():
    global _global_registry, _global_router
    if _global_registry is None:
        _global_registry, _global_router = _build_registry_from_env()
        logger.info(
            f"LLMClient: 初始化完成, 可用 Provider: {_global_registry.available()}"
        )


# ─── 主类 ──────────────────────────────────────────────────────────────────────

class LLMClient:
    """
    统一 LLM 访问客户端 v2.0
    全兼容 openai SDK 范式, 支持多 Provider 路由和 Fallback
    向后兼容原有构造函数和方法签名
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,    # 显式指定 Provider 名称
        task: Optional[TaskType] = None,   # 默认任务类型
    ):
        _ensure_globals()

        # 向后兼容: 若显式传入 api_key/base_url, 注册为临时 custom provider
        if api_key and base_url:
            _global_registry.register(ProviderConfig(
                name="_inline_custom",
                api_key=api_key,
                base_url=base_url,
                model=model or "default",
            ))
            self._forced_provider = "_inline_custom"
        else:
            self._forced_provider = provider

        self._default_task = task or TaskType.DEFAULT
        self.timeout = 60.0

        # 向后兼容属性
        try:
            _cfg = _global_registry.get_config(
                self._forced_provider or _global_router.resolve(self._default_task)[0]
            )
        except Exception:
            _cfg = None
        self.api_key  = (_cfg.api_key  if _cfg else api_key)  or ""
        self.base_url = (_cfg.base_url if _cfg else base_url) or ""
        self.model    = model or (_cfg.model if _cfg else "")

    # ── 通用对话接口 ───────────────────────────────────────────────────────────

    async def chat(
        self,
        messages: list[dict],
        task: Optional[TaskType | str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        provider: Optional[str] = None,
    ) -> str:
        """
        通用对话接口 (E2E Coordinator / AgentContext 核心调用)
        自动路由 Provider + Fallback 链
        """
        task_type = _parse_task(task or self._default_task)
        chain = (
            [provider] if provider and _global_registry.is_available(provider)
            else ([self._forced_provider] if self._forced_provider else None)
            or _global_router.resolve(task_type)
        )

        last_error: Optional[Exception] = None
        for provider_name in chain:
            try:
                return await self._chat_one(
                    provider_name, messages, task_type, temperature, max_tokens
                )
            except Exception as e:
                logger.warning(
                    f"LLMClient: Provider '{provider_name}' 失败 "
                    f"— {type(e).__name__}: {str(e)[:120]}, 尝试下一个"
                )
                last_error = e

        raise RuntimeError(
            f"LLMClient: 所有 Provider 均失败 ({chain}). "
            f"最后错误: {last_error}"
        )

    async def chat_stream(
        self,
        messages: list[dict],
        task: Optional[TaskType | str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        provider: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话接口 — 逐 token yield 输出
        Usage:
            async for chunk in client.chat_stream(messages):
                print(chunk, end="", flush=True)
        """
        task_type = _parse_task(task or self._default_task)
        chain = (
            [provider] if provider and _global_registry.is_available(provider)
            else ([self._forced_provider] if self._forced_provider else None)
            or _global_router.resolve(task_type)
        )

        for provider_name in chain:
            cfg = _global_registry.get_config(provider_name)
            if not cfg:
                continue
            client = _global_registry.get_client(provider_name)
            if client is None:
                continue
            try:
                stream = await client.chat.completions.create(
                    model=cfg.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta
                return
            except Exception as e:
                logger.warning(
                    f"LLMClient stream: Provider '{provider_name}' 失败 — {e}"
                )

        raise RuntimeError("LLMClient: 流式输出失败, 所有 Provider 均不可用")

    async def complete(
        self,
        prompt: str,
        task: Optional[TaskType | str] = None,
        system: str = "You are a helpful assistant.",
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> str:
        """单轮文本完成 (Sugar over chat)"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        return await self.chat(messages, task=task, temperature=temperature,
                               max_tokens=max_tokens)

    # ── 内部单 Provider 调用 ───────────────────────────────────────────────────

    async def _chat_one(
        self,
        provider_name: str,
        messages: list[dict],
        task_type: TaskType,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """尝试单个 Provider 调用 (openai SDK 优先, httpx 降级)"""
        cfg = _global_registry.get_config(provider_name)
        if not cfg:
            raise ValueError(f"Provider '{provider_name}' 未注册")

        # 尝试 openai SDK
        client = _global_registry.get_client(provider_name)
        if client is not None:
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()

        # 降级到 httpx
        return await _httpx_chat(
            base_url=cfg.base_url,
            api_key=cfg.api_key,
            model=cfg.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=cfg.timeout,
            extra_headers=cfg.extra_headers,
        )

    # ── 保留原有接口 (向后兼容) ───────────────────────────────────────────────

    async def generate_summary(
        self,
        domain_groups: dict[str, list[dict]],
        target_domain: Optional[str] = None,
    ) -> str:
        """
        根据各领域情报条目生成综述
        [向后兼容接口 — 保留原签名]
        """
        if not self.api_key and not _global_registry.available():
            logger.warning("LLMClient: 无可用 Provider, 返回模拟摘要")
            return self._mock_domain_summary(domain_groups, target_domain)

        domain_names = {
            "economy": "经济", "technology": "技术",
            "academic": "学术", "global": "全球监控",
        }
        context_parts = []
        for domain, items in domain_groups.items():
            if not items:
                continue
            name = domain_names.get(domain, domain)
            group_text = f"【{name} 领域】:\n" + "\n".join([
                f"- {item.get('title')}: {item.get('body', '')[:100]}..."
                if item.get("body") else f"- {item.get('title')}"
                for item in items[:15]
            ])
            context_parts.append(group_text)
        context = "\n\n".join(context_parts)

        if target_domain and target_domain != "all":
            domain_cn = domain_names.get(target_domain, target_domain)
            prompt = (
                f"你是一个资深情报分析专家。请针对选定的【{domain_cn}】领域进行深度情报综述。\n"
                f"要求:\n1. 仅针对 {domain_cn} 领域内容，不要混入其他领域。\n"
                "2. 归纳当前核心趋势、重大事件及潜在影响。\n"
                "3. 语气专业、客观、敏锐。\n4. 字数控制在 300 字以内。\n"
                "5. 必须使用中文，采用 Markdown 格式。\n\n"
                f"情报内容:\n{context}\n\n综述:"
            )
        else:
            prompt = (
                "你是一个资深全球情报分析师。请针对以下各领域最新动态，提供综合简报。\n"
                "要求:\n1. 按领域（经济、技术、学术、全球监控）综述。\n"
                "2. 每个领域精炼，突出最重要的高热度或高严重度事件。\n"
                "3. 语气专业、冷静。\n4. 总字数控制在 250 字以内。\n"
                "5. 必须使用中文，采用 Markdown 格式（使用 ## 分段）。\n\n"
                f"情报内容:\n{context}\n\n综述:"
            )

        try:
            return await self.chat(
                [{"role": "system", "content": "You are a professional intelligence analyst."},
                 {"role": "user", "content": prompt}],
                task=TaskType.SUMMARY,
                temperature=0.3,
                max_tokens=600,
            )
        except Exception as e:
            logger.error(f"LLMClient.generate_summary: 失败 — {e}")
            return f"智能化综述暂时不可用 (Error: {str(e)[:50]}...)"

    async def classify_items_batch(self, items_data: list[dict]) -> dict:
        """
        批量分类数据条目所属领域
        [向后兼容接口 — 保留原签名]
        returns: {item_id: {"domain": ..., "sub_domain": ...}, ...}
        """
        if not items_data:
            return {}
        if not _global_registry.available():
            return {}

        prompt_data = [
            {"id": item["id"],
             "text": f"Title: {item.get('title','')}\nBody: {str(item.get('body',''))[:500]}"}
            for item in items_data
        ]
        prompt = (
            "You are an expert intelligence classifier. Classify each item into: "
            "`global`, `economy`, `technology`, `academic`, or `entertainment`.\n"
            "Also assign a short `sub_domain` (1-2 words, lowercase).\n"
            "Respond ONLY with valid JSON (no markdown):\n"
            '{"item_id": {"domain": "technology", "sub_domain": "ai"}, ...}\n\n'
            f"Items:\n{json.dumps(prompt_data, ensure_ascii=False, indent=2)}"
        )

        try:
            raw = await self.chat(
                [{"role": "system",
                  "content": "Output only valid JSON. No markdown, no explanation."},
                 {"role": "user", "content": prompt}],
                task=TaskType.FAST,
                temperature=0.1,
                max_tokens=1500,
            )
            content = _strip_markdown_json(raw)
            result = json.loads(content)

            valid_domains = {"global", "economy", "technology", "academic", "entertainment"}
            domain_aliases = {"tech": "technology", "finance": "economy",
                              "science": "academic", "politics": "global"}
            final: dict = {}
            for k, v in result.items():
                d = str(v.get("domain", "")).lower()
                d = domain_aliases.get(d, d)
                if d in valid_domains:
                    final[k] = {"domain": d,
                                "sub_domain": str(v.get("sub_domain", "")).lower()[:64]}
            return final
        except Exception as e:
            logger.error(f"LLMClient.classify_items_batch: 失败 — {e}")
            return {}

    # ── 状态查询 ──────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """查询所有 Provider 的可用状态"""
        _ensure_globals()
        providers = {}
        for name in _global_registry.available():
            cfg = _global_registry.get_config(name)
            providers[name] = {
                "base_url": cfg.base_url if cfg else "",
                "model": cfg.model if cfg else "",
                "enabled": cfg.enabled if cfg else False,
            }
        return {
            "available_providers": _global_registry.available(),
            "providers": providers,
            "forced_provider": self._forced_provider,
        }

    # ── Mock (无 API Key 时) ──────────────────────────────────────────────────

    def _mock_domain_summary(
        self, domain_groups: dict, target_domain: Optional[str] = None
    ) -> str:
        if target_domain and target_domain != "all":
            items = domain_groups.get(target_domain, [])
            return (
                f"### {target_domain} 领域深度分析 (模拟)\n\n"
                f"该领域目前监测到 {len(items)} 条重要动态。"
                f"主要趋势包括 {items[0].get('title') if items else '暂无数据'} 等。"
            )
        mapping = {"economy": "经济域", "technology": "技术域",
                   "academic": "学术域", "global": "全球监控"}
        lines = ["## 全球情报综述 (模拟数据)"]
        for domain, items in domain_groups.items():
            if not items:
                continue
            name = mapping.get(domain, domain)
            lines.append(
                f"- {name}: 监测到 {len(items)} 条动态，"
                f"涵盖 {items[0].get('title','')[:30]} 等热点。"
            )
        lines.append("\n(请配置 LLM_API_KEY 以获取真实 AI 深度分析)")
        return "\n".join(lines)


# ─── 工具函数 ─────────────────────────────────────────────────────────────────

def _parse_task(task: Any) -> TaskType:
    """容错解析 TaskType"""
    if isinstance(task, TaskType):
        return task
    if isinstance(task, str):
        try:
            return TaskType(task.lower())
        except ValueError:
            return TaskType.DEFAULT
    return TaskType.DEFAULT


def _strip_markdown_json(text: str) -> str:
    """剥离 LLM 可能返回的 ```json ... ``` 包装"""
    text = text.strip()
    for prefix in ("```json", "```"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# ─── 便捷工厂函数 ─────────────────────────────────────────────────────────────

def get_llm_client(
    provider: Optional[str] = None,
    task: Optional[TaskType] = None,
) -> LLMClient:
    """获取 LLMClient 实例 (推荐使用, 比直接 LLMClient() 性能更好)"""
    return LLMClient(provider=provider, task=task)


def get_fast_client() -> LLMClient:
    """获取快速小模型客户端 (分类/关键词)"""
    return LLMClient(task=TaskType.FAST)


def get_analysis_client() -> LLMClient:
    """获取深度分析大模型客户端"""
    return LLMClient(task=TaskType.ANALYSIS)
