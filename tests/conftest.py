"""Shared test fixtures and configuration."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

#: The trusted base the CI job named for itself, captured before any fixture
#: can strip it. `RATCHET_BASE_REV` is exactly the kind of ambient field the
#: autouse fixture below exists to neutralize: left visible, it makes
#: otherwise-hermetic temp-repository tests resolve the *real* repository's
#: integration base inside a throwaway git dir, where that SHA does not
#: exist. Tests that audit the real repository's shipped state (the
#: `check-*` gate self-checks) are the counter-case: they need that base, so
#: they opt back in through the `real_repository_ratchet_base` fixture,
#: which re-exports this captured value.
_AMBIENT_RATCHET_BASE_REV = os.environ.get("RATCHET_BASE_REV", "").strip()

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
def _default_ac_state_ratchet_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test opts into GitHub integration metadata explicitly, or gets none.

    A merge-group CI job exports GITHUB_EVENT_NAME=merge_group to pytest itself,
    and `check_ac_state_impl.in_merge_group()` reads exactly that. So any test
    that drives the ratchet without pinning the event inherits the job's, runs
    against the #620 carve-out it did not ask for, and fails only inside the
    queue -- green on the pull request, red where it decides the merge.

    Trusted ratchets now also read the event's base metadata. Leaving the
    runner's GITHUB_BASE_REF/GITHUB_EVENT_PATH/GITHUB_ACTIONS visible makes
    otherwise-hermetic temp-repository tests resolve the real repository's
    integration base. The default therefore keeps the historical pull-request
    event kind used by AC-state tests while removing every ambient field that
    can supply a real integration base or trigger CI-only materialization.
    `RATCHET_BASE_REV` joins that set (#1235): a job-level base named for the
    gate self-checks would otherwise leak into every temp-repository test,
    whose `git -C <tmp>` cannot resolve the real repository's SHA and would
    fail closed for the wrong reason.

    Pinning is a floor, not a ceiling: a test wanting GitHub event or Actions
    semantics sets the relevant variables in its own body, which runs after
    this fixture and wins. Tests auditing the real repository's shipped state
    request `real_repository_ratchet_base` instead of re-reading the ambient
    value themselves — capture had to happen at import time, before this
    fixture strips it.
    """
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_REF", raising=False)
    monkeypatch.delenv("RATCHET_BASE_REV", raising=False)


@pytest.fixture()
def real_repository_ratchet_base(monkeypatch: pytest.MonkeyPatch) -> None:
    """Name the CI job's own trusted base for a gate that audits the real repo.

    The `check-*` shipped-state self-checks run a full ratchet against THIS
    repository — not a fixture — so their trusted base must be the revision
    the CI event is integrating against. On a push to `develop` the resolver's
    local fallback (`origin/develop`) degenerates to HEAD, and a clean
    worktree is exactly the self-referential state `#534` refuses: without a
    named base these audits would exit non-zero for "cannot compare" instead
    of "compared and failed", and every gate-expects-failure test would pass
    vacuously. Jobs that run the root suite name the event's own base in
    `RATCHET_BASE_REV`; this fixture re-exports that captured value to the
    tests allowed to see it.

    With no ambient value (a local run) it does nothing: the resolver keeps
    its documented local semantics, and a clean develop checkout names its
    own base explicitly when it wants the self-checks judged.
    """
    if _AMBIENT_RATCHET_BASE_REV:
        monkeypatch.setenv("RATCHET_BASE_REV", _AMBIENT_RATCHET_BASE_REV)


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
