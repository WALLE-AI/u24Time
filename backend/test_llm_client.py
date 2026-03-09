#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLMClient v2.0 整体测试脚本
Usage: python /tmp/test_llm_client.py
"""
import asyncio
import os
import sys
import time
import types

# ── 模拟 settings (避免 DB 初始化) ───────────────────────────────────────────
_mock = types.ModuleType("config")
_mock.settings = types.SimpleNamespace(
    LLM_API_KEY=os.environ.get("LLM_API_KEY", ""),
    LLM_BASE_URL=os.environ.get("LLM_BASE_URL", ""),
    LLM_MODEL_NAME=os.environ.get("LLM_MODEL_NAME", "Qwen3-30B-A3B-Instruct-2507"),
)
sys.modules["config"] = _mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.llm_client import (
    LLMClient, TaskType, PROVIDER_BASE_URLS,
    _build_registry_from_env, get_fast_client,
)

PASS = "✅"; FAIL = "❌"; SKIP = "⏭"

results = []

def check(name: str, ok: bool, detail: str = ""):
    icon = PASS if ok else FAIL
    print(f"  {icon}  {name}" + (f" — {detail}" if detail else ""))
    results.append((name, ok))

# ════════════════════════════════════════════════════════════
# TEST 1: Provider Registry & 路由
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 1: Provider Registry & 路由")
print("═"*55)

registry, router = _build_registry_from_env()
avail = registry.available()
print(f"  可用 Provider: {avail}")

check("custom provider 已注册",   "custom" in avail)
check("至少 1 个 provider 可用",   len(avail) >= 1)

for task in [TaskType.DEFAULT, TaskType.FAST, TaskType.ANALYSIS, TaskType.REPORT]:
    chain = router.resolve(task)
    check(f"Task({task.value}) 路由非空", len(chain) > 0, f"chain={chain[:3]}")

# URL 映射完整性
for name, url in PROVIDER_BASE_URLS.items():
    check(f"URL 映射({name})", url.startswith("http"), url)

# ════════════════════════════════════════════════════════════
# TEST 2: LLMClient 初始化 & 向后兼容属性
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 2: LLMClient 初始化 & 向后兼容")
print("═"*55)

client = LLMClient()
for attr in ["api_key", "base_url", "model", "timeout"]:
    check(f"属性 .{attr} 存在", hasattr(client, attr), str(getattr(client, attr, ""))[:50])

for method in ["chat", "chat_stream", "complete", "generate_summary",
               "classify_items_batch", "status"]:
    check(f"方法 .{method}() 存在", hasattr(client, method) and callable(getattr(client, method)))

status = client.status()
check("status() 返回字典", isinstance(status, dict))
check("status() 含 available_providers", "available_providers" in status)
print(f"  Providers: {status.get('available_providers')}")

# 带显式参数的构造器 (向后兼容)
client2 = LLMClient(
    api_key=os.environ.get("LLM_API_KEY","sk-test"),
    base_url=os.environ.get("LLM_BASE_URL","http://test/v1"),
    model="test-model",
)
check("显式构造器向后兼容", client2.model == "test-model")

# ════════════════════════════════════════════════════════════
# TEST 3: 真实 API — chat()
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 3: 真实 API — chat()")
print("═"*55)

async def test_chat():
    c = LLMClient()
    if not registry.available():
        check("chat() 真实调用", False, "无可用 Provider")
        return

    t0 = time.time()
    try:
        response = await c.chat(
            messages=[
                {"role": "system", "content": "你是一个助手，请简洁回答。"},
                {"role": "user",   "content": "用一句话介绍你自己，不超过20个字。"},
            ],
            task=TaskType.FAST,
            temperature=0.3,
            max_tokens=100,
        )
        elapsed = time.time() - t0
        ok = bool(response) and len(response) > 2
        check("chat() 返回非空响应", ok, f"{elapsed:.1f}s | '{response[:80]}'")
    except Exception as e:
        check("chat() 真实调用", False, str(e)[:100])

asyncio.run(test_chat())

# ════════════════════════════════════════════════════════════
# TEST 4: 流式输出 — chat_stream()
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 4: 流式输出 — chat_stream()")
print("═"*55)

async def test_stream():
    c = LLMClient()
    if not registry.available():
        print(f"  {SKIP}  跳过 (无可用 Provider)")
        return
    chunks = []
    t0 = time.time()
    try:
        async for chunk in c.chat_stream(
            messages=[{"role": "user", "content": "请用数字1到5依次报数，每个数字后换行。"}],
            task=TaskType.FAST,
            max_tokens=50,
        ):
            chunks.append(chunk)
        elapsed = time.time() - t0
        full = "".join(chunks)
        check("chat_stream() 返回多个 chunk", len(chunks) > 1, f"{len(chunks)} chunks in {elapsed:.1f}s")
        check("chat_stream() 内容非空", bool(full.strip()), f"'{full[:60]}'")
    except Exception as e:
        check("chat_stream() 调用", False, str(e)[:100])

asyncio.run(test_stream())

# ════════════════════════════════════════════════════════════
# TEST 5: 向后兼容接口 — generate_summary()
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 5: 向后兼容 — generate_summary()")
print("═"*55)

async def test_generate_summary():
    c = LLMClient()
    domain_groups = {
        "technology": [
            {"title": "GPT-5 发布", "body": "OpenAI 发布最新大语言模型，性能大幅提升"},
            {"title": "AI 监管新规", "body": "欧盟出台 AI 法案，要求透明度和可解释性"},
        ],
        "economy": [
            {"title": "美联储降息25个基点", "body": "联邦利率降至 4.25%，市场反应积极"},
        ],
    }
    t0 = time.time()
    try:
        result = await c.generate_summary(domain_groups)
        elapsed = time.time() - t0
        ok = bool(result) and "摘要" not in result[:10] if result.startswith("智能") else bool(result)
        check("generate_summary() 返回内容", bool(result), f"{elapsed:.1f}s | {len(result)} 字")
        print(f"    摘要预览: {result[:120]}...")
    except Exception as e:
        check("generate_summary() 调用", False, str(e)[:100])

asyncio.run(test_generate_summary())

# ════════════════════════════════════════════════════════════
# TEST 6: 向后兼容接口 — classify_items_batch()
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
print("TEST 6: 向后兼容 — classify_items_batch()")
print("═"*55)

async def test_classify():
    c = LLMClient()
    items = [
        {"id": "item-001", "title": "GPU算力不足？英伟达H100全球断货", "body": "因AI训练需求爆炸..."},
        {"id": "item-002", "title": "美债10年期收益率突破5%", "body": "市场恐慌"},
        {"id": "item-003", "title": "Nature发表AlphaFold3重大突破", "body": "蛋白质结构预测..."},
    ]
    t0 = time.time()
    try:
        result = await c.classify_items_batch(items)
        elapsed = time.time() - t0
        valid_domains = {"global","economy","technology","academic","entertainment"}
        ok = len(result) > 0 and all(
            v.get("domain") in valid_domains for v in result.values()
        )
        check("classify_items_batch() 返回字典", isinstance(result, dict))
        check("分类结果 domain 合法", ok, f"{elapsed:.1f}s")
        for item_id, cls in result.items():
            print(f"    {item_id}: domain={cls.get('domain')}, sub={cls.get('sub_domain')}")
    except Exception as e:
        check("classify_items_batch() 调用", False, str(e)[:100])

asyncio.run(test_classify())

# ════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════
print("\n" + "═"*55)
passed = sum(1 for _, ok in results if ok)
total  = len(results)
print(f"测试结果: {passed}/{total} 通过")
if passed == total:
    print("🎉 ALL TESTS PASSED")
else:
    failed = [name for name, ok in results if not ok]
    print(f"❌ 失败项: {failed}")
print("═"*55)
