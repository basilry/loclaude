"""Tests for wiki canonical consistency (file == memory backend)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from core.wiki_models import (
    build_wiki_document,
    parse_frontmatter,
    render_frontmatter,
    render_wiki_document,
)
from core.wiki_service import (
    _slugify,
    _resolve_wiki_path,
    ensure_wiki_structure,
    upsert_wiki_document,
)


# -- Stage 1: Canonical serializer tests --


def test_render_frontmatter():
    from core.wiki_models import WikiFrontmatter

    fm = WikiFrontmatter(
        title="Test Doc",
        type="reference",
        tags=["a", "b"],
        created="2026-01-01",
        updated="2026-01-02",
    )
    result = render_frontmatter(fm)
    assert result.startswith("---\n")
    assert result.endswith("\n---")
    assert "title: Test Doc" in result
    assert "type: reference" in result
    assert '["a", "b"]' in result


def test_render_wiki_document():
    doc = build_wiki_document(
        Path("/tmp/test.md"),
        title="Hello",
        doc_type="concept",
        tags=["x"],
        content="# Heading\n\nBody text.",
    )
    rendered = render_wiki_document(doc)
    assert rendered.startswith("---\n")
    assert "title: Hello" in rendered
    assert "type: concept" in rendered
    assert "# Heading\n\nBody text." in rendered


def test_build_wiki_document_sections():
    doc = build_wiki_document(
        Path("/tmp/test.md"),
        title="T",
        doc_type="guide",
        tags=[],
        content="# A\n\n## B\n\ntext",
    )
    assert "A" in doc.sections
    assert "B" in doc.sections


# -- Stage 2: Service facade tests --


def test_slugify():
    assert _slugify("Hello World!") == "hello-world"
    assert _slugify("---Test---") == "test"
    assert _slugify("a/b c") == "a-b-c"


def test_resolve_wiki_path(tmp_path):
    rel, absp = _resolve_wiki_path(tmp_path, "concepts", "My Title")
    assert rel == "concepts/my-title.md"
    assert absp == tmp_path / "concepts" / "my-title.md"


@pytest.fixture
def wiki_dir(tmp_path, monkeypatch):
    """Set up a temporary wiki directory."""
    wd = tmp_path / "wiki"
    wd.mkdir()
    ensure_wiki_structure({"wiki_dir": wd})
    # Patch factory at its source module so the lazy import inside upsert picks it up
    from core.memory.json_stub import JsonStubBackend
    monkeypatch.setattr(
        "core.memory.factory.create_memory_backend",
        lambda wiki_dir=None, backend="json_stub": JsonStubBackend(wd / "memory.json"),
    )
    return wd


def test_upsert_create(wiki_dir):
    result = asyncio.run(
        upsert_wiki_document(
            wiki_dir,
            title="New Doc",
            content="Some content here.",
            section="references",
            tags=["test"],
        )
    )
    assert result["action"] == "create"
    assert result["path"] == "references/new-doc.md"

    # Verify file exists and content
    file_path = wiki_dir / result["path"]
    assert file_path.exists()
    file_text = file_path.read_text(encoding="utf-8")

    # Verify frontmatter completeness
    fm = parse_frontmatter(file_text)
    assert fm.title == "New Doc"
    assert fm.type == "reference"
    assert "test" in fm.tags

    # Verify index updated
    index_text = (wiki_dir / "index.md").read_text(encoding="utf-8")
    assert "New Doc" in index_text

    # Verify log updated
    log_text = (wiki_dir / "log.md").read_text(encoding="utf-8")
    assert "new-doc" in log_text.lower() or "New Doc" in log_text

    # Verify memory hash matches file hash
    file_hash = hashlib.sha256(file_text.encode("utf-8")).hexdigest()
    assert result["hash"] == file_hash

    mem_data = json.loads((wiki_dir / "memory.json").read_text(encoding="utf-8"))
    entries = mem_data.get("entries", [])
    mem_entry = [e for e in entries if e["title"] == "New Doc"]
    assert len(mem_entry) == 1
    assert mem_entry[0]["sha256"] == file_hash


def test_upsert_update(wiki_dir):
    async def _run():
        await upsert_wiki_document(
            wiki_dir, title="Evolving", content="Version 1",
            section="guides", tags=["v1"],
        )
        return await upsert_wiki_document(
            wiki_dir, title="Evolving", content="Version 2",
            section="guides", tags=["v2"],
        )

    result = asyncio.run(_run())
    assert result["action"] == "update"

    file_path = wiki_dir / result["path"]
    file_text = file_path.read_text(encoding="utf-8")
    assert "Version 2" in file_text

    # Created date should be preserved from first write
    fm = parse_frontmatter(file_text)
    assert fm.created  # non-empty

    # Hash consistency
    file_hash = hashlib.sha256(file_text.encode("utf-8")).hexdigest()
    mem_data = json.loads((wiki_dir / "memory.json").read_text(encoding="utf-8"))
    entries = mem_data.get("entries", [])
    mem_entry = [e for e in entries if e["title"] == "Evolving"]
    assert len(mem_entry) == 1
    assert mem_entry[0]["sha256"] == file_hash


def test_canonical_consistency(wiki_dir):
    """File content must exactly equal memory backend content."""
    asyncio.run(
        upsert_wiki_document(
            wiki_dir,
            title="Canonical Test",
            content="# Test\n\nBody.",
            section="concepts",
            tags=["consistency"],
        )
    )

    file_text = (wiki_dir / "concepts" / "canonical-test.md").read_text(encoding="utf-8")
    mem_data = json.loads((wiki_dir / "memory.json").read_text(encoding="utf-8"))
    entries = mem_data.get("entries", [])
    mem_entry = [e for e in entries if e["title"] == "Canonical Test"][0]

    # The stored content in memory must be the same canonical markdown as the file
    assert mem_entry["content"] == file_text
    assert mem_entry["sha256"] == hashlib.sha256(file_text.encode("utf-8")).hexdigest()
