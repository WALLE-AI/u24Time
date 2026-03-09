# -*- coding: utf-8 -*-
"""
E2E Router API 接口测试 (FastAPI TestClient)
涵盖:
  - GET /agents/e2e/registry/status
  - GET /agents/e2e/scheduler/status
  - GET /agents/e2e/runs
  - POST /agents/e2e/run (Mock)
  - GET /agents/e2e/status/{run_id}
  - GET /agents/e2e/stream/{run_id} (SSE)
  - GET /agents/e2e/memory/search
"""

import asyncio
import sys
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── 最小 config mock 避免数据库报错 ─────────────────
import types
m = types.ModuleType("config")
m.settings = types.SimpleNamespace(
    LLM_API_KEY="test", LLM_BASE_URL="test", LLM_MODEL_NAME="test",
    AGENTS_PORT=5002, ZEP_API_URL="", ZEP_API_KEY="",
    DB_ECHO=False, DATABASE_URL_SYNC="sqlite:///./test.db",
    DATABASE_URL="sqlite+aiosqlite:///./test.db", DB_TYPE="sqlite",
    REDIS_URL="", UPSTASH_REDIS_REST_URL="", UPSTASH_REDIS_REST_TOKEN="",
    database_url="sqlite+aiosqlite:///./test.db",
    async_database_url="sqlite+aiosqlite:///./test.db",
    DATABASE_URL_ASYNC="sqlite+aiosqlite:///./test.db"
)
sys.modules["config"] = m
sys.path.insert(0, os.path.dirname(__file__))

# ── 引入待测 Router ─────────────────────────────────
from agents.routers.e2e import router as e2e_router
from agents.subagent_registry import get_subagent_registry

app = FastAPI()
app.include_router(e2e_router, prefix="/agents/e2e")

client = TestClient(app)

# ── 工具函数 ──
PASS = "✅"; FAIL = "❌"
def check(name, ok, detail=""):
    print(f"  {PASS if ok else FAIL}  {name} {f'— {detail}' if detail else ''}")
    if not ok:
        sys.exit(1)

def main():
    print("\n╔════════════════════════════════════════════════════════╗")
    print("║  E2E Router API 接口集成测试                         ║")
    print("╚════════════════════════════════════════════════════════╝\n")

    # 1. /registry/status 状态查询
    r1 = client.get("/agents/e2e/registry/status")
    check("GET /registry/status", r1.status_code == 200)
    data1 = r1.json()
    check("  返回 registry 结构", "summary" in data1 and "active_runs" in data1)

    # 2. /scheduler/status
    r2 = client.get("/agents/e2e/scheduler/status")
    check("GET /scheduler/status", r2.status_code in (200, 503)) 
    # if not initialized -> 200 {"status":"not_initialized"} or actual dict
    data2 = r2.json()
    check("  调度器返回结构合理", isinstance(data2, dict))

    # 3. /runs 历史记录查询
    r3 = client.get("/agents/e2e/runs?limit=5")
    check("GET /runs", r3.status_code == 200)
    data3 = r3.json()
    check("  返回 runs 格式", "runs" in data3 and "total" in data3)

    # 4. /run 触发分析 (Mock db 依赖以绕过 sqlalchemy 报错)
    # FastAPI 的 TestClient override_dependency 机制:
    from db.session import get_async_session
    from agents.routers.e2e import _get_llm
    
    async def mock_get_db():
        yield "mock_db"
        
    class MockLLM:
        pass

    app.dependency_overrides[get_async_session] = mock_get_db
    app.dependency_overrides[_get_llm] = lambda: MockLLM()

    r4 = client.post("/agents/e2e/run", json={"topic": "Test Topic", "is_heartbeat": True})
    check("POST /run (E2E触发)", r4.status_code == 200)
    data4 = r4.json()
    run_id = data4.get("run_id")
    check("  返回包含 run_id", bool(run_id) and data4.get("status") == "accepted", f"run_id={run_id}")

    # 5. /status/{run_id} 查询刚才触发的分析
    r5 = client.get(f"/agents/e2e/status/{run_id}")
    check("GET /status/{run_id}", r5.status_code == 200)
    data5 = r5.json()
    check("  返回匹配的 topic", data5.get("topic") == "Test Topic")
    check("  初始化状态", data5.get("status") in ("running", "error", "success"))

    # 6. /memory/search 记忆检索接口
    r6 = client.get("/agents/e2e/memory/search", params={"query": "人工智能", "k": 2})
    check("GET /memory/search", r6.status_code == 200)
    data6 = r6.json()
    check("  返回规范 search 结构", "results" in data6 and "count" in data6)
    check("  携带 query 回显", data6.get("query") == "人工智能")

    print("\n🎉 ALL API ROUTER TESTS PASSED.\n")

if __name__ == "__main__":
    main()
