"""Canonical execution proof for the shipped Builders ReAct turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from maistro.builders.interactive import (
    BuildersExecutionSpine,
    CanonicalInteractiveTurnExecutor,
    resolve_local_operator_principal,
)
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
)
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import InMemoryRunStore


@dataclass
class _Runner:
    result: dict[str, Any]

    def __post_init__(self) -> None:
        self.messages: list[list[dict[str, Any]]] = []

    async def execute_turn(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self.messages.append(messages)
        return self.result


async def _executor() -> tuple[CanonicalInteractiveTurnExecutor, InMemoryRunStore]:
    projects = InMemoryProjectScopeStore()
    await projects.create_root("builders-cli")
    project = await projects.root_for_workspace("builders-cli")
    runs = InMemoryRunStore(project_store=projects)
    durable = CanonicalDurableRunStore(runs, InMemoryGraphContinuationStore())
    return (
        CanonicalInteractiveTurnExecutor(
            run_store=runs,
            durable_store=durable,
            workspace_id="builders-cli",
            project_id=project.project_id,
        ),
        runs,
    )


def _executor_sync() -> tuple[CanonicalInteractiveTurnExecutor, InMemoryRunStore]:
    """Executor over in-memory stores, without the async fixture's async work."""
    runs = InMemoryRunStore(project_store=InMemoryProjectScopeStore())
    durable = CanonicalDurableRunStore(runs, InMemoryGraphContinuationStore())
    return (
        CanonicalInteractiveTurnExecutor(
            run_store=runs,
            durable_store=durable,
            workspace_id="builders-cli",
            project_id="project-1",
        ),
        runs,
    )


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_react_turn_is_admitted_as_one_canonical_run_and_physical_attempt() -> None:
    executor, runs = await _executor()
    runner = _Runner({"content": "edited file", "stop_reason": "end_turn"})

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="edit the file",
        messages=[{"role": "user", "content": "edit the file"}],
        runner=runner,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.output == "edited file"
    assert len(runner.messages) == 1
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.workspace_id == "builders-cli"
    assert stored.project_id == stored.graph.project_id
    node_runs = await runs.list_node_runs(result.run_id)
    assert len(node_runs) == 1
    assert node_runs[0].node_id == "builders-stage:interactive-turn"
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    assert len(attempts) == 1
    assert attempts[0].status is AttemptStatus.COMPLETED


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_cli_spine_retains_run_identity_across_reopen(tmp_path: Any) -> None:
    database_url = f"sqlite:///{tmp_path / 'builders.db'}"
    spine = await BuildersExecutionSpine.open(
        workspace_id="builders-cli",
        database_url=database_url,
        actor_principal_id="builders-local:test-operator",
    )
    try:
        runner = _Runner({"content": "persisted", "stop_reason": "end_turn"})
        result = await spine.executor().execute(
            session_id="session-1",
            repo="/tmp/repo",
            prompt="persist this turn",
            messages=[],
            runner=runner,
        )
    finally:
        await spine.close()

    reopened = await BuildersExecutionSpine.open(
        workspace_id="builders-cli",
        database_url=database_url,
        actor_principal_id="builders-local:test-operator",
    )
    try:
        stored = await reopened.run_store.get_run(result.run_id)
        assert stored is not None
        assert stored.status is RunStatus.COMPLETED
        assert stored.workspace_id == "builders-cli"
        # The spine admits with a real local-operator actor principal (#364),
        # not a test shim: the SQLite backend enforces admission itself.
        assert stored.actor_principal_id == "builders-local:test-operator"
    finally:
        await reopened.close()


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_react_failure_cannot_project_success_without_canonical_evidence() -> None:
    executor, runs = await _executor()
    runner = _Runner({"content": "ignored", "stop_reason": "max_turns"})

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="keep working",
        messages=[],
        runner=runner,
    )

    assert result.status is RunStatus.FAILED
    assert result.error == "interactive turn stopped: max_turns"
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.status is RunStatus.FAILED
    node_runs = await runs.list_node_runs(result.run_id)
    attempts = await runs.list_attempts(node_runs[0].node_run_id)
    # The physical call returned a structured failed NodeResult, so the
    # Attempt is complete evidence of a failed operation rather than a missing
    # Attempt; the canonical Run still cannot project success.
    assert attempts[0].status is AttemptStatus.COMPLETED
    assert attempts[0].result is not None
    assert attempts[0].result.status == "failed"


