"""Wiki pipeline integration tests."""

import os
import json
import pytest
import tempfile
import shutil
import sys
from pathlib import Path

# Project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from skills.memvid_ops import capsule_put, capsule_search, capsule_info, capsule_sync_all


@pytest.fixture(autouse=True)
def isolated_wiki(tmp_path, monkeypatch):
    """Redirect WIKI_DIR, STUB_PATH to temp directory for each test."""
    import skills.memvid_ops as ops

    wiki_dir = tmp_path / "wiki"
    wiki_dir.mkdir()
    stub_path = wiki_dir / "memory.json"

    monkeypatch.setattr(ops, "WIKI_DIR", wiki_dir)
    monkeypatch.setattr(ops, "STUB_PATH", stub_path)
    monkeypatch.setattr(ops, "VIDEO_PATH", wiki_dir / "memory.mp4")
    monkeypatch.setattr(ops, "INDEX_PATH", wiki_dir / "memory_index.json")

    yield wiki_dir


def _make_doc(wiki_dir: Path, rel_path: str, title: str, doc_type: str = "concept", body: str = "") -> Path:
    """Helper: create a wiki .md file with frontmatter."""
    full = wiki_dir / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    content = (
        f"---\ntitle: \"{title}\"\ntype: {doc_type}\n"
        f"tags: [test]\ncreated: 2026-04-05\n---\n\n{body or title + ' content.'}\n"
    )
    full.write_text(content, encoding="utf-8")
    return full


def _make_index(wiki_dir: Path, entries: list[tuple[str, str]]) -> Path:
    """Helper: create index.md with given entries."""
    lines = ["# Test Wiki\n\n## Concepts\n"]
    for title, path in entries:
        lines.append(f"- [{title}]({path})")
    lines.append("\n## References\n\n## Queries\n")
    index = wiki_dir / "index.md"
    index.write_text("\n".join(lines), encoding="utf-8")
    return index


class TestCapsulePutAndSearch:
    def test_put_then_search(self, isolated_wiki):
        """capsule_put -> capsule_search finds the document."""
        capsule_put(
            content="Python asyncio event loop tutorial for beginners",
            title="Asyncio Tutorial",
            tags=["python", "async"],
            wiki_path="wiki/concepts/asyncio.md",
        )
        results = capsule_search("asyncio event loop", top_k=5)
        assert len(results) > 0
        assert any("Asyncio" in r.get("title", "") for r in results)

    def test_put_deduplicates(self, isolated_wiki):
        """Putting same title twice keeps only one entry."""
        capsule_put(content="v1", title="Dedup Test", tags=["test"])
        capsule_put(content="v2 updated", title="Dedup Test", tags=["test"])
        info = capsule_info()
        assert info["doc_count"] == 1

    def test_search_no_match(self, isolated_wiki):
        """Search with no matching content returns empty."""
        capsule_put(content="hello world", title="Greeting")
        results = capsule_search("quantum physics")
        assert results == []


class TestCapsuleSyncAll:
    def test_sync_detects_changes(self, isolated_wiki):
        """Wiki doc changes -> capsule_sync_all updates capsule."""
        doc = _make_doc(isolated_wiki, "concepts/test-sync.md", "Sync Test", body="original content")

        # Initial sync
        result = capsule_sync_all(isolated_wiki)
        assert result["synced"] > 0

        # Modify doc
        doc.write_text(doc.read_text(encoding="utf-8") + "\nUpdated.", encoding="utf-8")

        # Re-sync: should detect change
        result = capsule_sync_all(isolated_wiki)
        assert result["synced"] >= 1

    def test_sync_skips_unchanged(self, isolated_wiki):
        """Unchanged files are skipped on re-sync."""
        _make_doc(isolated_wiki, "concepts/stable.md", "Stable Doc")
        capsule_sync_all(isolated_wiki)

        result = capsule_sync_all(isolated_wiki)
        assert result["skipped"] >= 1
        assert result["synced"] == 0


class TestCapsuleInfo:
    def test_info_has_doc_count(self, isolated_wiki):
        """capsule_info returns doc_count > 0 after put."""
        capsule_put(content="test", title="Info Test")
        info = capsule_info()
        assert info["doc_count"] > 0
        assert "backend" in info

    def test_info_empty(self, isolated_wiki):
        """Empty capsule returns doc_count == 0."""
        info = capsule_info()
        assert info["doc_count"] == 0


