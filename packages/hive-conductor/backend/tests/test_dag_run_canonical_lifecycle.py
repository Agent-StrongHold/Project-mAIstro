"""The projection publishes only canonical Run lifecycle truth (#1877).

Two seams used to publish false terminal metadata for readable same-Workspace
canonical Runs. The writer (`routes.dags._record_run_projection`) finished
every row it opened: a Run still waiting or paused got a `finished_at` the
canonical Run model forbids it to carry, and a missing status was silently
coerced to `failed`. The read overlay
(`services.dag_run_inspection._overlay`) replaced only the fields the
canonical Run happened to fill, so a stale projection `result`/`error`
survived a canonical null, and a stale `finished_at` survived a nonterminal
Run. The writer now finishes terminal Runs only, and the overlay replaces the
whole lifecycle block — status, result, error and finished_at — from the
canonical Run.

The status vocabulary under test is `RunStatus`/`TERMINAL_RUN_STATUSES`
themselves: the parametrizations below are derived from the enum, not from a
second list of strings, so a status added to (or removed from) the canonical
vocabulary moves these tests with it.

Store transition/reopen coverage here is deliberately scoped: it proves the
durable store transition and the read derivation survive a reopened store. It
is NOT executor resume/recovery — full graph resume, reconnect and installed
restart remain the #1036/#86 integration contracts.
"""

from __future__ import annotations

import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("behavioral")]

_READER_ID = "user"  # the principal the canonical spine grants membership to

#: The exact five nonterminal statuses, derived from the canonical vocabulary.
_NONTERMINAL_STATUSES = [s for s in RunStatus if s not in TERMINAL_RUN_STATUSES]

#: The exact four terminal statuses, derived from the canonical vocabulary.
_TERMINAL_STATUSES = sorted(TERMINAL_RUN_STATUSES, key=lambda s: s.value)

#: Legal transition walks from CREATED to each nonterminal status. Derived
#: per status so the test tracks the lifecycle table instead of re-encoding it.
_NONTERMINAL_WALKS: dict[RunStatus, tuple[RunStatus, ...]] = {
    RunStatus.CREATED: (),
    RunStatus.QUEUED: (RunStatus.QUEUED,),
    RunStatus.RUNNING: (RunStatus.QUEUED, RunStatus.RUNNING),
    RunStatus.WAITING: (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.WAITING),
    RunStatus.PAUSED: (RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED),
}


# ── the canonical spine (the established _canonical_spine pattern) ──────────


def _canonical_spine() -> tuple[Any, Any, Any]:
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs import InMemoryRunStore
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.workspaces import InMemoryWorkspaceStore

    projects = InMemoryProjectScopeStore()
    runs = InMemoryRunStore(project_store=projects)
    workspaces = InMemoryWorkspaceStore(project_store=projects)
    return ScopedRunReader(runs, workspaces, projects), runs, workspaces


async def _canonical_run(
    runs: Any, workspaces: Any, status: RunStatus, *, owner: str = _READER_ID
) -> Any:
    """A valid canonical Run transitioned to `status` along legal walks."""
    from maistro.graph import Graph, Node

    workspace = await workspaces.create(creator_user_id=owner, name=f"lifecycle-{owner}")
    root = await workspaces.project_store.root_for_workspace(workspace.workspace_id)
    graph = Graph(
        workspace_id=workspace.workspace_id,
        project_id=root.project_id,
        name="canonical-lifecycle",
        nodes=[Node(node_id="n", node_type="agent")],
    )
    run = await runs.create_run(graph, actor_principal_id=owner)
    for step in _NONTERMINAL_WALKS[status]:
        run = await runs.transition_run(run.run_id, step)
    return run


def _stale_record(canonical_run_id: str, workspace_id: str) -> dict[str, Any]:
    """A projection row that falsely claims a completed outcome (#1877)."""
    return {
        "id": "r-stale",
        "canonical_run_id": canonical_run_id,
        "workspace_id": workspace_id,
        "status": "completed",
        "result": {"stale": True},
        "error": "stale failure",
        "finished_at": 1234567890.0,
    }


