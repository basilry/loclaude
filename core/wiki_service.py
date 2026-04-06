"""Wiki directory structure and index/log management."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path


def ensure_wiki_structure(paths: dict[str, Path]) -> None:
    """Create wiki directory structure if missing.

    Args:
        paths: mapping with at least "wiki_dir" key.
    """
    wiki_dir = paths["wiki_dir"]
    for sub in ("concepts", "guides", "references", "queries"):
        (wiki_dir / sub).mkdir(parents=True, exist_ok=True)

    index = wiki_dir / "index.md"
    if not index.exists():
        index.write_text(
            "# Wiki Index\n\n## Concepts\n\n## Guides\n\n## References\n\n## Queries\n",
            encoding="utf-8",
        )

    log = wiki_dir / "log.md"
    if not log.exists():
        log.write_text(
            "# Wiki Log\n\n| Date | Action | Target | Summary |\n|------|--------|--------|---------|\n",
            encoding="utf-8",
        )


def update_wiki_index(wiki_dir: Path, section: str, title: str, rel_path: str) -> None:
    """Add an entry to index.md under the given section header.

    Args:
        wiki_dir: wiki root directory
        section: section name without "## " prefix (e.g. "References")
        title: display title for the link
        rel_path: path relative to wiki_dir
    """
    index = wiki_dir / "index.md"
    if not index.exists():
        return

    text = index.read_text(encoding="utf-8")
    entry = f"- [{title}]({rel_path})"
    if entry in text:
        return

    header = f"## {section}\n"
    if header in text:
        text = text.replace(header, f"{header}\n{entry}\n")
    else:
        text = text.rstrip() + f"\n\n{header}\n{entry}\n"
    index.write_text(text, encoding="utf-8")


def append_wiki_log(wiki_dir: Path, action: str, target: str, summary: str) -> None:
    """Append a row to log.md."""
    log = wiki_dir / "log.md"
    if not log.exists():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    entry = f"| {today} | {action} | {target} | {summary} |"
    text = log.read_text(encoding="utf-8").rstrip() + "\n" + entry + "\n"
    log.write_text(text, encoding="utf-8")


def sync_wiki_state(wiki_dir: Path) -> dict:
    """Ensure index, log, and memory.json are consistent.

    Returns dict with counts of fixes applied.
    """
    fixes = {"index_added": 0, "log_ok": False, "memory_ok": False}

    # 1. Ensure all .md files are in index
    index = wiki_dir / "index.md"
    exclude = {"_schema.md", "log.md", "index.md"}
    if index.exists():
        text = index.read_text(encoding="utf-8")
        linked = set(re.findall(r'\[.*?\]\((.+?\.md)\)', text))

        for md in wiki_dir.rglob("*.md"):
            rel = str(md.relative_to(wiki_dir))
            if rel in exclude or rel.startswith("."):
                continue
            if rel not in linked:
                section = _guess_section(rel)
                title = md.stem.replace("-", " ").replace("_", " ").title()
                entry = f"- [{title}]({rel})"
                header = f"## {section}\n"
                if header in text:
                    text = text.replace(header, f"{header}\n{entry}\n")
                else:
                    text = text.rstrip() + f"\n\n## {section}\n\n{entry}\n"
                fixes["index_added"] += 1

        if fixes["index_added"]:
            index.write_text(text, encoding="utf-8")

    # 2. Verify log exists
    fixes["log_ok"] = (wiki_dir / "log.md").exists()

    # 3. Verify memory.json exists
    fixes["memory_ok"] = (wiki_dir / "memory.json").exists()

    return fixes


def _guess_section(rel_path: str) -> str:
    if rel_path.startswith("concepts/"):
        return "Concepts"
    if rel_path.startswith("guides/"):
        return "Guides"
    if rel_path.startswith("queries/"):
        return "Queries"
    return "References"
