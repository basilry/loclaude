"""Health check utilities for /status and /doctor commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HealthCheck:
    name: str
    status: str  # "ok", "warn", "error"
    message: str = ""


@dataclass
class HealthReport:
    checks: list[HealthCheck] = field(default_factory=list)

    @property
    def summary(self) -> str:
        ok = sum(1 for c in self.checks if c.status == "ok")
        return f"{ok}/{len(self.checks)} checks passing"


def check_paths(paths: dict[str, Path]) -> list[HealthCheck]:
    """Check existence of project paths.

    Args:
        paths: mapping of label -> Path, e.g. {"Config dir": some_path}.
              If path suffix looks like a file, checks is_file(); otherwise is_dir().
    """
    results: list[HealthCheck] = []
    for label, p in paths.items():
        if p.suffix:
            exists = p.is_file()
        else:
            exists = p.is_dir()
        results.append(HealthCheck(
            name=label,
            status="ok" if exists else "warn",
            message=str(p),
        ))
    return results


async def check_engine(engine: Any) -> HealthCheck:
    """Ping engine and return health check result."""
    if engine is None:
        return HealthCheck(name="Engine", status="warn", message="unavailable")

    model = getattr(engine, "model", "unknown")
    if not hasattr(engine, "ping"):
        return HealthCheck(name="Engine", status="ok", message=f"model={model}, no ping")

    try:
        ping = await engine.ping()
        if isinstance(ping, dict):
            detail = ", ".join(f"{k}={v}" for k, v in ping.items())
        else:
            detail = f"model={model}, reachable={ping}"
        return HealthCheck(name="Engine ping", status="ok" if ping else "warn", message=detail)
    except Exception as exc:
        return HealthCheck(name="Engine ping", status="warn", message=str(exc))


def build_health_report(
    path_checks: list[HealthCheck],
    engine_check: HealthCheck | None = None,
) -> HealthReport:
    """Combine path checks and engine check into a single report."""
    checks = list(path_checks)
    if engine_check:
        checks.append(engine_check)
    return HealthReport(checks=checks)