def test_local_operator_principal_resolution_precedence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("MAISTRO_BUILDERS_ACTOR_PRINCIPAL", raising=False)

    # Explicit argument wins and is normalized; the CLI never admits a Run
    # without a non-empty operator identity (#364 store admission).
    assert resolve_local_operator_principal("  explicit-op ") == "explicit-op"

    monkeypatch.setenv("MAISTRO_BUILDERS_ACTOR_PRINCIPAL", "env-op")
    assert resolve_local_operator_principal() == "env-op"
    assert resolve_local_operator_principal("explicit-op") == "explicit-op"

    # No argument and no env: fall back to a stable non-empty local identity
    # derived from the OS user rather than an empty principal.
    monkeypatch.delenv("MAISTRO_BUILDERS_ACTOR_PRINCIPAL", raising=False)
    fallback = resolve_local_operator_principal()
    assert fallback.startswith("builders-local:")
    assert fallback.removeprefix("builders-local:").strip() != ""


@pytest.mark.contract("behavioral")
def test_principal_degrades_to_bare_identity_when_the_os_user_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unresolvable OS user must still yield an admissible principal.

    The fallback is what keeps the shipped CLI able to admit a turn on a box
    where `getpass.getuser()` raises (no LOGNAME/USER/`pwd` entry) — returning
    an empty string would trip the #364 store admission and make
    `maistro builders` unable to run a single turn.
    """
    import maistro.builders.interactive as interactive

    monkeypatch.delenv("MAISTRO_BUILDERS_ACTOR_PRINCIPAL", raising=False)

    def _no_user() -> str:
        raise OSError("no login name")

    monkeypatch.setattr(interactive.getpass, "getuser", _no_user)

    assert resolve_local_operator_principal() == "builders-local"


class _RaisingRunner:
    """A TurnRunner whose physical work raises."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def execute_turn(self, *, messages: list[dict[str, Any]]) -> dict[str, Any]:
        raise self._exc


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_react_dispatcher_error_settles_the_canonical_run_as_failed() -> None:
    """An exception inside the ReAct strategy is physical work that failed.

    It must become a failed canonical Run carrying the real error — not a
    raised exception that leaves the Run open, and not a success projection.
    """
    executor, runs = await _executor()

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="explode",
        messages=[],
        runner=_RaisingRunner(RuntimeError("provider refused")),
    )

    assert result.status is RunStatus.FAILED
    assert result.error == "provider refused"
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.status is RunStatus.FAILED


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_cancellation_is_not_converted_into_a_turn_failure() -> None:
    """Task cancellation stays cancellation.

    `run_durable_graph` owns the cancellation contract; a dispatcher that
    swallowed `CancelledError` into a failed NodeResult would make an
    operator's Ctrl-C look like a failed model call and would suppress the
    teardown that settles open physical work.
    """
    import asyncio

    executor, _runs = await _executor()

    with pytest.raises(asyncio.CancelledError):
        await executor.execute(
            session_id="session-1",
            repo="/tmp/repo",
            prompt="cancel me",
            messages=[],
            runner=_RaisingRunner(asyncio.CancelledError()),
        )


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_a_truncated_turn_settles_the_canonical_run_as_failed() -> None:
    """A token-limit stop is unfinished work, not a successful turn.

    `finish_reason="length"` means the model ran out of budget mid-answer.
    Recording that canonical Run COMPLETED would project a failed turn as
    success (#1068 acceptance), and the operator would never know the edit
    was truncated.
    """
    executor, runs = await _executor()
    runner = _Runner({"content": "partial edi", "stop_reason": "length"})

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="finish the refactor",
        messages=[],
        runner=runner,
    )

    assert result.status is RunStatus.FAILED
    assert result.error == "interactive turn truncated: length"
    stored = await runs.get_run(result.run_id)
    assert stored is not None
    assert stored.status is RunStatus.FAILED


