"""파일 기반 Task/Plan 저장소. .local-claude/tasks/ 디렉토리 사용."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from core.tasks import Plan


class TaskStore:
    """Plan을 JSON 파일로 저장/로드/아카이브."""

    def __init__(self, base_dir: Path):
        self._dir = base_dir / "tasks"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._history_dir = self._dir / "history"
        self._history_dir.mkdir(exist_ok=True)

    @property
    def current_path(self) -> Path:
        return self._dir / "current.json"

    def load_active_plan(self) -> Plan | None:
        path = self.current_path
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Plan.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def save_active_plan(self, plan: Plan) -> None:
        self.current_path.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def archive_plan(self, plan: Plan) -> None:
        dest = self._history_dir / f"{plan.id}.json"
        dest.write_text(
            json.dumps(plan.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if self.current_path.exists():
            self.current_path.unlink()

    def list_archived(self) -> list[str]:
        return [p.stem for p in sorted(self._history_dir.glob("*.json"))]
