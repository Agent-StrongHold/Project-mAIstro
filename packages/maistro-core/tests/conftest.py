"""Shared test fixtures and configuration."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

# Force dry-run mode in tests to avoid real LLM calls
os.environ.setdefault("MAISTRO_DRY_RUN", "1")

# High rate limits in tests to avoid 429s. Both sit above their declared
# security floor (SPEC-082226-2a10), so the suite has to say out loud that it is
# an unsafe/dev configuration — which is exactly what the override is for. Set
# before the limits so `Settings` never sees a weakened value without it.
os.environ.setdefault("ALLOW_UNSAFE_RESOURCE_OVERRIDES", "true")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "6000")
os.environ.setdefault("RATE_LIMIT_BURST", "1000")


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    """Reset all global singletons between tests to prevent state leakage."""
    # Clear cached settings so test env vars are picked up
    from maistro.config.settings import get_settings

    get_settings.cache_clear()

    yield

    # Task queue
    import maistro.tasks.queue as queue_module

    queue_module._queue = None

    # Sandbox containers
    import maistro.tools.sandbox.server as sandbox_server

    sandbox_server._containers.clear()

    # Langfuse tracing
    import maistro.observability.tracing as tracing_module

    tracing_module._langfuse = None
    tracing_module._langfuse_checked = False

    pass


@pytest.fixture(autouse=True)
def _disable_auth_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable auth requirement for tests (unless test explicitly configures it)."""
    monkeypatch.setenv("REQUIRE_AUTH", "false")


@pytest.fixture()
def task_queue():
    """Create a fresh TaskQueue instance for testing."""
    from maistro.tasks.queue import TaskQueue

    return TaskQueue()


@pytest.fixture()
def mock_executor():
    """Create a mock task executor that returns dry-run results."""
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


@pytest.fixture(autouse=True)
def _reset_shared_http() -> Iterator[None]:
    """Drop any test transport override and pooled clients between tests.

    A leaked override would silently route a later test's requests into an
    unrelated MockTransport — the kind of cross-test coupling that shows up as
    an unrelated failure days later.
    """
    from maistro.http import set_test_transport

    yield
    set_test_transport(None)
