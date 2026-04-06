"""MemoryBackend protocol -- all memory backends must implement this."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    """Memory backend common protocol."""

    async def put(
        self,
        doc_path: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> bool:
        """Store or update a document. Returns True on success."""
        ...

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
    ) -> list[dict]:
        """Search for documents. Returns list of {score, title, snippet, wiki_path, tags}."""
        ...

    def info(self) -> dict:
        """Return backend statistics (doc_count, file_size_mb, backend, etc.)."""
        ...

    async def sync_all(self, wiki_dir: Path) -> dict:
        """Sync all .md files from wiki_dir into the backend. Returns {synced, skipped, total}."""
        ...
