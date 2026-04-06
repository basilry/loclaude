"""Task Runtime 타입 정의. Plan/Task 기반 작업 추적."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class TaskItem:
    id: str
    title: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    blocked_by: list[str] = field(default_factory=list)
    created_at: str = ""  # ISO format
    completed_at: str | None = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now_iso()

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "blocked_by": self.blocked_by,
            "created_at": self.created_at,
        }
        if self.completed_at:
            d["completed_at"] = self.completed_at
        return d

    @classmethod
    def from_dict(cls, d: dict) -> TaskItem:
        return cls(
            id=d["id"],
            title=d["title"],
            description=d.get("description", ""),
            status=TaskStatus(d.get("status", "pending")),
            blocked_by=d.get("blocked_by", []),
            created_at=d.get("created_at", ""),
            completed_at=d.get("completed_at"),
        )


@dataclass
class Plan:
    id: str
    title: str
    tasks: list[TaskItem]
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        now = _now_iso()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "tasks": [t.to_dict() for t in self.tasks],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Plan:
        return cls(
            id=d["id"],
            title=d["title"],
            tasks=[TaskItem.from_dict(t) for t in d.get("tasks", [])],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
        )


@dataclass
class TaskSnapshot:
    plan: Plan
    active_task: TaskItem | None
    progress: str  # "3/7 completed"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_task_id() -> str:
    return uuid.uuid4().hex[:8]


def make_plan_id() -> str:
    return uuid.uuid4().hex[:12]
