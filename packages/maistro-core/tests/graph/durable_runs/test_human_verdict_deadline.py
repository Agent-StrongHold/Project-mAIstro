"""Durable HITL verdict pauses keep their originally admitted deadline."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    InMemoryGraphContinuationStore,
    SqliteDurableRunStore,
    durable_graph_launch_provenance,
    expire_hitl_pauses,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import get_node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.model import RunStatus

_T0 = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
_TIMEOUT = 10

_CASES = (
    ("human.approve_draft", {"draft": {"ticket": "PROJ-1"}}),
    ("human.delegate_to_role", {"role": "on_call_pm"}),
    ("human.review_and_edit", {"document": {"price": 10}}),
)


class _Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


async def _project() -> tuple[str, str]:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-hitl-deadline")
    project = await projects.create(
        workspace_id="ws-hitl-deadline",
        parent_project_id=root.project_id,
        name="Graphs",
    )
    return "ws-hitl-deadline", project.project_id


def _graph(workspace_id: str, project_id: str, kind: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="durable HITL verdict deadline",
        nodes=[Node(node_id="step", node_type=kind)],
    )


def _resolve(_node_id: str, graph: Graph) -> Any:
    return get_node(graph.nodes[0].node_type)()


def _inputs(kind: str, values: dict[str, Any]) -> dict[str, Any]:
    return {**values, "timeout_seconds": _TIMEOUT}


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
@pytest.mark.ac("ADR-090726-9a4e/AC-3")
@pytest.mark.ac("ADR-090726-9a4e/AC-4")
@pytest.mark.parametrize(("kind", "values"), _CASES)
@pytest.mark.parametrize("answer", [{}, {"verdict": "   "}, {"verdict": None}, {"verdict": 1}])
async def test_repeated_malformed_answers_preserve_deadline_after_restart(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    values: dict[str, Any],
    answer: dict[str, Any],
) -> None:
    """Malformed answers at T-1 never move the original durable expiry."""
    clock = _Clock(_T0)
    import maistro.graph.nodes.base as node_base

    monkeypatch.setattr(node_base, "now_utc", clock)
    workspace_id, project_id = await _project()
    graph = _graph(workspace_id, project_id, kind)
    database = tmp_path / f"{kind.replace('.', '_')}.db"
    store = SqliteDurableRunStore(database)

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve,
        inputs=_inputs(kind, values),
    )
    raw_deadline = paused.graph_state.metadata["pauses"]["step"]["resume_at"]
    assert isinstance(raw_deadline, str)
    deadline = datetime.fromisoformat(raw_deadline)
    assert deadline == _T0 + timedelta(seconds=_TIMEOUT)

    for seconds_after_start in (8, 9, 9):
        clock.value = _T0 + timedelta(seconds=seconds_after_start)
        restarted_store = SqliteDurableRunStore(database)
        answered = await restarted_store.submit_hitl_answer(
            paused.run_id,
            "step",
            answer,
            at=clock.value,
        )
        assert answered.status is RunStatus.PAUSED
        assert answered.graph_state.metadata["pauses"]["step"]["resume_at"] == deadline.isoformat()
        assert answered.hitl_answers["step"]["_pause"]["resume_at"] == deadline.isoformat()
        paused = answered

        # A malformed answer is audited but never makes the paused Run
        # runnable, so a restart cannot turn it into a queued timeout orphan.
        restarted_store = SqliteDurableRunStore(database)
        persisted = await restarted_store.get(paused.run_id)
        assert persisted is not None
        assert persisted.status is RunStatus.PAUSED
        assert persisted.graph_state.metadata["pauses"]["step"]["resume_at"] == deadline.isoformat()

    expired = await expire_hitl_pauses(
        SqliteDurableRunStore(database),
        now=deadline,
    )
    assert [record.run_id for record in expired] == [paused.run_id]
    assert expired[0].status is RunStatus.TIMED_OUT


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
@pytest.mark.ac("ADR-090726-9a4e/AC-3")
@pytest.mark.ac("ADR-090726-9a4e/AC-4")
@pytest.mark.parametrize(("kind", "values"), _CASES)
async def test_canonical_spine_preserves_malformed_verdict_deadline(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    values: dict[str, Any],
) -> None:
    """The canonical continuation, not only the SQLite document store, owns the deadline."""
    clock = _Clock(_T0)
    import maistro.graph.nodes.base as node_base

    monkeypatch.setattr(node_base, "now_utc", clock)
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("ws-hitl-canonical-deadline")
    project = await projects.create(
        workspace_id="ws-hitl-canonical-deadline",
        parent_project_id=root.project_id,
        name="Graphs",
    )
    run_store = InMemoryRunStore(project_store=projects)
    store = CanonicalDurableRunStore(run_store, InMemoryGraphContinuationStore())
    graph = _graph("ws-hitl-canonical-deadline", project.project_id, kind)
    launch_inputs = _inputs(kind, values)
    admitted = await run_store.create_run(
        graph,
        initial_status=RunStatus.QUEUED,
        provenance=durable_graph_launch_provenance(inputs=launch_inputs),
    )

    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve,
        inputs=launch_inputs,
        run_id=admitted.run_id,
        run_store=run_store,
    )
    deadline = paused.graph_state.metadata["pauses"]["step"]["resume_at"]
    malformed = await store.submit_hitl_answer(
        paused.run_id,
        "step",
        {"verdict": "   "},
        at=_T0 + timedelta(seconds=9),
    )

    assert malformed.status is RunStatus.PAUSED
    assert malformed.graph_state.metadata["pauses"]["step"]["resume_at"] == deadline
    expired = await expire_hitl_pauses(store, now=datetime.fromisoformat(deadline))
    assert [record.run_id for record in expired] == [paused.run_id]
    canonical = await run_store.get_run(paused.run_id)
    assert canonical is not None and canonical.status is RunStatus.TIMED_OUT


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
@pytest.mark.ac("ADR-090726-9a4e/AC-3")
@pytest.mark.ac("ADR-090726-9a4e/AC-4")
async def test_malformed_answer_cannot_beat_timeout_at_deadline(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The durable deadline wins a malformed-answer race for every verdict node."""
    clock = _Clock(_T0)
    import maistro.graph.nodes.base as node_base

    monkeypatch.setattr(node_base, "now_utc", clock)
    for kind, values in _CASES:
        workspace_id, project_id = await _project()
        graph = _graph(workspace_id, project_id, kind)
        database = tmp_path / f"race_{kind.replace('.', '_')}.db"
        paused = await run_durable_graph(
            graph,
            store=SqliteDurableRunStore(database),
            node_resolver=_resolve,
            inputs=_inputs(kind, values),
        )
        run_id = paused.run_id
        malformed_store = SqliteDurableRunStore(database)
        timeout_store = SqliteDurableRunStore(database)
        results = await asyncio.gather(
            malformed_store.submit_hitl_answer(run_id, "step", {}, at=_T0 + timedelta(seconds=10)),
            timeout_store.timeout_hitl(run_id, "step", at=_T0 + timedelta(seconds=10)),
            return_exceptions=True,
        )

        assert sum(not isinstance(result, BaseException) for result in results) == 1
        settled = await SqliteDurableRunStore(database).get(run_id)
        assert settled is not None
        assert settled.status is RunStatus.TIMED_OUT
        with pytest.raises(ValueError, match="not paused"):
            await malformed_store.submit_hitl_answer(
                run_id,
                "step",
                {"verdict": "approved"},
                at=_T0 + timedelta(seconds=11),
            )


