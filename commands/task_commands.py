"""Task/Plan 관련 slash commands."""

from __future__ import annotations

from pathlib import Path

from commands import CommandRegistry
from core.planner import (
    build_plan_from_prompt,
    get_next_task,
    get_snapshot,
    summarize_active_plan,
    update_task_status,
)
from core.task_store import TaskStore
from core.tasks import TaskStatus


def register(
    registry: CommandRegistry,
    get_session=None,
    get_runtime=None,
) -> None:
    """Task 관련 명령어 등록."""

    store = TaskStore(Path(".local-claude"))

    @registry.command("plan", "Create a new plan from description")
    def cmd_plan(args: str = "", **ctx) -> str:
        if not args.strip():
            return "Usage: /plan <description>\nProvide a numbered or bulleted list of tasks."

        plan = build_plan_from_prompt(args.strip())
        store.save_active_plan(plan)

        lines = [f"Plan created: {plan.title}", f"ID: {plan.id}", ""]
        for task in plan.tasks:
            lines.append(f"  [ ] [{task.id}] {task.title}")
        lines.append(f"\nTotal: {len(plan.tasks)} tasks")
        return "\n".join(lines)

    @registry.command("tasks", "Show current plan tasks")
    def cmd_tasks(args: str = "", **ctx) -> str:
        plan = store.load_active_plan()
        if not plan:
            return "No active plan. Use /plan <description> to create one."

        snap = get_snapshot(plan)
        lines = [f"Plan: {plan.title}", f"Progress: {snap.progress}", ""]
        for task in plan.tasks:
            icon = _icon(task.status)
            suffix = ""
            if task.blocked_by:
                suffix = f" (blocked by: {', '.join(task.blocked_by)})"
            lines.append(f"  {icon} [{task.id}] {task.title}{suffix}")

        if snap.active_task:
            lines.append(f"\nNext: {snap.active_task.title}")
        return "\n".join(lines)

    @registry.command("brief", "Show active plan summary + next task")
    def cmd_brief(args: str = "", **ctx) -> str:
        plan = store.load_active_plan()
        if not plan:
            return "No active plan."
        return summarize_active_plan(plan)

    @registry.command("task-done", "Mark a task as completed")
    def cmd_task_done(args: str = "", **ctx) -> str:
        plan = store.load_active_plan()
        if not plan:
            return "No active plan."

        task_id = args.strip()

        # id가 없으면 현재 in_progress task를 완료
        if not task_id:
            for t in plan.tasks:
                if t.status == TaskStatus.IN_PROGRESS:
                    task_id = t.id
                    break
            if not task_id:
                return "No task ID provided and no in-progress task found."

        # task 존재 확인
        found = any(t.id == task_id for t in plan.tasks)
        if not found:
            return f"Task '{task_id}' not found in current plan."

        plan = update_task_status(plan, task_id, TaskStatus.COMPLETED)
        store.save_active_plan(plan)

        done_task = next(t for t in plan.tasks if t.id == task_id)
        snap = get_snapshot(plan)
        lines = [f"Completed: {done_task.title}", f"Progress: {snap.progress}"]

        next_t = get_next_task(plan)
        if next_t:
            lines.append(f"Next: {next_t.title}")
        else:
            all_done = all(t.status == TaskStatus.COMPLETED for t in plan.tasks)
            if all_done:
                lines.append("All tasks completed!")
                store.archive_plan(plan)
                lines.append("Plan archived.")
        return "\n".join(lines)

    @registry.command("task-start", "Mark a task as in-progress")
    def cmd_task_start(args: str = "", **ctx) -> str:
        plan = store.load_active_plan()
        if not plan:
            return "No active plan."

        task_id = args.strip()
        if not task_id:
            # 다음 pending task를 자동 시작
            next_t = get_next_task(plan)
            if not next_t:
                return "No pending tasks to start."
            task_id = next_t.id

        found = any(t.id == task_id for t in plan.tasks)
        if not found:
            return f"Task '{task_id}' not found."

        plan = update_task_status(plan, task_id, TaskStatus.IN_PROGRESS)
        store.save_active_plan(plan)

        task = next(t for t in plan.tasks if t.id == task_id)
        return f"Started: {task.title}"


def _icon(status: TaskStatus) -> str:
    return {
        TaskStatus.PENDING: "[ ]",
        TaskStatus.IN_PROGRESS: "[>]",
        TaskStatus.COMPLETED: "[x]",
        TaskStatus.BLOCKED: "[!]",
    }.get(status, "[ ]")
