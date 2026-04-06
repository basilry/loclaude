"""Memvid-backed memory backend -- lazy imports, graceful fallback."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


class MemvidBackend:
    """Memory backend using memvid video capsules + JSON stub fallback."""

    def __init__(self, wiki_dir: Path):
        self._wiki_dir = wiki_dir
        self._video_path = wiki_dir / "memory.mp4"
        self._index_path = wiki_dir / "memory_index.json"
        self._stub_path = wiki_dir / "memory.json"

    # -- Protocol methods --

    async def put(
        self,
        doc_path: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> bool:
        tags = tags or []
        if doc_path and doc_path not in tags:
            tags.append(doc_path)

        entries = self._load_stub()
        entries = [e for e in entries if e.get("title") != title]
        entries.append({
            "title": title,
            "content": content,
            "tags": tags,
            "wiki_path": doc_path or "",
            "sha256": _sha256(content),
            "timestamp": datetime.now().isoformat(),
        })
        self._save_stub(entries)
        return True

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
    ) -> list[dict]:
        # Try memvid retriever first
        MemvidRetriever = _get_retriever()
        if MemvidRetriever and self._video_path.exists() and self._index_path.exists():
            try:
                retriever = MemvidRetriever(str(self._video_path), str(self._index_path))
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
                pass  # fall through to stub

        # JSON stub fallback
        entries = self._load_stub()
        scored = []
        for e in entries:
            text = f"{e.get('title', '')} {e.get('content', '')}"
            score = _keyword_score(query, text)
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

    def info(self) -> dict:
        entries = self._load_stub()
        size_mb = round(self._stub_path.stat().st_size / 1024 / 1024, 2) if self._stub_path.exists() else 0
        last_ts = max((e.get("timestamp", "") for e in entries), default="") if entries else ""
        info = {
            "doc_count": len(entries),
            "file_size_mb": size_mb,
            "last_commit": last_ts,
            "backend": "json_stub",
        }
        if self._video_path.exists():
            video_mb = round(self._video_path.stat().st_size / 1024 / 1024, 2)
            info["video_size_mb"] = video_mb
            info["backend"] = "memvid+json"
        return info

    async def build_video(self) -> dict:
        """Rebuild memvid video from all JSON entries."""
        MemvidEncoder = _get_encoder()
        if not MemvidEncoder:
            return {"status": "skipped", "reason": "memvid not installed"}

        entries = self._load_stub()
        if not entries:
            return {"status": "skipped", "reason": "no entries"}

        encoder = MemvidEncoder()
        for entry in entries:
            text = f"[{entry.get('title', '')}]\n{entry.get('content', '')}"
            encoder.add_text(text, chunk_size=512, overlap=32)

        self._video_path.parent.mkdir(parents=True, exist_ok=True)
        stats = encoder.build_video(
            str(self._video_path), str(self._index_path),
            codec="mp4v", show_progress=False, allow_fallback=True,
        )
        return {"status": "ok", "backend": "memvid", "entries": len(entries), **stats}

    async def sync_all(self, wiki_dir: Path) -> dict:
        md_files = sorted(wiki_dir.rglob("*.md"))
        entries = self._load_stub()
        existing_hashes = {e["title"]: e.get("sha256", "") for e in entries}

        synced = 0
        skipped = 0
        for md_file in md_files:
            content = md_file.read_text(encoding="utf-8")
            title = md_file.stem
            if content.startswith("---"):
                for line in content.split("\n")[1:]:
                    if line.strip() == "---":
                        break
                    if line.startswith("title:"):
                        title = line.split(":", 1)[1].strip().strip('"').strip("'")

            content_hash = _sha256(content)
            if existing_hashes.get(title) == content_hash:
                skipped += 1
                continue

            rel_path = str(md_file.relative_to(wiki_dir.parent))
            await self.put(
                doc_path=rel_path,
                title=title,
                content=content,
                tags=["wiki", "sync"],
            )
            synced += 1

        return {"synced": synced, "skipped": skipped, "total": len(md_files)}

    # -- Internal helpers --

    def _load_stub(self) -> list[dict]:
        if self._stub_path.exists():
            data = json.loads(self._stub_path.read_text(encoding="utf-8"))
            return data.get("entries", [])
        return []

    def _save_stub(self, entries: list[dict]) -> None:
        self._stub_path.parent.mkdir(parents=True, exist_ok=True)
        self._stub_path.write_text(
            json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


# -- Lazy imports --

def _get_encoder():
    try:
        from memvid import MemvidEncoder
        return MemvidEncoder
    except ImportError:
        return None


def _get_retriever():
    try:
        from memvid import MemvidRetriever
        return MemvidRetriever
    except ImportError:
        return None


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keyword_score(query: str, text: str) -> float:
    q_tokens = set(query.lower().split())
    t_tokens = set(text.lower().split())
    if not q_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)
