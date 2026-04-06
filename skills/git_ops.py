"""Git 조작 도구 (status, diff, show)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.tool_registry import ToolRegistry
from core.types import PermissionMode

TIMEOUT = 30


def _run_git(workspace: str, *args: str) -> str:
    """Run a git command and return combined output."""
    ws = Path(workspace).resolve()
    if not (ws / ".git").exists() and not (ws / ".git").is_file():
        return f"Error: {ws} is not a git repository"
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            out += f"\n[exit code: {result.returncode}]"
        out = out.strip()
        if len(out) > 10000:
            out = out[:5000] + "\n...(truncated)...\n" + out[-3000:]
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {TIMEOUT}s"
    except FileNotFoundError:
        return "Error: git not found in PATH"


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="git_status",
        description="Show git working tree status (git status).",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the git repository",
                },
            },
            "required": ["workspace"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def git_status(workspace: str) -> dict:
        return {"output": _run_git(workspace, "status")}

    @registry.tool(
        name="git_diff",
        description="Show git diff. Use staged=true for --staged.",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the git repository",
                },
                "staged": {
                    "type": "boolean",
                    "description": "Show staged changes only",
                    "default": False,
                },
            },
            "required": ["workspace"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def git_diff(workspace: str, staged: bool = False) -> dict:
        args = ["diff", "--staged"] if staged else ["diff"]
        return {"output": _run_git(workspace, *args)}

    @registry.tool(
        name="git_show",
        description="Show git object (commit, tag, etc). Defaults to HEAD.",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the git repository",
                },
                "ref": {
                    "type": "string",
                    "description": "Git ref to show (default: HEAD)",
                    "default": "HEAD",
                },
            },
            "required": ["workspace"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def git_show(workspace: str, ref: str = "HEAD") -> dict:
        if not ref.replace("-", "").replace("_", "").replace("/", "").replace(".", "").isalnum():
            return {"output": f"Error: invalid ref '{ref}'"}
        return {"output": _run_git(workspace, "show", ref)}
