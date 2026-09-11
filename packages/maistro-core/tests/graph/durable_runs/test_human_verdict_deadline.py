"""Durable HITL verdict pauses keep their originally admitted deadline."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    SqliteDurableRunStore,
    expire_hitl_pauses,
    resume_durable_graph,
    run_durable_graph,
)
from maistro.graph.nodes import get_node
from maistro.projects.scope_store import InMemoryProjectScopeStore
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
@pytest.mark.parametrize("answer", [{"verdict": "   "}, {"verdict": None}, {"verdict": 1}])
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
        assert answered.status is RunStatus.QUEUED

        restarted_store = SqliteDurableRunStore(database)
        paused = await resume_durable_graph(
            paused.run_id,
            store=restarted_store,
            node_resolver=_resolve,
        )
        assert paused.status is RunStatus.PAUSED
        assert paused.graph_state.metadata["pauses"]["step"]["resume_at"] == deadline.isoformat()

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

    answered = await store.submit_hitl_answer(
        paused.run_id,
        "step",
        {"verdict": "approved"},
        at=_T0 + timedelta(seconds=1),
    )
    settled = await resume_durable_graph(
        paused.run_id,
        store=SqliteDurableRunStore(database),
        node_resolver=_resolve,
    )

    assert answered.status is RunStatus.QUEUED
    assert settled.status is RunStatus.COMPLETED