@pytest.mark.contract("behavioral")
def test_the_exported_executor_resolves_a_principal_when_the_caller_omits_one() -> None:
    """Direct callers cannot hand canonical admission a `None` principal.

    Every production RunStore rejects `create_run` without an actor principal;
    the optional argument is for tests and embedding, not for admission.
    """
    executor, _runs = _executor_sync()
    assert executor._actor_principal_id
    assert executor._actor_principal_id.startswith("builders-local")


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_structured_content_blocks_are_joined_into_the_turn_output() -> None:
    """A block-structured ReAct reply reaches the TUI as readable text."""
    executor, _runs = await _executor()
    runner = _Runner(
        {
            "content": [
                {"type": "text", "text": "first"},
                {"type": "tool_use", "name": "no_text"},
                {"type": "text", "text": "second"},
            ],
            "stop_reason": "end_turn",
        }
    )

    result = await executor.execute(
        session_id="session-1",
        repo="/tmp/repo",
        prompt="say two things",
        messages=[],
        runner=runner,
    )

    assert result.status is RunStatus.COMPLETED
    assert result.output == "first\nsecond"


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_unconfigured_spine_opens_the_private_file_backed_sqlite_scope(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no deployment database the CLI uses its own SQLite *file*.

    The scope must be a file, not `:memory:`: session resume and inspection
    read the same Run identity after this process exits. A future change that
    "simplified" the fallback to an in-memory store would keep every other
    test here green and silently break that promise.
    """
    import maistro.builders.interactive as interactive

    database_path = tmp_path / "state" / "builders.db"
    monkeypatch.setattr(interactive, "_DEFAULT_DATABASE_PATH", database_path)
    monkeypatch.setattr(interactive, "resolve_database_url", lambda: "")

    spine = await BuildersExecutionSpine.open(workspace_id="builders-cli")
    try:
        assert spine.actor_principal_id.startswith("builders-local")
        assert database_path.is_file(), "the fallback scope must be a real SQLite file"
        result = await spine.executor().execute(
            session_id="session-1",
            repo="/tmp/repo",
            prompt="default scope",
            messages=[],
            runner=_Runner({"content": "ok", "stop_reason": "end_turn"}),
        )
        stored = await spine.run_store.get_run(result.run_id)
        assert stored is not None
        assert stored.status is RunStatus.COMPLETED
    finally:
        await spine.close()


@pytest.mark.contract("behavioral")
@pytest.mark.asyncio
async def test_configured_postgres_url_opens_the_pooled_spine_and_releases_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured PostgreSQL URL selects the pooled backend, not SQLite.

    The DSN is normalised for asyncpg and the pool this spine took is the pool
    it gives back on close — without either, the shipped CLI would either fail
    to connect or leak a pool per TUI session.
    """
    from types import SimpleNamespace

    import maistro.builders.interactive as interactive
    import maistro.persistence as persistence

    pool = object()
    calls: dict[str, Any] = {}

    async def _get_pool(dsn: str) -> object:
        calls["dsn"] = dsn
        return pool

    async def _release_pool(released: object) -> None:
        calls["released"] = released

    async def _wire(conn: object, **kwargs: Any) -> tuple[Any, ...]:
        calls["wire"] = {"conn": conn, **kwargs}

        class _Projects:
            async def root_for_workspace(self, workspace_id: str) -> Any:
                return SimpleNamespace(project_id=f"root-{workspace_id}")

        projects = _Projects()
        return (projects, InMemoryRunStore(project_store=projects), None, None, None, None)

    monkeypatch.setattr(persistence, "get_pool", _get_pool)
    monkeypatch.setattr(persistence, "release_pool", _release_pool)
    monkeypatch.setattr(interactive, "wire_execution_spine", _wire)

    spine = await BuildersExecutionSpine.open(
        workspace_id="builders-cli",
        database_url="postgresql+asyncpg://operator@db:5432/maistro",
        actor_principal_id="builders-local:operator",
    )
    try:
        # SQLAlchemy's `+asyncpg` spelling is not an asyncpg DSN; the spine
        # normalises it before opening the pool.
        assert calls["dsn"] == "postgresql://operator@db:5432/maistro"
        assert calls["wire"]["conn"] is None
        assert calls["wire"]["pg_pool"] is pool
        assert calls["wire"]["workspace_id"] == "builders-cli"
        assert spine.project_id == "root-builders-cli"
        assert spine.run_store is not None
    finally:
        await spine.close()

    assert calls["released"] is pool
