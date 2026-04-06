"""memvid capsule operations -- facade delegating to core/memory/ backends."""

import asyncio
from pathlib import Path

from core.memory import create_memory_backend
from core.project_paths import get_project_paths

PATHS = get_project_paths()
WIKI_DIR = PATHS.wiki_dir

_backend = None


def _get_backend():
    global _backend
    if _backend is None:
        _backend = create_memory_backend(backend="memvid", wiki_dir=WIKI_DIR)
    return _backend


def _run(coro):
    """Run async coroutine synchronously."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


# -- Public API (signatures preserved) --


def capsule_put(
    content: str,
    title: str,
    tags: list[str] | None = None,
    wiki_path: str | None = None,
) -> dict:
    """Put content into memory backend."""
    backend = _get_backend()
    _run(backend.put(
        doc_path=wiki_path or "",
        title=title,
        content=content,
        tags=tags,
    ))
    return {"status": "ok", "backend": backend.info().get("backend", "unknown"), "title": title}


def capsule_build() -> dict:
    """Rebuild memvid video from all JSON entries."""
    backend = _get_backend()
    if hasattr(backend, "build_video"):
        return _run(backend.build_video())
    return {"status": "skipped", "reason": "backend does not support video build"}


def capsule_search(
    query: str,
    mode: str = "hybrid",
    top_k: int = 5,
) -> list[dict]:
    """Search capsule. Returns list of {score, title, snippet, wiki_path, tags}."""
    backend = _get_backend()
    return _run(backend.search(query, top_k=top_k, mode=mode))


def capsule_info() -> dict:
    """Capsule statistics."""
    return _get_backend().info()


def capsule_sync_all(wiki_dir: Path | None = None) -> dict:
    """Sync all .md files -- only update changed ones."""
    backend = _get_backend()
    target = wiki_dir or WIKI_DIR
    return _run(backend.sync_all(target))
