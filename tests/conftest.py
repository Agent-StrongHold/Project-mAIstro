"""Shared test fixtures and configuration."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

# Force dry-run mode in tests to avoid real LLM calls
os.environ.setdefault("MAISTRO_DRY_RUN", "1")

# High rate limits in tests to avoid 429s. Both sit above their declared
# security floor (SPEC-082226-2a10), so the suite states the unsafe/dev override
# rather than being exempted from the check.
os.environ.setdefault("ALLOW_UNSAFE_RESOURCE_OVERRIDES", "true")
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "6000")
os.environ.setdefault("RATE_LIMIT_BURST", "1000")

_MUTATION_WORKFLOW = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "mutation.yml"
)
_MUTATION_DEFERRED_MARKER = (
    "Mutation testing is temporarily disabled until self-hosted runners are restored."
)
_MUTATION_ACTIVE_WORKFLOW_TESTS = {
    "tests/test_mutation_targets.py::TestPolicyPriorityIsReachable::test_every_package_source_is_in_the_workflow_scope",
    "tests/test_mutation_targets.py::TestWorkflowDiffsAgainstItsOwnBase::test_no_hardcoded_main_in_the_changed_files_diff",
    "tests/test_mutation_targets.py::TestWorkflowDiffsAgainstItsOwnBase::test_base_ref_is_passed_through_env_not_interpolated_into_shell",
    "tests/test_mutation_targets.py::TestWorkflowDiffsAgainstItsOwnBase::test_deletions_are_filtered_out_of_the_diff",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Skip active-workflow assertions only while mutation execution is explicitly deferred.

    The mutation targeting/scheduler implementation remains fully tested. These
    four assertions inspect the live GitHub workflow wiring itself, which is
    intentionally absent until self-hosted runners are restored. Removing the
    explicit marker automatically re-enables them.
    """
    if not _MUTATION_WORKFLOW.exists():
        return
    workflow = _MUTATION_WORKFLOW.read_text(encoding="utf-8")
    if _MUTATION_DEFERRED_MARKER not in workflow:
        return
    reason = "mutation workflow intentionally deferred until self-hosted runners return"
    for item in items:
        if item.nodeid in _MUTATION_ACTIVE_WORKFLOW_TESTS:
            item.add_marker(pytest.mark.skip(reason=reason))


@pytest.fixture(autouse=True)
def _default_ac_state_ratchet_event(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ratchet unit tests opt into merge-group semantics explicitly.

    A merge-group CI job exports GITHUB_EVENT_NAME=merge_group to pytest itself.
    The ordinary ratchet cases are review-time cases, so inheriting that ambient
    value made them exercise the carve-out by accident and deterministically
    reddened the queue. Scope the neutral default to this one test module; the
    merge-group cases set the event to merge_group in their own bodies.
    """
    if request.node.nodeid.startswith("tests/test_check_ac_state_ratchet.py"):
        monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")


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

    # Sandbox containers: only clear when a test imported the sandbox server.
    sandbox_server = sys.modules.get("maistro.tools.sandbox.server")
    if sandbox_server is not None:
        sandbox_server._containers.clear()

    # Langfuse tracing
    import maistro.observability.tracing as tracing_module

    tracing_module._langfuse = None
    tracing_module._langfuse_checked = False

    # Task runner: only reset when a test imported the server app.
    main_module = sys.modules.get("maistro_server.main")
    if main_module is not None:
        main_module._runner = None


@pytest.fixture(autouse=True)
def _reset_shared_http() -> Iterator[None]:
    """Drop any test transport override and pooled clients between tests.

    The same fixture `packages/maistro-core/tests/conftest.py` has carried all
    along, and whose docstring predicted this exactly: "a leaked override would
    silently route a later test's requests into an unrelated MockTransport --
    the kind of cross-test coupling that shows up as an unrelated failure days
    later."

    It showed up (#414). `tests/hive_conductor/test_airtable_cache.py` called
    `set_test_transport()` and never restored it, so `maistro.http` kept a
    MockTransport answering 200 to every request. Two Conductor tests that
    assert an unreachable URL reports "disconnected" then saw it as reachable
    -- only when the root suite happened to share a process with them, which no
    CI job does, so nothing was red.

    The calling test is fixed to use `override_transport` too. This is here so
    the *next* one cannot do it: one tree having the guard and its neighbour
    not is how a leak this specific survives.
    """
    from maistro.http import set_test_transport

    yield
    set_test_transport(None)


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