class TestIngestManual:
    def test_ingest_manual_creates_wiki_doc(self, isolated_wiki, monkeypatch):
        """Simulate /ingest --manual: raw file -> wiki/references/."""
        from commands import CommandRegistry
        from commands.builtins import register

        # Patch project root resolution
        project_root = isolated_wiki.parent
        wiki_dir = project_root / "wiki"
        wiki_dir.mkdir(exist_ok=True)

        # Create index.md and log.md
        index = wiki_dir / "index.md"
        index.write_text("# Wiki\n\n## References\n\n## Queries\n", encoding="utf-8")
        log = wiki_dir / "log.md"
        log.write_text("# Log\n\n| Date | Action | Target | Summary |\n|---|---|---|---|\n", encoding="utf-8")

        # Create raw file
        raw_dir = project_root / "raw"
        raw_dir.mkdir(exist_ok=True)
        raw_file = raw_dir / "test-doc.md"
        raw_file.write_text("---\ntitle: Test Raw Doc\n---\n\nSome raw content.\n", encoding="utf-8")

        # Patch Path(__file__).parent.parent in builtins
        import commands.builtins as builtins_mod
        original_file = builtins_mod.__file__
        # We need the ingest command to resolve project_root correctly
        # Monkey-patch approach: override __file__ resolution
        monkeypatch.setattr(builtins_mod, "__file__", str(wiki_dir.parent / "commands" / "builtins.py"))

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("ingest", f"raw/test-doc.md --manual"))

        assert "Ingested" in result
        # Check wiki/references/ has a file
        refs = list((wiki_dir / "references").glob("*.md"))
        assert len(refs) >= 1

    @pytest.mark.skipif(
        not os.environ.get("TEST_WITH_LLM"),
        reason="LLM-assisted ingest requires TEST_WITH_LLM=1",
    )
    def test_ingest_llm(self):
        """LLM-assisted ingest (skipped without LLM)."""
        pass


class TestLintDetectsOrphan:
    def test_orphan_detection(self, isolated_wiki, monkeypatch):
        """Create doc not in index -> /lint reports orphan."""
        import commands.builtins as builtins_mod
        monkeypatch.setattr(builtins_mod, "__file__", str(isolated_wiki.parent / "commands" / "builtins.py"))

        # Create index with one entry
        _make_index(isolated_wiki, [("Listed Doc", "concepts/listed.md")])
        _make_doc(isolated_wiki, "concepts/listed.md", "Listed Doc")

        # Create orphan (not in index)
        _make_doc(isolated_wiki, "concepts/orphan.md", "Orphan Doc")

        from commands import CommandRegistry
        from commands.builtins import register

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("lint"))

        assert "orphan" in result.lower() or "Not in index" in result
        assert "orphan.md" in result


class TestWikiStatus:
    def test_status_shows_doc_count(self, isolated_wiki, monkeypatch):
        """/wiki-status output includes document count."""
        import commands.builtins as builtins_mod
        import skills.memvid_ops as ops

        monkeypatch.setattr(builtins_mod, "__file__", str(isolated_wiki.parent / "commands" / "builtins.py"))

        _make_doc(isolated_wiki, "concepts/doc1.md", "Doc One")
        _make_doc(isolated_wiki, "concepts/doc2.md", "Doc Two")

        from commands import CommandRegistry
        from commands.builtins import register

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("wiki-status"))

        assert "Documents:" in result or "documents" in result.lower()
        assert "2" in result


class TestWikiExport:
    def test_export_mv2(self, isolated_wiki, monkeypatch):
        """/wiki-export --format mv2 copies capsule files."""
        import commands.builtins as builtins_mod
        monkeypatch.setattr(builtins_mod, "__file__", str(isolated_wiki.parent / "commands" / "builtins.py"))

        # Create a stub capsule file
        capsule_stub = isolated_wiki / "memory.json"
        capsule_stub.write_text('{"entries": []}', encoding="utf-8")

        from commands import CommandRegistry
        from commands.builtins import register

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("wiki-export", "--format mv2"))

        assert "Exported" in result
        exports_dir = isolated_wiki.parent / "exports" / "mv2"
        assert exports_dir.exists()

    def test_export_md_bundle(self, isolated_wiki, monkeypatch):
        """/wiki-export --format md-bundle creates tar.gz."""
        import commands.builtins as builtins_mod
        monkeypatch.setattr(builtins_mod, "__file__", str(isolated_wiki.parent / "commands" / "builtins.py"))

        _make_doc(isolated_wiki, "concepts/test.md", "Test")

        from commands import CommandRegistry
        from commands.builtins import register

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("wiki-export", "--format md-bundle"))

        assert "Exported" in result
        assert ".tar.gz" in result

    def test_export_html(self, isolated_wiki, monkeypatch):
        """/wiki-export --format html generates HTML files."""
        import commands.builtins as builtins_mod
        monkeypatch.setattr(builtins_mod, "__file__", str(isolated_wiki.parent / "commands" / "builtins.py"))

        _make_doc(isolated_wiki, "concepts/test.md", "Test HTML")

        from commands import CommandRegistry
        from commands.builtins import register

        cmds = CommandRegistry()
        register(cmds)

        import asyncio
        result = asyncio.run(cmds.execute("wiki-export", "--format html"))

        assert "Exported" in result
        exports_html = isolated_wiki.parent / "exports" / "html"
        assert exports_html.exists()
        # Find the index.html
        index_files = list(exports_html.rglob("index.html"))
        assert len(index_files) >= 1
