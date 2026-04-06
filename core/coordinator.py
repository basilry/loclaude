"""Coordinator -- Plan의 task들을 순차 실행하고 결과를 병합."""

from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field

from core.engines.base import EngineProtocol
from core.types import Message, Role
from core.workers import WorkerAssignment, WorkerOutput

logger = logging.getLogger(__name__)

# Plan/AgentProfile은 Phase 4 구현 전이므로 가벼운 타입 별칭 사용
Plan = list[dict]  # [{"task_id": str, "description": str}, ...]
AgentProfile = dict  # {"name": str, "system_prompt": str}


@dataclass
class CoordinatorConfig:
    max_workers: int = 1  # 초기는 sequential
    timeout_sec: float = 300.0
    temperature: float = 0.7
    max_tokens: int = 4096


class Coordinator:
    """Plan의 task들을 engine으로 순차 실행하고 결과를 수집한다."""

    def __init__(
        self,
        engine: EngineProtocol,
        config: CoordinatorConfig | None = None,
    ):
        self.engine = engine
        self.config = config or CoordinatorConfig()

    async def dispatch_plan(
        self,
        plan: Plan,
        profiles: list[AgentProfile] | None = None,
    ) -> list[WorkerOutput]:
        """Plan의 task들을 순차 실행. 각 task를 engine으로 처리."""
        outputs: list[WorkerOutput] = []
        profile_map = {}
        if profiles:
            profile_map = {p["name"]: p for p in profiles}

        for task in plan:
            task_id = task.get("task_id", "unknown")
            description = task.get("description", "")
            agent_name = task.get("agent", None)

            system_prompt = None
            if agent_name and agent_name in profile_map:
                system_prompt = profile_map[agent_name].get("system_prompt")

            output = await self._execute_task(
                task_id=task_id,
                description=description,
                system_prompt=system_prompt,
            )
            outputs.append(output)

        return outputs

    async def dispatch_single(self, task_description: str) -> WorkerOutput:
        """단일 task 실행."""
        return await self._execute_task(
            task_id="single",
            description=task_description,
        )

    def merge_outputs(self, outputs: list[WorkerOutput]) -> str:
        """여러 worker 출력을 하나의 요약으로 병합."""
        parts: list[str] = []
        for out in outputs:
            status = "OK" if out.success else "FAIL"
            header = f"## Task {out.task_id} [{status}] ({out.duration_ms:.0f}ms)"
            body = out.output if out.success else (out.error or "unknown error")
            parts.append(f"{header}\n{body}")
        return "\n\n".join(parts)

    async def _execute_task(
        self,
        task_id: str,
        description: str,
        system_prompt: str | None = None,
    ) -> WorkerOutput:
        """단일 task를 engine.chat()으로 실행."""
        messages = [Message(role=Role.USER, content=description)]
        start = time.monotonic()
        try:
            content, _usage = await self.engine.chat(
                messages,
                system=system_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            duration_ms = (time.monotonic() - start) * 1000
            return WorkerOutput(
                task_id=task_id,
                success=True,
                output=content,
                duration_ms=duration_ms,
            )
        except Exception as e:
            duration_ms = (time.monotonic() - start) * 1000
            logger.error("Task %s failed: %s", task_id, e)
            return WorkerOutput(
                task_id=task_id,
                success=False,
                output="",
                duration_ms=duration_ms,
                error=str(e),
            )
