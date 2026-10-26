"""The DAG-run projection mirrors lifecycle metadata, never invents it (#35, #1036).

The #1036 closure-safety finding: a canonical Run that parks non-terminal
(WAITING for a human answer, PAUSED, QUEUED behind a lease) reaches the
Conductor projection writer through the run route's failure branch — the
canonical facade raises for anything not `completed` — and the writer passed
that intermediate status straight to `finish_run`, which stamps `finished_at`
once and refuses every later update. A Run the spine had not finished was
therefore irreversibly *presented* as finished, and a stale terminal row kept
its locally stamped finish time over whatever the spine later decided.

These tests pin the correction at both doors:

- **Write side** (the projection writers + a narrow `DagRunStore.record_status`
  presentation seam): the run-route writer fail-closes on input outside the
  canonical vocabulary — no row, no finish, nothing fabricated (#1877) — and
  finishes only terminal canonical outcomes; the chat workflow writer records
  the canonical outcome under the shared #1036 terminality contract, so a
  non-terminal canonical state is mirrored open with no invented
  `finished_at`, a late non-terminal mirror cannot unfinish a finished
  receipt, and an open row survives persist/reopen exactly.

- **Read side** (`services.dag_run_inspection`): lifecycle reconciliation
  replaces status AND finish time — a terminal row over an open canonical
  Run serves the open lifecycle (`finished_at` null), the served finish time
  is the canonical Run's own `finished_at` in the existing epoch-seconds
  wire shape (never the projection's local clock), and absent-canonical
  fallback still serves the recorded receipt untouched.

The #1036 regression — record WAITING, resume to COMPLETED, prove the
projection was never irreversibly finished at the intermediate state — is
`test_waiting_projection_resumes_to_completed_without_irreversible_finish`.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

pytestmark = [pytest.mark.contract("boundary")]

_AUTHED_USER_ID = "user"  # the session conftest seeds

_NONTERMINAL = ("created", "queued", "running", "waiting", "paused")
_TERMINAL = ("completed", "failed", "cancelled", "timed_out")


def _workspace(client: Any, name: str) -> str:
    """A Workspace the client's principal owns (the caller becomes owner)."""
    r = client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class _FakeCanonicalReader:
    """The slice of the scoped canonical reader that inspection reads.

    `dag_run_inspection` asks through `get_runs(run_ids, principal_id=...)`
    and `get_run(run_id, principal_id=...)`; both are Workspace-scoped in
    production, so the fake answers only the ids it was seeded with.
    """

    def __init__(self, runs: dict[str, Any] | None = None) -> None:
        self._runs = dict(runs or {})
        self.gets: list[str] = []

    async def get_runs(self, run_ids: list[str], *, principal_id: str = "") -> dict[str, Any]:
        self.gets.extend(run_ids)
        return {run_id: self._runs[run_id] for run_id in run_ids if run_id in self._runs}

    async def get_run(self, run_id: str, *, principal_id: str = "") -> Any:
        self.gets.append(run_id)
        return self._runs.get(run_id)


def _point_reader(monkeypatch: pytest.MonkeyPatch, fake: _FakeCanonicalReader) -> None:
    """Wire the fake reader in at the one seam inspection reads."""
    from services.engine import get_engine

    monkeypatch.setattr(
        get_engine(),
        "_agent_port",
        SimpleNamespace(container=SimpleNamespace(run_reader=fake)),
    )


def _canonical_run(
    run_id: str,
    status: Any,
    workspace_id: str,
    finished_at: Any = None,
    error: Any = None,
) -> Any:
    """A canonical Run shaped the way the overlay reads it, filed in the
    projection row's Workspace (the overlay ignores cross-Workspace links)."""
    return SimpleNamespace(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id="proj-lifecycle",
        actor_principal_id=_AUTHED_USER_ID,
        status=status,
        result=None,
        error=error,
        finished_at=finished_at,
        created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )


class _Records(dict):
    """The JsonStore seam `DagRunStore` persists through."""

    def initialize(self) -> None:  # the read-through `reload()` calls first
        pass


def _plant_row(
    store: Any,
    run_id: str,
    *,
    status: str,
    workspace_id: str,
    canonical_run_id: str = "",
) -> None:
    """Write one finished projection row through the real write path."""

    async def _plant() -> None:
        await store.start_run(
            run_id=run_id,
            workspace_id=workspace_id,
            canonical_run_id=canonical_run_id,
        )
        await store.finish_run(run_id, status=status)

    asyncio.run(_plant())


