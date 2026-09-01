from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from maistro.graph.durable_runs import recovery
from maistro.runs.model import RunStatus

pytestmark = [pytest.mark.contract("behavioral")]


class _Store:
    def __init__(self, *records) -> None:
        self.records = {record.run_id: record for record in records}

    async def list_due(self, *, now: datetime, limit: int = 100):
        del now
        return list(self.records.values())[:limit]

    async def get(self, run_id: str):
        return self.records.get(run_id)


def _record(run_id: str, status: RunStatus, resume_at: datetime | None):
    return SimpleNamespace(
        run_id=run_id,
        run=SimpleNamespace(status=status),
        resume_at=resume_at,
    )


@pytest.mark.asyncio
async def test_wakeup_executes_due_waiting_graphs_but_never_hitl_pauses(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    paused = _record("paused", RunStatus.PAUSED, now - timedelta(seconds=2))
    future = _record("future", RunStatus.WAITING, now + timedelta(seconds=1))
    store = _Store(waiting, paused, future)
    calls: list[str] = []

    async def _resume(run_id: str, **kwargs) -> None:
        del kwargs
        calls.append(run_id)

    monkeypatch.setattr(recovery, "resume_durable_graph", _resume)

    count = await recovery.resume_due_graph_runs(
        store=store,
        run_store=object(),
        node_resolver=lambda _node_id, _graph: None,
        now=now,
    )

    assert count == 1
    assert calls == ["waiting"]


@pytest.mark.asyncio
async def test_losing_a_cross_replica_resume_race_is_idempotent(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _lose_race(run_id: str, **kwargs) -> None:
        del kwargs
        store.records[run_id] = _record(run_id, RunStatus.RUNNING, None)
        raise ValueError("version regression: another worker won")

    monkeypatch.setattr(recovery, "resume_durable_graph", _lose_race)

    assert (
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
        == 0
    )


@pytest.mark.asyncio
async def test_resume_failure_stays_visible_when_the_record_is_still_eligible(monkeypatch) -> None:
    now = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
    waiting = _record("waiting", RunStatus.WAITING, now - timedelta(seconds=1))
    store = _Store(waiting)

    async def _broken(_run_id: str, **kwargs) -> None:
        del kwargs
        raise ValueError("broken recovery invariant")

    monkeypatch.setattr(recovery, "resume_durable_graph", _broken)

    with pytest.raises(ValueError, match="broken recovery invariant"):
        await recovery.resume_due_graph_runs(
            store=store,
            run_store=object(),
            node_resolver=lambda _node_id, _graph: None,
            now=now,
        )
