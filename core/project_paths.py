"""Project-local path helpers for internal and config data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    config_dir: Path
    internal_dir: Path
    wiki_dir: Path
    raw_dir: Path
    sessions_dir: Path
    exports_dir: Path
    tasks_dir: Path


def get_project_paths(project_root: str | Path | None = None) -> ProjectPaths:
    root = Path(project_root).resolve() if project_root else Path(__file__).resolve().parent.parent
    internal_dir = root / ".internal"
    config_dir = root / ".local-claude"
    return ProjectPaths(
        root=root,
        config_dir=config_dir,
        internal_dir=internal_dir,
        wiki_dir=internal_dir / "wiki",
        raw_dir=internal_dir / "raw",
        sessions_dir=internal_dir / "sessions",
        exports_dir=root / "exports",
        tasks_dir=config_dir / "tasks",
    )
