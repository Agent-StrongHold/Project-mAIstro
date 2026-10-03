"""Run admission binds goal_id/goal_revision, immutably, on all three backends (#1572).

The last open criterion from #1572's scope: "a Run can carry goal_id and
goal_revision as immutable provenance, set at admission. Historical Runs keep
the revision they used." Exercised against `spine`, the same three-backend
harness `test_spine_conformance.py` drives, so "immutable" and "round-trips"
are one checked fact across memory, SQLite and PostgreSQL rather than three.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maistro.graph import Graph, Node
from maistro.runs.model import GraphSnapshot, Run


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Goal-bound graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


def _snapshot() -> GraphSnapshot:
    return GraphSnapshot.from_graph(_graph("ws", "proj"))


async def test_admission_binds_the_goal_and_the_exact_revision_it_read(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id), goal_id="goal-1", goal_revision=3)

    assert run.goal_id == "goal-1"
    assert run.goal_revision == 3

    reloaded = await store.get_run(run.run_id)
    assert reloaded.goal_id == "goal-1"
    assert reloaded.goal_revision == 3


async def test_a_run_with_no_goal_binds_neither_field(spine: Any) -> None:
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id))

    assert run.goal_id is None
    assert run.goal_revision is None


async def test_historical_runs_keep_the_revision_they_ran_against(spine: Any) -> None:
    """A Goal moving on (a later revision, even a different Goal entirely for
    the next Run) must not retroactively change what an existing Run recorded."""
    store, workspace, project_id = spine
    first = await store.create_run(_graph(workspace, project_id), goal_id="goal-1", goal_revision=1)
    second = await store.create_run(
        _graph(workspace, project_id), goal_id="goal-1", goal_revision=2
    )

    reloaded_first = await store.get_run(first.run_id)
    reloaded_second = await store.get_run(second.run_id)
    assert reloaded_first.goal_revision == 1
    assert reloaded_second.goal_revision == 2


async def test_claim_run_by_effect_binds_the_goal_too(spine: Any) -> None:
    store, workspace, project_id = spine
    claim = await store.claim_run_by_effect(
        _graph(workspace, project_id),
        effect_key="effect-1",
        goal_id="goal-1",
        goal_revision=1,
    )

    assert claim.claimed is True
    assert claim.run.goal_id == "goal-1"
    assert claim.run.goal_revision == 1


def test_goal_id_and_goal_revision_must_be_set_together() -> None:
    with pytest.raises(ValidationError):
        Run(workspace_id="ws", project_id="proj", graph=_snapshot(), goal_id="goal-1")


def test_goal_revision_alone_is_also_rejected() -> None:
    with pytest.raises(ValidationError):
        Run(workspace_id="ws", project_id="proj", graph=_snapshot(), goal_revision=1)


def test_goal_revision_must_be_at_least_one() -> None:
    with pytest.raises(ValidationError):
        Run(
            workspace_id="ws",
            project_id="proj",
            graph=_snapshot(),
            goal_id="goal-1",
            goal_revision=0,
        )
