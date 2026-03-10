# Port OpenClaw Tools to Backend Implementation Plan

## Goal Description
The objective is to perfectly port the rich toolset from `opensource/openclaw` (TypeScript) into `backend/agents/tools/` (Python). The existing backend uses a `Tool` base class with `pydantic` parameters and an `async execute(self, args, ctx)` method. We will systematically translate the TypeScript schemas to Pydantic models, and implement Python equivalents of the capabilities using available runtime libraries.

*Note: `web_search` and `web_fetch` are already implemented in the backend, meaning they serve as good reference points.*

## User Review Required
> [!IMPORTANT]  
> This plan outlines the comprehensive tool mapping based on a deep dive into the OpenClaw source code. Please review it carefully. The implementation uses Python equivalents for Node.js-specific behaviors. Let me know if you want to selectively disable any tools or if you approve the full porting execution.

### OpenClaw to Python Tool Mapping

| OpenClaw Tools | Python Target File | Description | Python Implementation Strategy |
| --- | --- | --- | --- |
| `exec`, `process` | `bash.py` | Execute bash commands and manage background processes. | Use `asyncio.create_subprocess_shell` and a process registry to manage background tasks, timeouts, and pty sessions. |
| `browser` | `browser.py` | Browser control (navigate, click, snapshot, screenshot). | Drive headless browsers using `playwright` (async) or `pyppeteer`. Maintain context sessions. |
| `image`, `pdf` | `media.py` | Vision analysis for images & PDF parsing. | Read uploaded files via `ctx.get_files()`. Use `pdfplumber` or `PyPDF2` for PDFs, and call LLM Vision models for images. |
| `message`, `tts` | `communication.py` | Send messages to users, trigger Text-to-Speech. | Interface with backend channel dispatchers. Use OpenAI TTS or edge-tts for TTS feature. |
| `sessions_spawn`, `sessions_list`, `sessions_history`, `sessions_send`, `subagents`, `session_status`, `agents_list` | `sessions.py` | List/manage sessions, spawn nested agents. | Query DB/SqlAlchemy models for Sessions. Invoke `AgentRunner` to orchestrate subagent spawning. |
| `memory_search`, `memory_get` | `memory.py` | Semantic/hybrid search over MEMORY.md and workspaces. | Follow OpenClaw's dual approach: Use SQLite FTS (Full Text Search) + Vector Embeddings for Hybrid Search, or optionally use Python `lancedb` for vector indexing. Fall back to simple BM25 keyword matching if embeddings are unavailable. |
| `canvas`, `nodes`, `gateway` | `system.py` | Virtual canvas UI, worker nodes, gateway state. | Abstract to backend state queries returning JSON payload of the node registry. |
| `cron` | `cron.py` | Schedule recursive/repeated tasks. | Wrap tasks in an `apscheduler` loop or native `asyncio` delayed execution queue. |
| `diffs` | `diffs.py` | Create visual diff viewer URLs and render PDF/PNG. | Use `playwright` (async) or a diff-rendering library to generate HTML diffs. |
| `llm_task` | `llm_task.py` | Run isolated, schema-validated LLM prompts. | Execute a sub-instance of the backend LLM engine/AgentRunner to return JSON. |
| `lobster` | `lobster.py` | Run predefined pipeline workflows. | Call local subprocesses or backend workflow orchestration engines. |

## Proposed Changes

We will create several new files in `backend/agents/tools/` to modularize the tools logically:

* **[NEW] [bash.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/bash.py)**: `ExecTool`, `ProcessTool`
* **[NEW] [browser.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/browser.py)**: `BrowserTool`
* **[NEW] [media.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/media.py)**: `ImageTool`, `PdfTool`
* **[NEW] [sessions.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/sessions.py)**: `SessionsSpawnTool`, `SessionsListTool`, `SessionsHistoryTool`, `SessionsSendTool`, `SubagentsTool`, `SessionStatusTool`, `AgentsListTool`
* **[NEW] [memory.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/memory.py)**: `MemorySearchTool`, `MemoryGetTool`
* **[NEW] [communication.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/communication.py)**: `MessageTool`, `TtsTool`
* **[NEW] [system.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/system.py)**: `CanvasTool`, `NodesTool`, `GatewayTool`, `CronTool`
* **[NEW] [diffs.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/diffs.py)**: `DiffsTool`
* **[NEW] [llm_task.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/llm_task.py)**: `LlmTaskTool`
* **[NEW] [lobster.py](file:///d:/LLM/project/WALL-AI/u24Time/backend/agents/tools/lobster.py)**: `LobsterTool`

### Phase 1: Tool Definitions
Define all tool classes inheriting from `Tool` with `pydantic` basemodels mirroring OpenClaw parameter schemas, raising `NotImplementedError` in execution to test discovery.

### Phase 2: Implementation
Implement the `execute` logic for each functional domain, heavily reusing existing backend infrastucture (`ToolContext` and existing agent pipelines). Ensure `memory_search` matches the hybrid functionality seen in `src/memory/manager.ts`.

## Verification Plan
1. Parse the schema representations generated by `to_openai_function()` to ensure matching expected OpenClaw strict types.
2. Manually test tool availability in `build`, `plan`, and `explore` agent modes visually or by using a local runner script.
