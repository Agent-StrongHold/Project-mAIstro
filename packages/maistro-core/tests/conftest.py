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


# ── a real PostgreSQL for the suites that want one ────────────────
#
# Lives here rather than in `tests/persistence/` because two suites need it —
# the persistence conformance tests (#122) and the execution-spine conformance
# tests (#132) — and pytest fixtures do not cross sibling directories.
# Duplicating it would be two definitions of "an isolated database", which is
# the kind of drift the conformance suites exist to catch.

#: Tables those suites write to, truncated between tests. Listed rather than
#: discovered: truncating everything would take out the alembic version table
#: and make a migrated database look unmigrated.
_PG_SCRATCH_TABLES = (
    "quota_usage",
    "sessions",
    "audit_log",
    "learnings",
    "outcomes",
    "prompts",
    "prompt_labels",
    "canonical_attempts",
    "canonical_node_runs",
    "canonical_runs",
    "canonical_project_resources",
    "canonical_project_memberships",
    "canonical_projects",
    "security_violations",
    "security_strikes",
    "security_rate_limits",
    "handler_invocations",
    "trigger_definitions",
    "event_log",
    "schedules",
    "graph_templates",
    "graph_continuations",
    # (#563) Absent from this list, rows survived between runs — and these
    # suites derive deterministic ids from their test names, so a later run
    # read a previous run's row. A regression that stopped `put` writing would
    # have been masked by data the fixture never cleared.
    "node_templates",
)


@pytest.fixture
async def pg_pool():
    """An asyncpg pool on a migrated database, truncated before each test.

    Yields ``None`` rather than skipping when no server is configured, so a
    parametrized fixture can request it unconditionally and skip only its
    PostgreSQL parametrization. Skipping here would take the whole suite with it.

    Built directly rather than through `maistro.persistence.get_pool`, which is a
    process singleton: one test's pool would outlive it and be handed to the
    next, along with whatever event loop it was created on.
    """
    from maistro.testing.postgres import postgres_dsn

    dsn = postgres_dsn()
    if not dsn:
        yield None
        return
    asyncpg = pytest.importorskip("asyncpg")

    from maistro.persistence import _register_json_codecs

    # The same codec registration the production pool uses; a test pool without
    # it would exercise a different connection than the one that ships.
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=8, init=_register_json_codecs)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE {} RESTART IDENTITY CASCADE".format(", ".join(_PG_SCRATCH_TABLES))
            )
        yield pool
    finally:
        await pool.close()
