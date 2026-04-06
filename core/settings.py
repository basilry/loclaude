"""Runtime and provider settings."""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field

from core.types import PermissionMode


@dataclass(frozen=True)
class ProviderSettings:
    provider_name: str
    model: str
    base_url: str
    api_key_env: str = ""


@dataclass
class RuntimeSettings:
    provider: str = "mlx"
    model: str = "mlx-community/Qwen3-8B-4bit"
    base_url: str = "http://localhost:8080/v1"
    timeout: int = 120
    permission: PermissionMode = PermissionMode.FULL_ACCESS
    workspace: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


def resolve_api_key(env_name: str) -> str | None:
    """Resolve API key from environment variable. Returns None if not set."""
    if not env_name:
        return None
    return os.environ.get(env_name)


def load_settings(args: argparse.Namespace) -> RuntimeSettings:
    """Build RuntimeSettings from parsed CLI arguments."""
    return RuntimeSettings(
        provider=getattr(args, "provider", "mlx"),
        model=getattr(args, "model", RuntimeSettings.model),
        base_url=getattr(args, "base_url", RuntimeSettings.base_url),
        timeout=getattr(args, "timeout", RuntimeSettings.timeout),
        permission=PermissionMode(getattr(args, "permission", PermissionMode.FULL_ACCESS.value)),
        workspace=getattr(args, "workspace", ""),
        temperature=getattr(args, "temperature", RuntimeSettings.temperature),
        max_tokens=getattr(args, "max_tokens", RuntimeSettings.max_tokens),
    )
