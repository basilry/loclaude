"""Runtime bootstrap -- CLI entrypoint에서 사용할 컴포넌트 조립."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from core.config import ProjectConfig, load_config
from core.engines.base import EngineProtocol
from core.engines.factory import create_engine
from core.hooks import HookRunner
from core.project_paths import ProjectPaths, get_project_paths
from core.runtime import ConversationRuntime
from core.session import Session
from core.settings import RuntimeSettings, load_settings, resolve_api_key
from core.task_store import TaskStore
from core.tool_registry import ToolRegistry
from core.types import PermissionMode
from commands import CommandRegistry
from commands.builtins import register as register_builtins
from commands.task_commands import register as register_task_commands
from core.tool_groups import build_default_tool_groups
from skills import file_ops, bash_exec, search, web_fetch, git_ops, test_runner, wiki_ops


@dataclass
class RuntimeBundle:
    engine: EngineProtocol
    tools: ToolRegistry
    commands: CommandRegistry
    session: Session
    runtime: ConversationRuntime
    paths: ProjectPaths
    project_config: ProjectConfig
    settings: RuntimeSettings


def build_runtime_settings(args: argparse.Namespace, workspace: str) -> RuntimeSettings:
    settings = load_settings(args)
    if not settings.workspace:
        object.__setattr__(settings, "workspace", workspace) if hasattr(settings, "__dataclass_fields__") else setattr(settings, "workspace", workspace)
    return settings


def build_engine(settings: RuntimeSettings) -> EngineProtocol:
    api_key = resolve_api_key(getattr(settings, "api_key_env", "")) if hasattr(settings, "api_key_env") else None
    return create_engine(
        provider=settings.provider,
        model=settings.model,
        base_url=settings.base_url,
        api_key=api_key,
    )


def build_session(paths: ProjectPaths) -> Session:
    return Session(session_dir=paths.sessions_dir)


def build_tool_registry(workspace: str) -> ToolRegistry:
    registry = ToolRegistry()
    file_ops.register(registry, workspace)
    bash_exec.register(registry, workspace)
    search.register(registry, workspace)
    web_fetch.register(registry)
    git_ops.register(registry, workspace)
    test_runner.register(registry, workspace)
    wiki_ops.register(registry, workspace)
    for group in build_default_tool_groups():
        registry.register_group(group)
    return registry


def build_task_store(workspace: str) -> TaskStore:
    return TaskStore.for_workspace(workspace)


def build_command_registry(get_session, get_runtime, store: TaskStore) -> CommandRegistry:
    registry = CommandRegistry()
    register_builtins(registry, get_session=get_session, get_runtime=get_runtime)
    register_task_commands(registry, get_session=get_session, get_runtime=get_runtime, store=store)
    return registry


def build_runtime_bundle(args: argparse.Namespace, workspace: str) -> RuntimeBundle:
    settings = build_runtime_settings(args, workspace)
    paths = get_project_paths(workspace)
    engine = build_engine(settings)
    project_config = load_config(workspace)
    tools = build_tool_registry(workspace)
    hooks = HookRunner()
    session = build_session(paths)
    store = build_task_store(workspace)

    # Load active plan at boot so runtime has plan context
    active_plan = store.load_active_plan()

    runtime = ConversationRuntime(
        engine=engine,
        tools=tools,
        hooks=hooks,
        session=session,
        permission_mode=settings.permission,
        project_config=project_config,
        plan=active_plan,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
    )

    commands = build_command_registry(
        get_session=lambda: runtime.session,
        get_runtime=lambda: runtime,
        store=store,
    )

    return RuntimeBundle(
        engine=engine,
        tools=tools,
        commands=commands,
        session=session,
        runtime=runtime,
        paths=paths,
        project_config=project_config,
        settings=settings,
    )