def _project(status: str, run_id: str, workspace_id: str, **extra: Any) -> None:
    """Drive the run route's projection writer with a canonical result shape."""
    from routes.dags import _record_run_projection

    result: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "workspace_id": workspace_id,
        "project_id": "proj-lifecycle",
        "node_results": {"n1": {"success": True, "role": "worker", "response": "ok"}},
        **extra,
    }
    asyncio.run(
        _record_run_projection(dag_id="dag-lifecycle", user_id=_AUTHED_USER_ID, result=result)
    )


# ── write side: a non-terminal mirror invents no finish ───────────────


@pytest.mark.parametrize("status", _NONTERMINAL)
def test_nonterminal_canonical_status_leaves_the_row_open(authed_client: Any, status: str) -> None:
    """All five non-terminal canonical statuses reach the projection writer
    (the facade raises for each): the row is opened and left open — no
    invented `finished_at` (#1036, #1877) — and the open row survives
    persist/reopen exactly. What the row displays is decided at read time by
    the lifecycle overlay against the canonical Run, never by a locally
    stamped finish."""
    from services.dag_run_store import configure_dag_run_store

    ws = _workspace(authed_client, f"Lifecycle Open {status}")
    records = _Records()
    store = configure_dag_run_store(records)
    run_id = f"r-open-{status}"

    _project(status, run_id, ws)

    row = store.get_run(run_id)
    assert row is not None
    assert row["finished_at"] is None
    assert records[run_id]["finished_at"] is None
    # #1036: mirror the exact canonical nonterminal status — never leave the
    # row stuck at the store's in-flight default "running".
    assert row["status"] == status
    assert records[run_id]["status"] == status

    # Persist/reopen: a replica rehydrates the fixture and the row is still
    # exactly as open as the writer left it — reopen finishes nothing.
    replica = configure_dag_run_store(records)
    replica.reload()
    reopened = replica.get_run(run_id)
    assert reopened is not None
    assert reopened["finished_at"] is None
    assert reopened["status"] == status


def test_terminal_outcomes_finish_normally(authed_client: Any) -> None:
    """All four terminal canonical statuses still finish the row: status
    recorded from the canonical outcome, `finished_at` stamped once."""
    from services.dag_run_store import configure_dag_run_store

    ws = _workspace(authed_client, "Lifecycle Terminal")
    store = configure_dag_run_store(_Records())

    for status in _TERMINAL:
        run_id = f"r-term-{status}"
        _project(status, run_id, ws)
        row = store.get_run(run_id)
        assert row is not None, status
        assert row["status"] == status
        assert row["finished_at"] is not None


def test_result_without_a_known_status_fabricates_no_terminal_outcome(
    authed_client: Any,
) -> None:
    """A result whose status is missing, or outside the canonical vocabulary,
    must not be stamped `failed` by the projection writer: that was a locally
    decided terminal outcome. The writer fail-closes before any store
    mutation — no row is opened at all — and the miss surfaces as the
    caught-and-logged projection failure it is (#1877)."""
    from services.dag_run_store import configure_dag_run_store, get_dag_run_store

    ws = _workspace(authed_client, "No Fabricated Outcome")
    store = configure_dag_run_store(_Records())

    _project("", "r-missing-status", ws)
    _project("sorta-done", "r-unknown-status", ws)

    for run_id in ("r-missing-status", "r-unknown-status"):
        assert get_dag_run_store().get_run(run_id) is None, run_id
    assert not store.list_runs(limit=100)


def test_record_status_cannot_unfinish_a_finished_receipt() -> None:
    """The presentation seam is one-way: a finished row keeps the terminal
    outcome it recorded, so a late duplicate non-terminal mirror (replay,
    double delivery) cannot unfinish the receipt."""
    from services.dag_run_store import DagRunStore

    store = DagRunStore()

    async def _drive() -> None:
        await store.start_run(run_id="r-late-mirror")
        await store.finish_run("r-late-mirror", status="completed")
        await store.record_status("r-late-mirror", status="waiting")

    asyncio.run(_drive())
    row = store.get_run("r-late-mirror")
    assert row is not None
    assert row["status"] == "completed"
    assert row["finished_at"] is not None


