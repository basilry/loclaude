"""Worker 타입 정의 -- Coordinator가 task를 할당하고 결과를 수집하는 단위."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExecutionMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"  # 향후 확장


@dataclass
class WorkerAssignment:
    task_id: str
    task_description: str
    agent_profile: str | None = None
    priority: int = 0


@dataclass
class WorkerOutput:
    task_id: str
    success: bool
    output: str
    duration_ms: float
    error: str | None = None

    def to_dict(self) -> dict:
        d = {
            "task_id": self.task_id,
            "success": self.success,
            "output": self.output,
            "duration_ms": self.duration_ms,
        }
        if self.error:
            d["error"] = self.error
        return d
