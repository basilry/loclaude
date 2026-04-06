"""Wiki index.md management utilities."""

from __future__ import annotations

from pathlib import Path


def load_index(index_path: Path) -> str:
    """Read the wiki index file. Returns empty string if not found."""
    if index_path.exists():
        return index_path.read_text(encoding="utf-8")
    return ""


def add_index_entry(index_path: Path, section: str, title: str, rel_path: str) -> None:
    """Add an entry under the given section header in index.md.

    Args:
        index_path: path to index.md
        section: section name without "## " prefix (e.g. "References")
        title: display title for the link
        rel_path: path relative to wiki dir
    """
    text = load_index(index_path)
    if not text:
        return

    entry = f"- [{title}]({rel_path})"
    if entry in text:
        return

    header = f"## {section}\n"
    if header in text:
        text = text.replace(header, f"{header}\n{entry}\n")
    else:
        text = text.rstrip() + f"\n\n{header}\n{entry}\n"

    index_path.write_text(text, encoding="utf-8")


def remove_index_entry(index_path: Path, rel_path: str) -> None:
    """Remove all index entries pointing to rel_path."""
    text = load_index(index_path)
    if not text:
        return

    lines = text.split("\n")
    filtered = [line for line in lines if f"]({rel_path})" not in line]
    if len(filtered) != len(lines):
        index_path.write_text("\n".join(filtered), encoding="utf-8")
