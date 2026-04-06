"""Wiki document data models and frontmatter parsing."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class WikiFrontmatter:
    title: str = ""
    type: str = ""
    tags: list[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""


@dataclass
class WikiDocument:
    path: Path
    frontmatter: WikiFrontmatter
    content: str
    sections: list[str] = field(default_factory=list)


def parse_frontmatter(text: str) -> WikiFrontmatter:
    """Parse YAML frontmatter from markdown text."""
    fm = WikiFrontmatter()
    if not text.startswith("---"):
        return fm

    lines = text.split("\n")
    end = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = i
            break
    if end < 0:
        return fm

    for line in lines[1:end]:
        if line.startswith("title:"):
            fm.title = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("type:"):
            fm.type = line.split(":", 1)[1].strip()
        elif line.startswith("tags:"):
            raw = line.split(":", 1)[1].strip()
            match = re.findall(r"[\w./-]+", raw)
            fm.tags = match if match else []
        elif line.startswith("created:"):
            fm.created = line.split(":", 1)[1].strip()
        elif line.startswith("updated:"):
            fm.updated = line.split(":", 1)[1].strip()

    return fm


def parse_wiki_document(path: Path) -> WikiDocument:
    """Parse a wiki markdown file into a WikiDocument."""
    text = path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)

    # Strip frontmatter from content
    content = text
    if text.startswith("---"):
        lines = text.split("\n")
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                content = "\n".join(lines[i + 1:]).lstrip()
                break

    # Extract section headers
    sections = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)

    if not fm.title:
        fm.title = path.stem.replace("-", " ").replace("_", " ").title()

    return WikiDocument(
        path=path,
        frontmatter=fm,
        content=content,
        sections=sections,
    )


def render_frontmatter(frontmatter: WikiFrontmatter) -> str:
    """Render WikiFrontmatter as a YAML frontmatter string with --- delimiters."""
    lines = ["---"]
    lines.append(f"title: {frontmatter.title}")
    lines.append(f"type: {frontmatter.type}")
    lines.append(f"tags: {json.dumps(frontmatter.tags)}")
    if frontmatter.created:
        lines.append(f"created: {frontmatter.created}")
    if frontmatter.updated:
        lines.append(f"updated: {frontmatter.updated}")
    lines.append("---")
    return "\n".join(lines)


def render_wiki_document(doc: WikiDocument) -> str:
    """Render full canonical markdown: frontmatter + content."""
    fm_str = render_frontmatter(doc.frontmatter)
    return f"{fm_str}\n\n{doc.content}"


def build_wiki_document(
    path: Path,
    *,
    title: str,
    doc_type: str,
    tags: list[str],
    content: str,
) -> WikiDocument:
    """Factory for creating WikiDocument with proper frontmatter."""
    now = datetime.now().strftime("%Y-%m-%d")
    fm = WikiFrontmatter(
        title=title,
        type=doc_type,
        tags=tags,
        created=now,
        updated=now,
    )
    sections = re.findall(r"^#{1,3}\s+(.+)$", content, re.MULTILINE)
    return WikiDocument(path=path, frontmatter=fm, content=content, sections=sections)