async def _projected(
    monkeypatch: pytest.MonkeyPatch, record: dict[str, Any], reader: Any
) -> dict[str, Any]:
    """The inspection answer for `record` under the wired canonical spine."""
    import services.engine as engine_mod
    from services.dag_run_inspection import _canonical_projection

    monkeypatch.setattr(engine_mod, "_singleton", SimpleNamespace(run_reader=reader))
    return await _canonical_projection(dict(record), _READER_ID)


# ── the writer: terminal Runs finish the row, nonterminal ones do not ───────


class _SpyStore:
    """A real DagRunStore with the projection write path counted."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = {"start_run": 0, "append_event": 0, "finish_run": 0}

    async def start_run(self, **kwargs: Any) -> Any:
        self.calls["start_run"] += 1
        return await self._inner.start_run(**kwargs)

    async def append_event(self, run_id: str, **kwargs: Any) -> Any:
        self.calls["append_event"] += 1
        return await self._inner.append_event(run_id, **kwargs)

    async def finish_run(self, run_id: str, **kwargs: Any) -> Any:
        self.calls["finish_run"] += 1
        return await self._inner.finish_run(run_id, **kwargs)


def _writer_result(run_id: str, status: Any) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": status,
        "workspace_id": "ws",
        "project_id": "proj",
        "node_results": {"n1": {"success": True, "role": "worker", "response": "ok"}},
    }


async def _record_with_spy(
    monkeypatch: pytest.MonkeyPatch, result: dict[str, Any]
) -> tuple[Any, Any]:
    import services.dag_run_store as dag_run_store_mod
    from routes.dags import _record_run_projection
    from services.dag_run_store import DagRunStore

    inner = DagRunStore()
    spy = _SpyStore(inner)
    monkeypatch.setattr(dag_run_store_mod, "get_dag_run_store", lambda: spy)
    await _record_run_projection(dag_id="dag-lifecycle", user_id=_READER_ID, result=result)
    return spy, inner


async def test_writer_finishes_every_nonterminal_run_zero_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each of the five nonterminal statuses opens and events the row but
    never finishes it: a waiting Run is not a finished Run (#1877)."""
    for status in _NONTERMINAL_STATUSES:
        run_id = f"r-{status.value}"
        spy, inner = await _record_with_spy(monkeypatch, _writer_result(run_id, status.value))

        assert spy.calls["finish_run"] == 0, status.value
        assert spy.calls["start_run"] == 1, status.value
        assert spy.calls["append_event"] == 1, status.value
        row = inner.get_run(run_id)
        assert row is not None
        # The row stays open: no terminal metadata the canonical Run forbids.
        assert row["finished_at"] is None, status.value


async def test_writer_still_finishes_a_terminal_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """The control: a terminal status finishes the row exactly once, with the
    canonical status — the guard must not have disabled the writer."""
    spy, inner = await _record_with_spy(
        monkeypatch, _writer_result("r-done", RunStatus.COMPLETED.value)
    )

    assert spy.calls["finish_run"] == 1
    row = inner.get_run("r-done")
    assert row is not None
    assert row["status"] == "completed"
    assert row["finished_at"] is not None


@pytest.mark.parametrize("status_input", [None, "", "nonsense", "Completed"])
async def test_writer_never_coerces_a_malformed_status_to_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, status_input: Any
) -> None:
    """A missing, empty, unknown or non-canonical-cased status is malformed
    projection input: the existing caught-and-logged failure path runs with
    zero store mutations, and the row is never opened (#1877). It is never
    coerced to `failed` — the canonical Run's outcome is not this function's
    to invent."""
    with caplog.at_level(logging.WARNING, logger="hive.dags"):
        spy, inner = await _record_with_spy(
            monkeypatch, _writer_result("r-malformed", status_input)
        )

    assert spy.calls == {"start_run": 0, "append_event": 0, "finish_run": 0}
    assert inner.get_run("r-malformed") is None
    warnings = [r for r in caplog.records if "dag_run_projection_not_recorded" in r.message]
    assert warnings, "the malformed input must surface as the projection failure it is"