def test_run_route_failure_branch_parks_waiting_without_finishing(
    admin_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end through `POST /v1/dags/{id}/run`: the canonical facade
    raises for a parked (waiting) Run, the route's failure branch projects
    it, and the projection records the canonical intermediate state without
    inventing a finish."""
    import services.graph_runner as graph_runner
    import stores
    from services.dag_run_store import get_dag_run_store
    from services.graph_runner import CanonicalDagExecutionError

    ws = _workspace(admin_client, "Route Parks Waiting")
    dag_id = "dag-route-waiting"
    stores.dags[dag_id] = {
        "id": dag_id,
        "name": dag_id,
        "description": "",
        "workspace_id": ws,
        "project_id": "proj-lifecycle",
    }

    async def _parked(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise CanonicalDagExecutionError(
            {
                "status": "waiting",
                "run_id": "r-route-waiting",
                "workspace_id": ws,
                "project_id": "proj-lifecycle",
                "node_results": {},
            }
        )

    monkeypatch.setattr(graph_runner, "execute_dag", _parked)

    r = admin_client.post(f"/v1/dags/{dag_id}/run", json={"workspace_id": ws})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "waiting"

    row = get_dag_run_store().get_run("r-route-waiting")
    assert row is not None
    # The parked Run's row stays open and correlated — no invented finish;
    # what the row displays follows the canonical Run at read time.
    assert row["finished_at"] is None
    assert row["canonical_run_id"] == "r-route-waiting"


# ── the second writer: the chat workflow tool ─────────────────────────


def _seed_dag(dag_id: str, workspace_id: str) -> None:
    import stores

    stores.dags[dag_id] = {
        "id": dag_id,
        "name": dag_id,
        "description": "",
        "workspace_id": workspace_id,
        "project_id": "proj-lifecycle",
    }


def test_chat_workflow_parked_run_mirrors_open(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat workflow tool is the second projection writer, and the
    canonical facade raises for it too when the Run parks non-terminal: the
    same #1036 terminality contract must hold — WAITING is mirrored open,
    with the canonical correlation, and no finish is invented."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store
    from services.graph_runner import CanonicalDagExecutionError

    ws = _workspace(authed_client, "Chat Parks Waiting")
    dag_id = "dag-chat-waiting"
    _seed_dag(dag_id, ws)

    async def _parked(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise CanonicalDagExecutionError(
            {
                "status": "waiting",
                "run_id": "r-chat-waiting",
                "workspace_id": ws,
                "project_id": "proj-lifecycle",
                "node_results": {},
            }
        )

    monkeypatch.setattr(graph_runner, "execute_dag", _parked)
    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert "error" in out, out

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    assert new_rows, "the parked branch must still open the run's row"
    row = get_dag_run_store().get_run(next(iter(new_rows)))
    assert row is not None
    assert row["status"] == "waiting"
    assert row["finished_at"] is None
    assert row["canonical_run_id"] == "r-chat-waiting"


def test_chat_workflow_result_without_status_records_no_outcome(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canonical result with no status at all must not be stamped
    `failed` by the chat writer either: no outcome is recorded, the row
    stays open, and the miss is visible rather than papered over."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store
    from services.graph_runner import CanonicalDagExecutionError

    ws = _workspace(authed_client, "Chat No Status")
    dag_id = "dag-chat-no-status"
    _seed_dag(dag_id, ws)

    async def _no_status(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise CanonicalDagExecutionError(
            {"run_id": "r-chat-no-status", "workspace_id": ws, "node_results": {}}
        )

    monkeypatch.setattr(graph_runner, "execute_dag", _no_status)
    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    asyncio.run(_tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None))

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    assert new_rows
    row = get_dag_run_store().get_run(next(iter(new_rows)))
    assert row is not None
    assert row["finished_at"] is None
    assert row["status"] == "running"  # no fabricated outcome


# ── the #1036 regression: WAITING -> resume -> COMPLETED ──────────────


def test_waiting_projection_resumes_to_completed_without_irreversible_finish(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact #1036 regression: a canonical Run is recorded WAITING and
    projected; recovery resumes it to COMPLETED; the Conductor projection was
    never irreversibly finished at the intermediate state.

    - the WAITING projection carries no `finished_at`;
    - the terminal write still lands on the open row (under the stamp-once
      defect the first non-terminal finish made every later write a no-op);
    - after recovery, the served view follows the canonical Run — completed,
    with the canonical Run's own finish time — while the stored receipt keeps
    what it recorded at each write.
    """
    from services.dag_run_store import configure_dag_run_store, get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Waiting Then Resumed")
    store = configure_dag_run_store(_Records())
    run_id = "r-wait-recovers"

    # 1. The Run parks WAITING; the route projects the intermediate state.
    _project("waiting", run_id, ws)
    row = store.get_run(run_id)
    assert row is not None
    assert row["finished_at"] is None  # never irreversibly finished

    # 2. Recovery resumes the Run to COMPLETED; the terminal write lands.
    canonical_finished_at = datetime(2026, 10, 20, 12, 0, 0, tzinfo=UTC)
    fake = _FakeCanonicalReader(
        {run_id: _canonical_run(run_id, RunStatus.COMPLETED, ws, finished_at=canonical_finished_at)}
    )
    _point_reader(monkeypatch, fake)

    async def _terminal_write() -> None:
        await store.finish_run(run_id, status="completed")

    asyncio.run(_terminal_write())
    stored = get_dag_run_store().get_run(run_id)
    assert stored is not None
    assert stored["status"] == "completed"  # not frozen at "waiting"
    assert stored["finished_at"] is not None

    # 3. The served view observes the recovered state, with the canonical
    # Run's own finish time — and the receipt is not rewritten by the read.
    detail = authed_client.get(f"/v1/dag-runs/{run_id}")
    assert detail.status_code == 200
    served = detail.json()
    assert served["status"] == "completed"
    assert served["finished_at"] == canonical_finished_at.timestamp()
    assert stored["status"] == "completed"


# ── read side: lifecycle reconciliation replaces finish time too ──────


def test_stale_terminal_row_over_open_canonical_run_serves_open_lifecycle(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row the projection finished (completed, stamped) over a canonical
    Run the spine still holds OPEN (waiting) serves the open lifecycle:
    status waiting AND `finished_at` null — not a finish the spine never
    made, in list and detail alike."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Stale Finish Over Open Run")
    _plant_row(
        get_dag_run_store(),
        "r-stale-finish",
        status="completed",
        workspace_id=ws,
        canonical_run_id="r-stale-finish",
    )
    fake = _FakeCanonicalReader(
        {"r-stale-finish": _canonical_run("r-stale-finish", RunStatus.WAITING, ws)}
    )
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-stale-finish")
    assert detail.status_code == 200
    assert detail.json()["status"] == "waiting"
    assert detail.json()["finished_at"] is None

    listed = authed_client.get("/v1/dag-runs").json()
    row = next(r for r in listed if r["id"] == "r-stale-finish")
    assert row["status"] == "waiting"
    assert row["finished_at"] is None


def test_served_finish_time_is_canonical_not_the_local_clock(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The served finish time is derived from the canonical Run's own
    `finished_at` (datetime -> the existing epoch-seconds wire shape), never
    the projection's locally stamped clock and never a substitute timestamp:
    a row stamped failed at t_local over a Run the spine completed at
    t_canonical serves completed @ t_canonical, and the stored receipt keeps
    its own record untouched."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Canonical Clock")
    _plant_row(
        get_dag_run_store(),
        "r-canonical-clock",
        status="failed",
        workspace_id=ws,
        canonical_run_id="r-canonical-clock",
    )
    canonical_finished_at = datetime(2026, 10, 19, 9, 30, 0, tzinfo=UTC)
    fake = _FakeCanonicalReader(
        {
            "r-canonical-clock": _canonical_run(
                "r-canonical-clock",
                RunStatus.COMPLETED,
                ws,
                finished_at=canonical_finished_at,
            )
        }
    )
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-canonical-clock")
    assert detail.status_code == 200
    served = detail.json()
    assert served["status"] == "completed"
    assert served["finished_at"] == canonical_finished_at.timestamp()

    # The receipt is not rewritten by the read: provenance intact.
    stored = get_dag_run_store().get_run("r-canonical-clock")
    assert stored is not None
    assert stored["status"] == "failed"


def test_absent_canonical_still_serves_the_recorded_lifecycle(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fallback branch is unchanged: with no canonical truth to reconcile
    against (uncorrelated row, or a spine that no longer resolves the Run),
    the recorded lifecycle — status AND finish time — is served as recorded."""
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Receipt Lifecycle")
    _plant_row(
        get_dag_run_store(),
        "r-receipt-lifecycle",
        status="failed",
        workspace_id=ws,
    )
    fake = _FakeCanonicalReader({})
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-receipt-lifecycle")
    assert detail.status_code == 200
    served = detail.json()
    assert served["status"] == "failed"
    assert served["finished_at"] is not None
