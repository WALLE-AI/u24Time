from typing import Any, Type, Optional, List, Dict
from pydantic import BaseModel, Field
from agents.tools.base import Tool, ToolContext, ToolResult


def optional_string_enum(*args):
    """Placeholder for description representing enums"""
    return " | ".join(args)

# ----------------------------------------------------------------------------
# Memory Search Tool
# ----------------------------------------------------------------------------

class MemorySearchToolParams(BaseModel):
    query: str
    maxResults: Optional[int] = None
    minScore: Optional[float] = None


class MemorySearchTool(Tool):
    @property
    def id(self) -> str:
        return "memory_search"

    @property
    def description(self) -> str:
        return "Mandatory recall step: semantically search MEMORY.md + memory/*.md"

    @property
    def parameters(self) -> Type[BaseModel]:
        return MemorySearchToolParams

    async def execute(self, args: MemorySearchToolParams, ctx: ToolContext) -> ToolResult:
        import json
        if not ctx.directory:
            return ToolResult(
                output=json.dumps({"results": [], "disabled": True, "error": "No workspace directory provided."})
            )

        import os
        import glob
        from pathlib import Path
        
        base_dir = Path(ctx.directory)
        search_paths = [
            base_dir / "MEMORY.md",
            *(base_dir / "memory").rglob("*.md")
        ]

        results = []
        query_lower = args.query.lower()
        keywords = [k for k in query_lower.split() if len(k) > 1]
        if not keywords:
            keywords = [query_lower]

        for file_path in search_paths:
            if not file_path.exists() or not file_path.is_file():
                continue
            
            try:
                rel_path = file_path.relative_to(base_dir).as_posix()
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    
                # Simple chunking by paragraph or lines
                chunk_size = 10
                for i in range(0, len(lines), chunk_size):
                    chunk_lines = lines[i:i+chunk_size]
                    chunk_text = "".join(chunk_lines)
                    chunk_lower = chunk_text.lower()
                    
                    # Calculate simple score based on keyword matches
                    match_count = sum(1 for k in keywords if k in chunk_lower)
                    if match_count > 0:
                        score = match_count / len(keywords)
                        if args.minScore and score < args.minScore:
                            continue
                            
                        results.append({
                            "chunk_id": f"{rel_path}:{i}",
                            "path": rel_path,
                            "snippet": chunk_text.strip()[:700],
                            "score": score,
                            "startLine": i + 1,
                            "endLine": i + len(chunk_lines)
                        })
            except Exception as e:
                pass # Skip unreadable files

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        if args.maxResults:
            results = results[:args.maxResults]

        return ToolResult(
            output=json.dumps({
                "results": results,
                "provider": "local_search",
                "citations": "auto"
            }, ensure_ascii=False),
            success=True
        )


# ----------------------------------------------------------------------------
# Memory Get Tool
# ----------------------------------------------------------------------------

class MemoryGetToolParams(BaseModel):
    path: str
    from_: Optional[int] = Field(None, alias="from")
    lines: Optional[int] = None

    class Config:
        populate_by_name = True


class MemoryGetTool(Tool):
    @property
    def id(self) -> str:
        return "memory_get"

    @property
    def description(self) -> str:
        return "Safe snippet read from MEMORY.md or memory/*.md with optional from/lines"

    @property
    def parameters(self) -> Type[BaseModel]:
        return MemoryGetToolParams

    async def execute(self, args: MemoryGetToolParams, ctx: ToolContext) -> ToolResult:
        import json
        if not ctx.directory:
            return ToolResult(
                output=json.dumps({"path": args.path, "text": "", "disabled": True, "error": "No workspace directory."}),
                success=False,
                error="No workspace directory."
            )
            
        import os
        from pathlib import Path
        
        base_dir = Path(ctx.directory).resolve()
        target_path = (base_dir / args.path).resolve()
        
        # Security check: ensure target_path is within base_dir
        if not str(target_path).startswith(str(base_dir)):
            return ToolResult(
                output=json.dumps({"path": args.path, "text": "", "disabled": True, "error": "Access denied: outside workspace."}),
                success=False,
                error="Access denied: outside workspace."
            )
            
        if not target_path.exists() or not target_path.is_file():
            return ToolResult(
                output=json.dumps({"path": args.path, "text": "", "disabled": True, "error": "File not found."}),
                success=False,
                error="File not found."
            )

        try:
            with open(target_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                
            start_idx = max(0, (args.from_ or 1) - 1)
            end_idx = start_idx + args.lines if args.lines else len(lines)
            
            snippet = "".join(lines[start_idx:end_idx])
            return ToolResult(
                output=json.dumps({"path": args.path, "text": snippet}, ensure_ascii=False),
                success=True
            )
        except Exception as e:
            return ToolResult(
                output=json.dumps({"path": args.path, "text": "", "disabled": True, "error": str(e)}),
                success=False,
                error=str(e)
            )
