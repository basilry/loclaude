"""Memory backend factory."""

from __future__ import annotations

from pathlib import Path

from core.memory.base import MemoryBackend
from core.memory.json_stub import JsonStubBackend


def create_memory_backend(
    backend: str = "json_stub",
    wiki_dir: Path | None = None,
) -> MemoryBackend:
    """Create a memory backend instance.

    Args:
        backend: "json_stub" or "memvid"
        wiki_dir: wiki directory path. Required for memvid, optional for json_stub.

    Returns:
        MemoryBackend implementation.
    """
    if wiki_dir is None:
        from core.project_paths import get_project_paths
        wiki_dir = get_project_paths().wiki_dir

    if backend == "json_stub":
        return JsonStubBackend(wiki_dir / "memory.json")

    if backend == "memvid":
        try:
            from core.memory.memvid_backend import MemvidBackend
            return MemvidBackend(wiki_dir)
        except Exception:
            return JsonStubBackend(wiki_dir / "memory.json")

    raise ValueError(f"Unknown memory backend: {backend!r}. Use 'json_stub' or 'memvid'.")
