"""memvid capsule operations. Falls back to JSON stub if memvid not installed."""

import hashlib
import json
import os
from pathlib import Path
from datetime import datetime

VIDEO_PATH = Path(__file__).parent.parent / "wiki" / "memory.mp4"
INDEX_PATH = Path(__file__).parent.parent / "wiki" / "memory_index.json"
STUB_PATH = Path(__file__).parent.parent / "wiki" / "memory.json"
WIKI_DIR = Path(__file__).parent.parent / "wiki"

try:
    from memvid import MemvidEncoder, MemvidRetriever
    HAS_MEMVID = True
except ImportError:
    HAS_MEMVID = False


def _load_stub() -> list[dict]:
    if STUB_PATH.exists():
        data = json.loads(STUB_PATH.read_text(encoding="utf-8"))
        return data.get("entries", [])
    return []


def _save_stub(entries: list[dict]) -> None:
    STUB_PATH.parent.mkdir(parents=True, exist_ok=True)
    STUB_PATH.write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _simple_score(query: str, text: str) -> float:
    """Simple keyword overlap scoring."""
    q_tokens = set(query.lower().split())
    t_tokens = set(text.lower().split())
    if not q_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)


# ── Public API ──


def capsule_put(
    content: str,
    title: str,
    tags: list[str] | None = None,
    wiki_path: str | None = None,
) -> dict:
    """Put content into JSON store. Call capsule_build() to rebuild memvid video."""
    tags = tags or []
    if wiki_path and wiki_path not in tags:
        tags.append(wiki_path)

    entries = _load_stub()
    # Remove existing entry with same title to avoid duplicates
    entries = [e for e in entries if e.get("title") != title]
    entries.append({
        "title": title,
        "content": content,
        "tags": tags,
        "wiki_path": wiki_path or "",
        "sha256": _sha256(content),
        "timestamp": datetime.now().isoformat(),
    })
    _save_stub(entries)
    return {"status": "ok", "backend": "json_stub", "title": title}


def capsule_build() -> dict:
    """Rebuild memvid video from all JSON entries. No-op if memvid not installed."""
    if not HAS_MEMVID:
        return {"status": "skipped", "reason": "memvid not installed"}

    entries = _load_stub()
    if not entries:
        return {"status": "skipped", "reason": "no entries"}

    encoder = MemvidEncoder()
    for entry in entries:
        text = f"[{entry.get('title', '')}]\n{entry.get('content', '')}"
        encoder.add_text(text, chunk_size=512, overlap=32)

    VIDEO_PATH.parent.mkdir(parents=True, exist_ok=True)
    stats = encoder.build_video(
        str(VIDEO_PATH), str(INDEX_PATH),
        codec="mp4v", show_progress=False, allow_fallback=True,
    )
    return {"status": "ok", "backend": "memvid", "entries": len(entries), **stats}


def capsule_search(
    query: str,
    mode: str = "hybrid",
    top_k: int = 5,
) -> list[dict]:
    """Search capsule. Returns list of {score, title, snippet, wiki_path, tags}."""
    # Try memvid retriever first if video exists
    if HAS_MEMVID and VIDEO_PATH.exists() and INDEX_PATH.exists():
        try:
            retriever = MemvidRetriever(str(VIDEO_PATH), str(INDEX_PATH))
            results = retriever.search_with_metadata(query, top_k=top_k)
            out = []
            for r in results:
                out.append({
                    "score": r.get("score", 0),
                    "title": r.get("text", "")[:80],
                    "snippet": r.get("text", "")[:200],
                    "wiki_path": "",
                    "tags": [],
                })
            return out
        except Exception:
            pass  # Fall through to JSON stub

    # JSON stub fallback: simple keyword matching
    entries = _load_stub()
    scored = []
    for e in entries:
        text = f"{e.get('title', '')} {e.get('content', '')}"
        score = _simple_score(query, text)
        if score > 0:
            scored.append({
                "score": round(score, 4),
                "title": e.get("title", ""),
                "snippet": e.get("content", "")[:200],
                "wiki_path": e.get("wiki_path", ""),
                "tags": e.get("tags", []),
            })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def capsule_info() -> dict:
    """Capsule statistics."""
    entries = _load_stub()
    size_mb = round(STUB_PATH.stat().st_size / 1024 / 1024, 2) if STUB_PATH.exists() else 0
    last_ts = max((e.get("timestamp", "") for e in entries), default="") if entries else ""
    info = {
        "doc_count": len(entries),
        "file_size_mb": size_mb,
        "last_commit": last_ts,
        "backend": "json_stub",
    }
    if HAS_MEMVID and VIDEO_PATH.exists():
        video_mb = round(VIDEO_PATH.stat().st_size / 1024 / 1024, 2)
        info["video_size_mb"] = video_mb
        info["backend"] = "memvid+json"
    return info


def capsule_sync_all(wiki_dir: Path | None = None) -> dict:
    """Sync all .md files -- only update changed ones (SHA256 comparison)."""
    wiki_dir = wiki_dir or WIKI_DIR
    md_files = sorted(wiki_dir.rglob("*.md"))

    entries = _load_stub()
    existing_hashes = {e["title"]: e.get("sha256", "") for e in entries}

    synced = 0
    skipped = 0
    for md_file in md_files:
        content = md_file.read_text(encoding="utf-8")
        title = md_file.stem
        # Extract title from frontmatter if present
        if content.startswith("---"):
            lines = content.split("\n")
            for line in lines[1:]:
                if line.strip() == "---":
                    break
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"').strip("'")

        content_hash = _sha256(content)
        if existing_hashes.get(title) == content_hash:
            skipped += 1
            continue

        rel_path = str(md_file.relative_to(wiki_dir.parent))
        capsule_put(
            content=content,
            title=title,
            tags=["wiki", "sync"],
            wiki_path=rel_path,
        )
        synced += 1

    return {"synced": synced, "skipped": skipped, "total": len(md_files)}
