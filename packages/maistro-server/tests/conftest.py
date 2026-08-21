"""Maistro Server — shared test fixtures."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

os.environ.setdefault("MAISTRO_DRY_RUN", "1")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "6000")
os.environ.setdefault("RATE_LIMIT_BURST", "1000")


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    from maistro.config.settings import get_settings

    get_settings.cache_clear()

    yield

    import maistro.tasks.queue as queue_module

    queue_module._queue = None

    import maistro.tools.sandbox.server as sandbox_server

    sandbox_server._containers.clear()

    import maistro.observability.tracing as tracing_module

    tracing_module._langfuse = None
    tracing_module._langfuse_checked = False

    import maistro_server.main as main_module

    main_module._runner = None


@pytest.fixture(autouse=True)
def _disable_auth_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REQUIRE_AUTH", "false")


@pytest.fixture()
def task_queue():
    from maistro.tasks.queue import TaskQueue

    return TaskQueue()


@pytest.fixture()
def mock_executor():
    from maistro.agents.types import ConductorOutput, PlanOutput, SubTask

    async def executor(task):
        return ConductorOutput(
            plan=PlanOutput(
                summary=f"[TEST] Plan for: {task.description}",
                subtasks=[SubTask(title="Test task", description=task.description)],
            ),
            final_answer=f"[TEST] Done: {task.description}",
            success=True,
        )

    return executor