# ── the read overlay: canonical lifecycle replaces the row's wholesale ──────


async def test_overlay_replaces_every_stale_field_for_each_nonterminal_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale completed projection row under a readable same-Workspace
    nonterminal canonical Run reads as the Run actually is: canonical status,
    null finished_at (the Run model forbids one), and the canonical null
    result/error overwriting the stale values (#1877)."""
    from maistro.runs import InMemoryRunStore  # noqa: F401  (spine shape via _canonical_run)
    from maistro.workspaces import InMemoryWorkspaceStore  # noqa: F401

    for status in _NONTERMINAL_STATUSES:
        reader, runs, workspaces = _canonical_spine()
        run = await _canonical_run(runs, workspaces, status)
        record = _stale_record(run.run_id, run.workspace_id)

        projected = await _projected(monkeypatch, record, reader)

        assert projected["status"] == status.value, status.value
        assert projected["finished_at"] is None, status.value
        assert projected["result"] is None, status.value
        assert projected["error"] is None, status.value


@pytest.mark.parametrize("status", _TERMINAL_STATUSES)
async def test_overlay_derives_terminal_finished_at_from_the_canonical_timestamp_only(
    monkeypatch: pytest.MonkeyPatch, status: RunStatus
) -> None:
    """For each terminal status, the canonical Run's supplied timezone-aware
    `finished_at` reaches the response as exactly `datetime.timestamp()` —
    the epoch-seconds shape the projection already serves. A wall-clock value
    minted at read time would not equal this number (#1877)."""
    finished = datetime(2026, 1, 15, 12, 30, 45, 123456, tzinfo=UTC)
    reader, runs, workspaces = _canonical_spine()
    run = await _canonical_run(runs, workspaces, RunStatus.RUNNING)
    canonical = await runs.transition_run(
        run.run_id,
        status,
        at=finished,
        result={"answer": 42},
        error=f"{status.value} evidence",
    )
    record = _stale_record(canonical.run_id, canonical.workspace_id)

    projected = await _projected(monkeypatch, record, reader)

    assert projected["status"] == status.value
    assert projected["finished_at"] == finished.timestamp()
    assert projected["result"] == {"answer": 42}
    assert projected["error"] == f"{status.value} evidence"


async def test_overlay_canonical_values_overwrite_null_projection_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the replacement: a null projection row still gets
    the canonical nonnull values — replacement, not fill-on-absence (#1877)."""
    finished = datetime(2026, 2, 1, 8, 0, 0, tzinfo=UTC)
    reader, runs, workspaces = _canonical_spine()
    run = await _canonical_run(runs, workspaces, RunStatus.RUNNING)
    canonical = await runs.transition_run(
        run.run_id, RunStatus.COMPLETED, at=finished, result={"answer": 42}
    )
    record = {
        "id": "r-blank",
        "canonical_run_id": canonical.run_id,
        "workspace_id": canonical.workspace_id,
        "status": "running",
        "result": None,
        "error": None,
        "finished_at": None,
    }

    projected = await _projected(monkeypatch, record, reader)

    assert projected["status"] == "completed"
    assert projected["result"] == {"answer": 42}
    assert projected["error"] is None
    assert projected["finished_at"] == finished.timestamp()


# ── the guards: the two fallback branches stay byte-for-byte ────────────────


def test_overlay_without_a_readable_canonical_run_is_the_record_verbatim() -> None:
    """No canonical Run — none recorded, or one the caller cannot read —
    leaves the projection row itself in place: the fallback branch is
    preserved exactly, pending #1036's distinct historical disposition."""
    from services.dag_run_inspection import _overlay

    record = _stale_record("r-anything", "ws")
    assert _overlay(record, None) is record


def test_overlay_of_a_canonical_run_from_another_workspace_is_the_record_verbatim() -> None:
    """A canonical Run filed in a different Workspace than the projection row
    is not that row's lifecycle truth, even when readable: the mismatch
    fallback is preserved exactly (#1152)."""
    from services.dag_run_inspection import _overlay

    record = _stale_record("r-cross", "ws-row")
    run = SimpleNamespace(
        status=RunStatus.COMPLETED,
        result={"answer": 42},
        error=None,
        finished_at=datetime(2026, 1, 15, tzinfo=UTC),
        workspace_id="ws-canonical",
        provenance={},
    )
    assert _overlay(record, run) is record


def test_overlay_still_relays_creative_provenance() -> None:
    """Presentation fields the overlay does not own survive it: the
    goal_run_evidence block is relayed alongside the replaced lifecycle."""
    from services.dag_run_inspection import _overlay

    record = _stale_record("r-creative", "ws")
    run = SimpleNamespace(
        status=RunStatus.COMPLETED,
        result=None,
        error=None,
        finished_at=datetime(2026, 1, 15, tzinfo=UTC),
        workspace_id="ws",
        provenance={
            "relationship": "goal_run_evidence",
            "goal_id": "goal-spring",
            "goal_revision": 4,
        },
    )

    projected = _overlay(record, run)

    assert projected["creative_provenance"]["goal_id"] == "goal-spring"
    assert projected["creative_provenance"]["goal_revision"] == 4


# ── durable store: transition, reopen, reapply the derivation ───────────────


async def test_terminal_metadata_is_derived_from_a_reopened_durable_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid Run transitioned nonterminal → terminal in a durable
    (sqlite-backed) store, read back through a reopened store, still derives
    the exact terminal metadata through inspection.

    This pins the store transition and the read derivation across a reopen —
    NOT executor resume/recovery (#1036/#86 keep those contracts).
    """
    import aiosqlite

    from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
    from maistro.runs import SqliteRunStore
    from maistro.runs.scoped_reads import ScopedRunReader
    from maistro.workspaces.sqlite_store import SqliteWorkspaceStore

    db_path = tmp_path / "canonical-lifecycle.db"
    finished = datetime(2026, 3, 1, 9, 15, 30, tzinfo=UTC)
    run_id_holder: list[str] = []
    workspace_holder: list[str] = []

    async def _open() -> tuple[Any, ScopedRunReader]:
        conn = await aiosqlite.connect(db_path)
        projects = SqliteProjectScopeStore(conn)
        await projects.ensure_schema()
        workspaces = SqliteWorkspaceStore(conn, project_store=projects)
        await workspaces.ensure_schema()
        runs = SqliteRunStore(conn, project_store=projects)
        await runs.ensure_schema()
        return conn, ScopedRunReader(runs, workspaces, projects)

    conn, reader = await _open()
    try:
        workspace = await reader.workspace_store.create(
            creator_user_id=_READER_ID, name="durable-lifecycle"
        )
        root = await reader.workspace_store.project_store.root_for_workspace(workspace.workspace_id)
        from maistro.graph import Graph, Node

        graph = Graph(
            workspace_id=workspace.workspace_id,
            project_id=root.project_id,
            name="durable-lifecycle",
            nodes=[Node(node_id="n", node_type="agent")],
        )
        run = await reader.run_store.create_run(graph, actor_principal_id=_READER_ID)
        await reader.run_store.transition_run(run.run_id, RunStatus.QUEUED)
        await reader.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        await reader.run_store.transition_run(
            run.run_id, RunStatus.COMPLETED, at=finished, result={"answer": 42}
        )
        run_id_holder.append(run.run_id)
        workspace_holder.append(workspace.workspace_id)
    finally:
        await conn.close()

    # Reopen: a fresh store over the same file — what a restart reads.
    conn, reader = await _open()
    try:
        canonical = await reader.get_run(run_id_holder[0], principal_id=_READER_ID)
        record = {
            "id": "r-durable",
            "canonical_run_id": canonical.run_id,
            "workspace_id": workspace_holder[0],
            "status": "running",
            "result": None,
            "error": None,
            "finished_at": None,
        }

        from services.dag_run_inspection import _overlay

        projected = _overlay(record, canonical)

        assert projected["status"] == "completed"
        assert projected["result"] == {"answer": 42}
        assert projected["error"] is None
        assert projected["finished_at"] == finished.timestamp()
    finally:
        await conn.close()
