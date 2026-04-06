"""위키 조작 도구 (upsert, search, backlink check)."""

from __future__ import annotations

import re
from pathlib import Path

from core.memory.factory import create_memory_backend
from core.tool_registry import ToolRegistry
from core.types import PermissionMode
from core.wiki_service import ensure_wiki_structure, upsert_wiki_document


def _get_wiki_dir() -> Path:
    from core.project_paths import get_project_paths
    return get_project_paths().wiki_dir


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="wiki_upsert",
        description="Create or update a wiki document. Syncs to index, log, and memory backend.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Document title"},
                "content": {"type": "string", "description": "Markdown content"},
                "section": {
                    "type": "string",
                    "description": "Wiki section: concepts, guides, references, queries",
                    "default": "references",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags",
                    "default": "",
                },
            },
            "required": ["title", "content"],
        },
        permission_level=PermissionMode.WORKSPACE_WRITE,
    )
    async def wiki_upsert(
        title: str,
        content: str,
        section: str = "references",
        tags: str = "",
    ) -> dict:
        wiki_dir = _get_wiki_dir()
        ensure_wiki_structure({"wiki_dir": wiki_dir})

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        result = await upsert_wiki_document(
            wiki_dir,
            title=title,
            content=content,
            section=section,
            tags=tag_list,
        )
        return {"output": f"Wiki '{title}' saved to {result['path']}"}

    @registry.tool(
        name="wiki_search",
        description="Search wiki documents by keyword query.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {
                    "type": "integer",
                    "description": "Max results",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    async def wiki_search(query: str, top_k: int = 5) -> dict:
        wiki_dir = _get_wiki_dir()
        backend = create_memory_backend(wiki_dir=wiki_dir)
        results = await backend.search(query, top_k=top_k)
        if not results:
            return {"output": "No results found."}
        lines = []
        for r in results:
            score = r.get("score", 0)
            title = r.get("title", "?")
            snippet = r.get("snippet", "")[:120]
            path = r.get("wiki_path", "")
            lines.append(f"- [{title}]({path}) (score: {score:.2f})\n  {snippet}")
        return {"output": f"Found {len(results)} results:\n" + "\n".join(lines)}

    @registry.tool(
        name="wiki_backlink_check",
        description="Cross-check index.md entries against actual files. Reports mismatches.",
        parameters={
            "type": "object",
            "properties": {
                "wiki_dir": {
                    "type": "string",
                    "description": "Wiki directory path (auto-detected if empty)",
                    "default": "",
                },
            },
            "required": [],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def wiki_backlink_check(wiki_dir: str = "") -> dict:
        wd = Path(wiki_dir) if wiki_dir else _get_wiki_dir()
        index_path = wd / "index.md"
        if not index_path.exists():
            return {"output": "index.md not found"}

        text = index_path.read_text(encoding="utf-8")
        indexed_paths = set(re.findall(r'\[.*?\]\((.+?\.md)\)', text))

        existing_files = set()
        exclude = {"index.md", "log.md", "_schema.md"}
        for md in wd.rglob("*.md"):
            rel = str(md.relative_to(wd))
            if rel not in exclude and not rel.startswith("."):
                existing_files.add(rel)

        orphan_index = indexed_paths - existing_files
        unindexed = existing_files - indexed_paths

        lines = []
        if orphan_index:
            lines.append(f"Broken links in index ({len(orphan_index)}):")
            for p in sorted(orphan_index):
                lines.append(f"  - {p}")
        if unindexed:
            lines.append(f"Files not in index ({len(unindexed)}):")
            for p in sorted(unindexed):
                lines.append(f"  - {p}")
        if not lines:
            lines.append("All index entries match existing files.")
        return {"output": "\n".join(lines)}