@pytest.mark.ac("ADR-090726-9a4e/AC-2")
@pytest.mark.ac("ADR-090726-9a4e/AC-3")
@pytest.mark.ac("ADR-090726-9a4e/AC-4")
@pytest.mark.parametrize(("kind", "values"), _CASES)
async def test_valid_answer_before_deadline_still_settles(
    tmp_path, monkeypatch: pytest.MonkeyPatch, kind: str, values: dict[str, Any]
) -> None:
    clock = _Clock(_T0)
    import maistro.graph.nodes.base as node_base

    monkeypatch.setattr(node_base, "now_utc", clock)
    workspace_id, project_id = await _project()
    graph = _graph(workspace_id, project_id, kind)
    database = tmp_path / f"valid_{kind.replace('.', '_')}.db"
    store = SqliteDurableRunStore(database)
    paused = await run_durable_graph(
        graph,
        store=store,
        node_resolver=_resolve,
        inputs=_inputs(kind, values),
    )

    malformed = await store.submit_hitl_answer(
        paused.run_id,
        "step",
        {"verdict": "   "},
        at=_T0 + timedelta(seconds=1),
    )
    assert malformed.status is RunStatus.PAUSED

    answered = await store.submit_hitl_answer(
        paused.run_id,
        "step",
        {"verdict": "approved"},
        at=_T0 + timedelta(seconds=2),
    )
    settled = await resume_durable_graph(
        paused.run_id,
        store=SqliteDurableRunStore(database),
        node_resolver=_resolve,
    )

    assert answered.status is RunStatus.QUEUED
    assert settled.status is RunStatus.COMPLETED
