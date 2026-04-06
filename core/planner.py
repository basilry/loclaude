"""Plan 생성 및 관리. 프롬프트에서 task 목록을 추출하고 상태를 관리."""

from __future__ import annotations

import re

from core.tasks import (
    Plan, TaskItem, TaskSnapshot, TaskStatus,
    make_plan_id, make_task_id, _now_iso,
)


def build_plan_from_prompt(prompt: str, title: str | None = None) -> Plan:
    """프롬프트 텍스트에서 task 목록 추출.

    지원 포맷:
      - 번호 목록: "1. ...", "2) ..."
      - 불릿 목록: "- ...", "* ..."
    한 줄에 하나의 task.
    """
    tasks: list[TaskItem] = []
    lines = prompt.strip().splitlines()

    plan_title = title or ""
    task_lines: list[str] = []
    plain_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 번호 목록: "1. ", "1) ", "01. "
        m_num = re.match(r"^\d+[.)]\s+(.+)", stripped)
        # 불릿 목록: "- ", "* "
        m_bul = re.match(r"^[-*]\s+(.+)", stripped)

        if m_num:
            task_lines.append(m_num.group(1).strip())
        elif m_bul:
            task_lines.append(m_bul.group(1).strip())
        else:
            plain_lines.append(stripped)

    # title: 명시적 title > 첫 번째 plain line > 첫 task에서 유도
    if not plan_title and plain_lines:
        plan_title = plain_lines.pop(0)
    if not plan_title and task_lines:
        plan_title = "Plan"

    # plain_lines 중 남은 것도 task로 추가
    all_task_texts = task_lines + plain_lines

    for text in all_task_texts:
        tasks.append(TaskItem(
            id=make_task_id(),
            title=text,
            description="",
        ))

    # task가 없으면 전체 프롬프트를 단일 task로
    if not tasks:
        tasks.append(TaskItem(
            id=make_task_id(),
            title=plan_title or prompt[:80],
            description=prompt,
        ))

    return Plan(
        id=make_plan_id(),
        title=plan_title or "Untitled Plan",
        tasks=tasks,
    )


def update_task_status(plan: Plan, task_id: str, status: TaskStatus) -> Plan:
    """task 상태 업데이트. completed이면 completed_at 기록."""
    for task in plan.tasks:
        if task.id == task_id:
            task.status = status
            if status == TaskStatus.COMPLETED:
                task.completed_at = _now_iso()
            plan.updated_at = _now_iso()
            break
    return plan


def get_next_task(plan: Plan) -> TaskItem | None:
    """다음 실행할 pending task 반환. blocked_by가 모두 완료된 것만."""
    completed_ids = {t.id for t in plan.tasks if t.status == TaskStatus.COMPLETED}
    for task in plan.tasks:
        if task.status == TaskStatus.PENDING:
            if all(bid in completed_ids for bid in task.blocked_by):
                return task
    return None


def get_active_task(plan: Plan) -> TaskItem | None:
    """현재 in_progress인 task 반환."""
    for task in plan.tasks:
        if task.status == TaskStatus.IN_PROGRESS:
            return task
    return None


def get_snapshot(plan: Plan) -> TaskSnapshot:
    """현재 plan 상태 스냅샷."""
    completed = sum(1 for t in plan.tasks if t.status == TaskStatus.COMPLETED)
    total = len(plan.tasks)
    active = get_active_task(plan) or get_next_task(plan)
    return TaskSnapshot(
        plan=plan,
        active_task=active,
        progress=f"{completed}/{total} completed",
    )


def summarize_active_plan(plan: Plan) -> str:
    """system prompt 주입용 plan 요약 텍스트."""
    snap = get_snapshot(plan)
    lines = [
        f"## Active Plan: {plan.title}",
        f"Progress: {snap.progress}",
        "",
    ]
    for task in plan.tasks:
        icon = _status_icon(task.status)
        lines.append(f"  {icon} [{task.id}] {task.title}")

    if snap.active_task:
        lines.append(f"\nCurrent focus: {snap.active_task.title}")

    return "\n".join(lines)


def _status_icon(status: TaskStatus) -> str:
    return {
        TaskStatus.PENDING: "[ ]",
        TaskStatus.IN_PROGRESS: "[>]",
        TaskStatus.COMPLETED: "[x]",
        TaskStatus.BLOCKED: "[!]",
    }.get(status, "[ ]")
