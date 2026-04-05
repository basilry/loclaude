"""검색 도구 (grep, glob)."""

from __future__ import annotations

import re
from pathlib import Path

from core.tool_registry import ToolRegistry
from core.types import PermissionMode

MAX_FILE_SIZE = 2_000_000  # 2MB
MAX_RESULTS = 50


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="grep",
        description="Search file contents with regex. Returns matching lines with file paths.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern"},
                "path": {"type": "string", "description": "Search directory", "default": "."},
                "include": {"type": "string", "description": "File glob filter (e.g. '*.py')", "default": "*"},
                "context": {"type": "integer", "description": "Context lines around match", "default": 0},
            },
            "required": ["pattern"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def grep(pattern: str, path: str = ".", include: str = "*", context: int = 0) -> dict:
        root = Path(workspace).resolve() / path
        try:
            rx = re.compile(pattern)
        except re.error as e:
            return {"output": f"Invalid regex: {e}"}

        results, searched = [], 0
        targets = [root] if root.is_file() else sorted(root.rglob(include))

        for fp in targets:
            if not fp.is_file() or fp.stat().st_size > MAX_FILE_SIZE:
                continue
            searched += 1
            try:
                lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if rx.search(line):
                    rel = fp.relative_to(Path(workspace).resolve())
                    start, end = max(0, i - context), min(len(lines), i + context + 1)
                    snippet = "\n".join(f"  {j+1:>4} | {lines[j]}" for j in range(start, end))
                    results.append(f"{rel}:{i+1}\n{snippet}")
                    if len(results) >= MAX_RESULTS:
                        break
            if len(results) >= MAX_RESULTS:
                break

        header = f"Searched {searched} files, {len(results)} matches"
        return {"output": header + ("\n\n" + "\n\n".join(results) if results else "")}

    @registry.tool(
        name="glob",
        description="Find files matching a glob pattern.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '**/*.ts')"},
                "path": {"type": "string", "description": "Base directory", "default": "."},
            },
            "required": ["pattern"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def glob_search(pattern: str, path: str = ".") -> dict:
        root = Path(workspace).resolve() / path
        matches = sorted(root.glob(pattern))[:200]
        entries = [str(m.relative_to(root)) for m in matches]
        return {"output": f"Found {len(matches)} files:\n" + "\n".join(entries)}
