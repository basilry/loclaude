"""Wiki log.md append utility."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def append_log_entry(log_path: Path, action: str, target: str, summary: str) -> None:
    """Append a timestamped entry to log.md.

    Format: - YYYY-MM-DD HH:MM | action | target | summary
    """
    if not log_path.exists():
        return

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"- {now} | {action} | {target} | {summary}"
    text = log_path.read_text(encoding="utf-8").rstrip() + "\n" + entry + "\n"
    log_path.write_text(text, encoding="utf-8")
