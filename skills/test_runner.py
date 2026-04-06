"""테스트 실행 도구 (pytest, script, list targets)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from core.tool_registry import ToolRegistry
from core.types import PermissionMode

TIMEOUT = 120


def _run_cmd(workspace: str, cmd: list[str], timeout: int = TIMEOUT) -> str:
    """Run a command with timeout, return combined output."""
    ws = Path(workspace).resolve()
    if not ws.is_dir():
        return f"Error: directory not found: {ws}"
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ws),
            capture_output=True,
            text=True,
            timeout=timeout,
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
        return f"Timed out after {timeout}s"
    except FileNotFoundError:
        return f"Error: command not found: {cmd[0]}"


def register(registry: ToolRegistry, workspace: str = ".") -> None:

    @registry.tool(
        name="run_pytest",
        description="Run pytest in the workspace. Optionally target a specific file/dir.",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the project root",
                },
                "target": {
                    "type": "string",
                    "description": "Test file or directory (relative to workspace)",
                    "default": "",
                },
                "args": {
                    "type": "string",
                    "description": "Additional pytest arguments (e.g. '-v --tb=short')",
                    "default": "",
                },
            },
            "required": ["workspace"],
        },
        permission_level=PermissionMode.FULL_ACCESS,
    )
    def run_pytest(workspace: str, target: str = "", args: str = "") -> dict:
        cmd = ["python", "-m", "pytest"]
        if target:
            cmd.append(target)
        if args:
            cmd.extend(args.split())
        return {"output": _run_cmd(workspace, cmd)}

    @registry.tool(
        name="run_script",
        description="Run a Python script in the workspace.",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the project root",
                },
                "script": {
                    "type": "string",
                    "description": "Script path (relative to workspace)",
                },
                "args": {
                    "type": "string",
                    "description": "Arguments to pass to the script",
                    "default": "",
                },
            },
            "required": ["workspace", "script"],
        },
        permission_level=PermissionMode.FULL_ACCESS,
    )
    def run_script(workspace: str, script: str, args: str = "") -> dict:
        ws = Path(workspace).resolve()
        script_path = ws / script
        if not script_path.is_file():
            return {"output": f"Error: script not found: {script}"}
        if not script.endswith(".py"):
            return {"output": "Error: only .py scripts are supported"}
        cmd = ["python", str(script_path)]
        if args:
            cmd.extend(args.split())
        return {"output": _run_cmd(workspace, cmd)}

    @registry.tool(
        name="list_test_targets",
        description="List test files in the workspace tests/ directory.",
        parameters={
            "type": "object",
            "properties": {
                "workspace": {
                    "type": "string",
                    "description": "Absolute path to the project root",
                },
            },
            "required": ["workspace"],
        },
        permission_level=PermissionMode.READ_ONLY,
    )
    def list_test_targets(workspace: str) -> dict:
        ws = Path(workspace).resolve()
        tests_dir = ws / "tests"
        if not tests_dir.is_dir():
            return {"output": "No tests/ directory found"}
        files = sorted(
            str(f.relative_to(ws))
            for f in tests_dir.rglob("*.py")
            if f.name.startswith("test_") or f.name.endswith("_test.py")
        )
        if not files:
            return {"output": "No test files found in tests/"}
        return {"output": f"Found {len(files)} test files:\n" + "\n".join(files)}
