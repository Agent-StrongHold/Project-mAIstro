"""The DAG-run projection cannot own terminal truth (#35).

`DagRunStore` is the surviving receipt/projection the M1 census names the
"DagRunStore class of defect": a product store whose free-text `status`
could, in principle, terminalize or resurrect work that the canonical
Run/NodeRun/Attempt spine disagrees with. These tests pin the closure of
that defect in both directions:

- **Read side** (`services.dag_run_inspection`): a projection row that
  carries its canonical correlation is reconciled against the canonical
  durable Run store on every read. A planted contradictory row — failed
  against a completed Run, completed against a failed one, or terminal
  against a Run the spine is still executing — serves the canonical status.
  The reconciliation holds across restart/reload (the durable row survives;
  the served status still follows the spine), and it never rewrites the
  stored record: the row keeps what it recorded, provenance intact.

- **Write side** (the chat workflow tool, the one producer that minted an
  uncorrelated row key and stamped its own terminal status): the recorded
  status and the canonical correlation are copied from the canonical result
  on the success, canonical-failure, and post-return bookkeeping-failure
  paths. The unknown-outcome path (the facade died without deciding) is
  pinned as the reviewed attempt-local display boundary: the row still
  closes (#697) with the writer's witnessed fact and no invented
  correlation, and a stamped row that is correlated at admission is
  outranked by the spine at read time.

- **Boundary**: a row with no correlation, or whose canonical Run no longer
  resolves, is served exactly as recorded — an honest receipt, not an
  authority — and nothing on the execution side (scheduler, recovery, the
  canonical runner) reads this projection at all.

Canonical runs here are protocol-shaped fakes standing in for the scoped
reader seam `dag_run_inspection` reads (`get_runs`/`get_run` answering
objects whose `.status` is a real `RunStatus`): the thing under test is the
reconciliation decision, not the spine's own storage, which its own suites
cover.
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


def _workspace(client: Any, name: str) -> str:
    """A Workspace the client's principal owns (the caller becomes owner)."""
    r = client.post("/v1/workspaces", json={"persona_template_id": "pm_fleet", "name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


class _FakeCanonicalReader:
    """The slice of the scoped canonical reader that inspection reads.

    `dag_run_inspection` asks through `get_runs(run_ids, principal_id=...)`
    (the batched lifecycle overlay) and `get_run(run_id, principal_id=...)`
    (the optional NodeRun/Attempt evidence read); both are Workspace-scoped
    in production, so the fake answers only the ids it was seeded with.
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


def _canonical_record(run_id: str, status: Any, workspace_id: str) -> Any:
    """A canonical Run shaped the way the overlay reads it: a real
    `RunStatus`, the projection row's Workspace identity (the overlay ignores
    cross-Workspace links), and the null lifecycle fields it must be able to
    overwrite a stale row with."""
    return SimpleNamespace(
        run_id=run_id,
        workspace_id=workspace_id,
        project_id="proj-authority",
        actor_principal_id=_AUTHED_USER_ID,
        status=status,
        result=None,
        error=None,
        finished_at=None,
        created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )


def _point_reader(monkeypatch: pytest.MonkeyPatch, fake: _FakeCanonicalReader) -> None:
    """Wire the fake reader in at the one seam inspection reads.

    Same instance-attribute patch the session conftest uses for spine
    fixtures: `EngineService.run_reader` is a read-only view of the
    Container's scoped reader, so the Container under a fake `_agent_port`
    is the seam.
    """
    from services.engine import get_engine

    monkeypatch.setattr(
        get_engine(),
        "_agent_port",
        SimpleNamespace(container=SimpleNamespace(run_reader=fake)),
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


# ── canonical truth wins over a contradictory projection ──────────────


def test_failed_projection_row_serves_completed_canonical_truth(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Plant the classic defect: the row says failed, the spine says
    completed. List and detail must serve the canonical status."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Authority Wins")
    _plant_row(
        get_dag_run_store(),
        "r-lying-failure",
        status="failed",
        workspace_id=ws,
        canonical_run_id="r-lying-failure",
    )
    fake = _FakeCanonicalReader(
        {"r-lying-failure": _canonical_record("r-lying-failure", RunStatus.COMPLETED, ws)}
    )
    _point_reader(monkeypatch, fake)

    listed = authed_client.get("/v1/dag-runs").json()
    row = next(r for r in listed if r["id"] == "r-lying-failure")
    assert row["status"] == "completed"

    detail = authed_client.get("/v1/dag-runs/r-lying-failure")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"


def test_completed_projection_row_cannot_resurrect_failed_canonical_work(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The resurrection direction: a row claiming success over a Run the
    spine finished as failed serves the canonical failure."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "No Resurrection")
    _plant_row(
        get_dag_run_store(),
        "r-lying-success",
        status="completed",
        workspace_id=ws,
        canonical_run_id="r-lying-success",
    )
    fake = _FakeCanonicalReader(
        {"r-lying-success": _canonical_record("r-lying-success", RunStatus.FAILED, ws)}
    )
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-lying-success")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"


def test_projection_cannot_terminalize_work_the_spine_still_executes(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A terminal row over a non-terminal canonical Run is served as the
    spine's live status: the projection cannot decide work is finished
    before the spine says so."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Still Running")
    _plant_row(
        get_dag_run_store(),
        "r-premature",
        status="completed",
        workspace_id=ws,
        canonical_run_id="r-premature",
    )
    fake = _FakeCanonicalReader(
        {"r-premature": _canonical_record("r-premature", RunStatus.RUNNING, ws)}
    )
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-premature")
    assert detail.status_code == 200
    assert detail.json()["status"] == "running"


# ── the receipt boundary ──────────────────────────────────────────────


def test_uncorrelated_row_is_served_as_recorded(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A row written before correlation existed has no canonical truth to
    contradict: it is served as recorded — an honest receipt, not an
    authority the spine is asked to confirm."""
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Receipt Boundary")
    _plant_row(get_dag_run_store(), "r-uncorrelated", status="completed", workspace_id=ws)
    fake = _FakeCanonicalReader({})
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-uncorrelated")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    # The row's own key is the correlation candidate inspection asks about;
    # asking is not authority — the reader has nothing, so the recorded
    # receipt stands.


def test_row_whose_canonical_run_no_longer_resolves_is_served_as_recorded(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After a restart that emptied an in-memory spine, the durable row is
    the surviving receipt: its recorded status (itself copied from canonical
    facts at write time) is served rather than guessed away."""
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Gone Spine")
    _plant_row(
        get_dag_run_store(),
        "r-gone",
        status="failed",
        workspace_id=ws,
        canonical_run_id="r-gone",
    )
    fake = _FakeCanonicalReader({})  # the spine holds nothing anymore
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-gone")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"


# ── provenance: reconciliation never rewrites history ─────────────────


def test_reconciliation_does_not_rewrite_the_stored_record(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No historical record is rewritten to make the canonical model look
    good (#35): the served view carries canonical truth, while the stored
    row — and the durable record behind it — keep what they recorded."""
    from services.dag_run_store import configure_dag_run_store, get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Provenance")
    records = _Records()
    store = configure_dag_run_store(records)
    _plant_row(
        store,
        "r-provenance",
        status="failed",
        workspace_id=ws,
        canonical_run_id="r-provenance",
    )
    assert records["r-provenance"]["status"] == "failed"

    fake = _FakeCanonicalReader(
        {"r-provenance": _canonical_record("r-provenance", RunStatus.COMPLETED, ws)}
    )
    _point_reader(monkeypatch, fake)

    served = authed_client.get("/v1/dag-runs/r-provenance")
    assert served.json()["status"] == "completed"

    stored = get_dag_run_store().get_run("r-provenance")
    assert stored is not None and stored["status"] == "failed"
    assert records["r-provenance"]["status"] == "failed"


def test_reconciliation_holds_across_restart_and_replica_reload(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The restart/replica-handoff resurrection path: a replica rehydrates a
    contradictory durable row via `reload()` and still serves canonical
    truth, because reconciliation runs on every read — not once at load."""
    from services.dag_run_store import configure_dag_run_store, get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Reload")
    records = _Records()
    writer = configure_dag_run_store(records)
    _plant_row(
        writer,
        "r-replica",
        status="completed",
        workspace_id=ws,
        canonical_run_id="r-replica",
    )
    assert records["r-replica"]["status"] == "completed"

    # A second process boots against the same records and rehydrates them.
    replica = configure_dag_run_store(records)
    replica.reload()
    assert replica.get_run("r-replica") is not None

    fake = _FakeCanonicalReader({"r-replica": _canonical_record("r-replica", RunStatus.FAILED, ws)})
    _point_reader(monkeypatch, fake)

    detail = authed_client.get("/v1/dag-runs/r-replica")
    assert detail.status_code == 200
    assert detail.json()["status"] == "failed"
    # ... while the rehydrated record itself is untouched.
    assert get_dag_run_store().get_run("r-replica")["status"] == "completed"


# ── the write side: the chat workflow tool copies canonical outcome ───


def _seed_dag(dag_id: str, workspace_id: str) -> None:
    import stores

    stores.dags[dag_id] = {
        "id": dag_id,
        "name": dag_id,
        "description": "",
        "workspace_id": workspace_id,
        "project_id": "proj-authority",
    }


def test_chat_workflow_success_records_canonical_status_and_correlation(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The chat tool's row key is a product-local id, so the row MUST carry
    the canonical Run id and the canonical outcome — never a locally
    re-derived terminal status."""
    import services.eval_judge as eval_judge_service
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Chat Authority")
    dag_id = "dag-chat-authority"
    _seed_dag(dag_id, ws)

    async def _fake_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        return {
            "status": "completed",
            "run_id": "r-canonical-chat",
            "node_results": {"n1": {"success": True, "role": "worker", "response": "ok"}},
        }

    async def _fake_score_run(run_record: Any, **kw: Any) -> dict:
        return {"score": 50}

    monkeypatch.setattr(graph_runner, "execute_dag", _fake_execute_dag)
    monkeypatch.setattr(eval_judge_service, "score_run", _fake_score_run)

    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert out.get("status") == "completed", out

    row = get_dag_run_store().get_run(str(out["run_id"]))
    assert row is not None
    assert row["status"] == "completed"
    assert row["canonical_run_id"] == "r-canonical-chat"


def test_chat_workflow_canonical_failure_records_canonical_status_and_correlation(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canonical Run that ended `failed` (the facade raises) must land in
    the projection as exactly that — the spine's outcome and identity, not
    a chat-path re-decision."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store
    from services.graph_runner import CanonicalDagExecutionError

    ws = _workspace(authed_client, "Chat Canonical Failure")
    dag_id = "dag-chat-canonical-failure"
    _seed_dag(dag_id, ws)

    async def _failing_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise CanonicalDagExecutionError(
            {
                "status": "failed",
                "run_id": "r-canonical-failed",
                "error": "node collapsed",
                "node_results": {"n1": {"success": False, "role": "worker", "response": ""}},
            }
        )

    monkeypatch.setattr(graph_runner, "execute_dag", _failing_execute_dag)

    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert "error" in out, out

    after = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    new_rows = after - before
    assert new_rows, "the failure branch must still finish the run"
    row = get_dag_run_store().get_run(next(iter(new_rows)))
    assert row is not None
    assert row["status"] == "failed"
    assert row["canonical_run_id"] == "r-canonical-failed"


def test_chat_failure_row_is_reconciled_like_any_other(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end for the chat path: the correlated row a failure wrote is
    subject to the same read-side reconciliation as every other row."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store
    from services.graph_runner import CanonicalDagExecutionError

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Chat Reconciled")
    dag_id = "dag-chat-reconciled"
    _seed_dag(dag_id, ws)

    async def _failing_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise CanonicalDagExecutionError({"status": "failed", "run_id": "r-chat-reconciled"})

    monkeypatch.setattr(graph_runner, "execute_dag", _failing_execute_dag)
    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    asyncio.run(_tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None))

    # The spine recovered the same Run afterwards and completed it.
    fake = _FakeCanonicalReader(
        {"r-chat-reconciled": _canonical_record("r-chat-reconciled", RunStatus.COMPLETED, ws)}
    )
    _point_reader(monkeypatch, fake)

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    assert new_rows, "the failure branch must still finish the run"
    row_id = next(iter(new_rows))
    served = [r for r in authed_client.get("/v1/dag-runs").json() if r["id"] == row_id]
    assert served and served[0]["status"] == "completed"
    stored = get_dag_run_store().get_run(row_id)
    assert stored is not None and stored["status"] == "failed"  # receipt preserved


def test_chat_unknown_outcome_failure_records_the_attempt_fact(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A facade crash before any canonical verdict (here: before admission,
    so the row carries no correlation) must still close the chat tool's row
    (#697). The `failed` stamp it writes is the writer's witnessed,
    attempt-local display fact -- the chat attempt ended without an outcome
    -- and nothing about it is a copied or guessed canonical status."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Chat Attempt Fact")
    dag_id = "dag-chat-attempt-fact"
    _seed_dag(dag_id, ws)

    async def _exploding_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        raise ValueError("malformed graph never reached admission")

    monkeypatch.setattr(graph_runner, "execute_dag", _exploding_execute_dag)

    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert "error" in out, out

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    assert new_rows, "the unknown-outcome branch must still close the row (#697)"
    row = get_dag_run_store().get_run(next(iter(new_rows)))
    assert row is not None
    assert row["status"] == "failed"
    assert row["canonical_run_id"] == ""  # nothing was admitted; no invented link


def test_chat_unknown_outcome_stamp_cannot_contradict_the_spine(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash AFTER admission lands in the same unknown-outcome branch with
    the row already correlated (#1332 writes the link before any node work).
    The branch's locally stamped display `failed` must then never contradict
    canonical truth: the read overlay serves the canonical Run's lifecycle
    (here: still RUNNING) over the stamp, exactly as for any contradictory
    planted row (#35)."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "Chat Unknown Outcome")
    dag_id = "dag-chat-unknown-outcome"
    _seed_dag(dag_id, ws)

    async def _crashing_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        on_admitted = kw.get("on_admitted")
        if on_admitted is not None:
            await on_admitted("r-canonical-unknown")
        raise RuntimeError("the walk died mid-flight; the Run's fate is unresolved")

    monkeypatch.setattr(graph_runner, "execute_dag", _crashing_execute_dag)

    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert "error" in out, out

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    row_id = next(iter(new_rows))
    stored = get_dag_run_store().get_run(row_id)
    assert stored is not None
    assert stored["status"] == "failed"  # the attempt-local display fact
    assert stored["canonical_run_id"] == "r-canonical-unknown"  # correlated at admission

    # The spine says the Run is still going: served truth is the spine's,
    # not the locally stamped display status.
    fake = _FakeCanonicalReader(
        {"r-canonical-unknown": _canonical_record("r-canonical-unknown", RunStatus.RUNNING, ws)}
    )
    _point_reader(monkeypatch, fake)
    served = [r for r in authed_client.get("/v1/dag-runs").json() if r["id"] == row_id]
    assert served and served[0]["status"] == "running", served


def test_chat_bookkeeping_failure_records_the_canonical_outcome(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A graph that completed and then tripped over a bookkeeping write is a
    completed run: the branch records the canonical outcome it is holding --
    status, result and correlation, under the same #1036 contract as the
    success path -- rather than re-deciding a bare status locally (#35)."""
    import services.graph_runner as graph_runner
    from services.chat_completion import _tool_run_workflow
    from services.dag_run_store import get_dag_run_store

    ws = _workspace(authed_client, "Chat Bookkeeping Failure")
    dag_id = "dag-chat-bookkeeping"
    _seed_dag(dag_id, ws)

    async def _fake_execute_dag(dag_data: Any, *, user_id: str = "", **kw: Any) -> dict:
        return {
            "status": "completed",
            "run_id": "r-canonical-bookkeeping",
            "node_results": {"n1": {"success": True, "role": "worker", "response": "ok"}},
        }

    async def _raising_append(run_id: str, **kw: Any) -> Any:
        raise RuntimeError("history write exploded after the graph finished")

    monkeypatch.setattr(graph_runner, "execute_dag", _fake_execute_dag)
    monkeypatch.setattr(get_dag_run_store(), "append_event", _raising_append)

    before = {r["id"] for r in get_dag_run_store().list_runs(limit=100)}
    out = asyncio.run(
        _tool_run_workflow({"dag_id": dag_id, "workspace_id": ws}, _AUTHED_USER_ID, None)
    )
    assert out.get("status") == "completed", out
    assert "recording it did not" in str(out.get("warning", "")), out

    new_rows = {r["id"] for r in get_dag_run_store().list_runs(limit=100)} - before
    assert new_rows
    row = get_dag_run_store().get_run(next(iter(new_rows)))
    assert row is not None
    assert row["status"] == "completed"  # the spine's verdict, not a re-decision
    assert row["canonical_run_id"] == "r-canonical-bookkeeping"
    # The fake never fired the admission seam, so this correlation can only
    # have been written by the branch's canonical-outcome record itself.
    assert row["finished_at"] is not None


# ── the projection is not an execution authority ──────────────────────


def test_execution_side_never_reads_the_projection() -> None:
    """The semantic boundary is structural: admission, scheduling, recovery
    and the canonical runner operate on the spine, never on the projection.
    If one of them ever grows a `dag_run_store` read, this projection has
    started to become an execution authority again and this test fails."""
    import inspect

    import services.canonical_dag_runner as canonical_dag_runner
    import services.dag_agents as dag_agents
    import services.dag_recovery as dag_recovery
    import services.scheduler as scheduler

    for module in (scheduler, dag_recovery, canonical_dag_runner, dag_agents):
        assert "dag_run_store" not in inspect.getsource(module), (
            f"{module.__name__} reads the DAG-run projection; the projection must not "
            "drive execution, recovery or admission decisions (#35)"
        )


def test_contradicting_projection_cannot_mutate_canonical_truth(
    authed_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writing and serving a contradictory row leaves the canonical record
    exactly as the spine wrote it: the projection has no write path into
    execution truth."""
    from services.dag_run_store import get_dag_run_store

    from maistro.runs.model import RunStatus

    ws = _workspace(authed_client, "No Write Path")
    _plant_row(
        get_dag_run_store(),
        "r-no-write",
        status="completed",
        workspace_id=ws,
        canonical_run_id="r-no-write",
    )
    canonical = _canonical_record("r-no-write", RunStatus.FAILED, ws)
    fake = _FakeCanonicalReader({"r-no-write": canonical})
    _point_reader(monkeypatch, fake)

    served = authed_client.get("/v1/dag-runs/r-no-write")
    assert served.json()["status"] == "failed"
    # The canonical record is untouched by both the planted row and the read.
    assert canonical.status is RunStatus.FAILED
    assert "r-no-write" in fake.gets  # the detail read asked; nothing wrote
