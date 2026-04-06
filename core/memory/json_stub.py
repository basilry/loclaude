"""JSON file-based memory backend -- simple keyword matching, no external deps."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


class JsonStubBackend:
    """Memory backend backed by a single memory.json file."""

    def __init__(self, stub_path: Path):
        self._path = stub_path

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

        entries = self._load()
        entries = [e for e in entries if e.get("title") != title]
        entries.append({
            "title": title,
            "content": content,
            "tags": tags,
            "wiki_path": doc_path or "",
            "sha256": _sha256(content),
            "timestamp": datetime.now().isoformat(),
        })
        self._save(entries)
        return True

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "hybrid",
    ) -> list[dict]:
        entries = self._load()
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
        entries = self._load()
        size_mb = round(self._path.stat().st_size / 1024 / 1024, 2) if self._path.exists() else 0
        last_ts = max((e.get("timestamp", "") for e in entries), default="") if entries else ""
        return {
            "doc_count": len(entries),
            "file_size_mb": size_mb,
            "last_commit": last_ts,
            "backend": "json_stub",
        }

    async def sync_all(self, wiki_dir: Path) -> dict:
        md_files = sorted(wiki_dir.rglob("*.md"))
        entries = self._load()
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

    def _load(self) -> list[dict]:
        if self._path.exists():
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("entries", [])
        return []

    def _save(self, entries: list[dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"entries": entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _keyword_score(query: str, text: str) -> float:
    q_tokens = set(query.lower().split())
    t_tokens = set(text.lower().split())
    if not q_tokens:
        return 0.0
    return len(q_tokens & t_tokens) / len(q_tokens)
