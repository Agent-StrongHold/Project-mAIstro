"""#1036: both transport writers preserve canonical-derived projection status.

These tests retain the existing unavailable-reader fallback. They do not
claim canonical-only discovery, executor recovery, or replica ordering.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.state import PersistedStore, State

pytestmark = [pytest.mark.contract("behavioral")]


@pytest.fixture
def projection_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import services.dag_run_store as storage
    from services.model_store import JsonStore

    states = []

    def reopen() -> Any:
        if states:
            states[-1].close()
        state = State(db_path=str(tmp_path / "projection.db"))
        states.append(state)
        persisted = PersistedStore(state)
        persisted.initialize()
        records = JsonStore("dag_runs", persisted=persisted)
        records.initialize()
        store = storage.DagRunStore(records=records)
        monkeypatch.setattr(storage, "_global_store", store)
        return store

    yield reopen
    states[-1].close()


async def _write(
    transport: str, result: dict[str, Any], monkeypatch: pytest.MonkeyPatch, *, events: bool = True
) -> None:
    if transport == "http":
        from routes.dags import _record_run_projection

        await _record_run_projection(dag_id="dag", user_id="user", result=result)
        return

    import stores
    from routes.ws import _stream_canonical_run
    from services import graph_runner
    from services.dag_execution_scope import DagExecutionScope

    async def execute(_dag: Any, **kwargs: Any) -> Any:
        if events:
            seq = await kwargs["on_event"](
                {"run_id": "run", "node_id": "n", "kind": "node_started"}
            )
            yield {"status": "node_started", "seq": seq}
        await kwargs["on_result"](result)
        yield {"status": result.get("status"), "run_id": "run"}

    monkeypatch.setitem(stores.dags._data, "dag", {"id": "dag"})
    monkeypatch.setattr(graph_runner, "execute_dag_streaming", execute)
    socket = SimpleNamespace(send_json=AsyncMock())
    await _stream_canonical_run(
        socket,
        dag_id="dag",
        scope=DagExecutionScope(user_id="user", workspace_id="ws", project_id="proj"),
    )
    if events:
        assert socket.send_json.call_args_list[0].args[0]["seq"] == 1


def _result(status: Any) -> dict[str, Any]:
    return {
        "run_id": "run",
        "workspace_id": "ws",
        "project_id": "proj",
        "status": status,
        "node_results": {"n": {"success": True, "response": "ok"}},
    }


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("status", list(RunStatus), ids=lambda s: s.value)
async def test_every_status_survives_writer_and_sqlite_reopen(
    projection_store: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
    transport: str,
    status: RunStatus,
) -> None:
    store = projection_store()
    await _write(transport, _result(status.value), monkeypatch)
    before = store.get_run("run")
    store = projection_store()
    row = store.get_run("run")
    assert row == before
    assert row["status"] == status.value
    assert (row["finished_at"] is not None) == (status in TERMINAL_RUN_STATUSES)
    assert row["canonical_run_id"] == "run"
    assert row["workspace_id"] == "ws"
    assert [event["seq"] for event in row["events"]] == [1]
    assert store._runs["run"].to_record()["result"]["status"] == status.value

    # Drive the existing scoped inspection service with absent and failing
    # canonical readers separately. Neither fallback may invent RUNNING.
    import services.dag_run_inspection as inspection
    import services.engine as engine

    monkeypatch.setattr(inspection, "authorized_workspace_ids", AsyncMock(return_value={"ws"}))
    broken = SimpleNamespace(get_runs=AsyncMock(side_effect=RuntimeError("reader down")))
    for reader in (None, broken):
        monkeypatch.setattr(engine, "_singleton", SimpleNamespace(run_reader=reader))
        detail = await inspection.visible_run_detail("user", "run")
        listed = await inspection.list_visible_runs("user")
        assert detail["status"] == status.value
        assert detail["finished_at"] == row["finished_at"]
        assert listed[0]["status"] == status.value
        assert listed[0]["finished_at"] == row["finished_at"]
    assert broken.get_runs.await_count == 2


@pytest.mark.parametrize("transport", ["http", "websocket"])
@pytest.mark.parametrize("status", [None, "", "unknown", "Completed"])
@pytest.mark.parametrize("existing", [False, True])
async def test_invalid_status_has_zero_projection_mutations(
    projection_store: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    transport: str,
    status: Any,
    existing: bool,
) -> None:
    store = projection_store()
    if existing:
        await store.start_run(run_id="run", workspace_id="ws")
        await store.append_event("run", event_type="pm_node_started", role="worker", capability="n")
    before = store.get_run("run")
    persisted_before = store._runs["run"].to_record() if existing else None
    spies = []
    for name in ("start_run", "append_event", "finish_run", "record_nonterminal_result"):
        spy = AsyncMock(wraps=getattr(store, name))
        monkeypatch.setattr(store, name, spy)
        spies.append(spy)
    result = _result(status)
    if status is None:
        result.pop("status")
    await _write(transport, result, monkeypatch, events=False)
    assert store.get_run("run") == before
    for spy in spies:
        spy.assert_not_awaited()
    reopened = projection_store()
    assert reopened.get_run("run") == before
    persisted_after = reopened._runs["run"].to_record() if existing else None
    assert persisted_after == persisted_before
    assert "not_recorded" in caplog.text


async def test_live_waiting_then_completed_preserves_replay_and_terminal_guard(
    projection_store: Callable[[], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.dag_execution_scope import DagExecutionScope
    from services.dag_run_live import LiveRunProjection

    store = projection_store()
    recorder = LiveRunProjection(
        dag_id="dag", scope=DagExecutionScope(user_id="user", workspace_id="ws", project_id="proj")
    )
    assert (
        await recorder.record_event({"run_id": "run", "node_id": "n", "kind": "node_started"}) == 1
    )
    await recorder.record_result(_result("waiting"))
    waiting = store.get_run("run")
    assert waiting["status"] == "waiting" and waiting["finished_at"] is None
    assert (
        await recorder.record_event(
            {"run_id": "run", "node_id": "n", "kind": "node_completed", "response": "ok"}
        )
        == 2
    )
    await recorder.record_result(_result("completed"))
    completed = store._runs["run"].to_record()
    # Preserve the projection's existing first-terminal-write behavior; this
    # does not add a revision token or order intermediate canonical results.
    await recorder.record_result(_result("paused"))
    await recorder.record_result(_result("failed"))
    assert store._runs["run"].to_record() == completed
    reopened = projection_store()
    assert reopened._runs["run"].to_record() == completed
    replay = reopened.subscribe("run")
    assert [replay.get_nowait().seq, replay.get_nowait().seq] == [1, 2]
    assert replay.empty()


async def test_nonterminal_projection_method_refuses_invalid_or_terminal_input(
    projection_store: Callable[[], Any],
) -> None:
    store = projection_store()
    await store.start_run(run_id="run")
    before = store._runs["run"].to_record()
    for invalid in ("unknown", *(status.value for status in TERMINAL_RUN_STATUSES)):
        with pytest.raises(ValueError):
            await store.record_nonterminal_result("run", status=invalid, result=_result(invalid))
        assert store._runs["run"].to_record() == before
    await store.record_nonterminal_result("absent", status="waiting", result=_result("waiting"))
    assert store.get_run("absent") is None
