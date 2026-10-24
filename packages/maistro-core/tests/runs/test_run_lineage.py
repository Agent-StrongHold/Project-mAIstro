"""Lineage is a read model over the RunStore, on every backend (M7-A6).

`maistro.runs.lineage` answers "where did this artifact come from, and what
was it scored against" purely from persisted objects. These tests run the
projection against the shared three-backend `spine` fixture — a lineage that
only one store could answer would be three separate beliefs, not one query.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.lineage import (
    ArtifactNotInRunLineage,
    artifact_lineage,
    run_lineage,
)
from maistro.runs.model import AttemptStatus, EvalMethod, RunEvalScore, RunStatus
from maistro.runs.store import RunNotFound
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

GOAL_ID = "goal-lineage"
GOAL_REVISION = 3
RUBRIC_ID = "rubric-lineage"
RUBRIC_REVISION = 2


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Lineage graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _run_one_node(spine: Any, artifact: dict[str, Any]) -> tuple[Any, str, str, str]:
    """A Run with one completed NodeRun/Attempt whose result is `artifact`."""
    store, workspace, project_id = spine
    run = await store.create_run(
        _graph(workspace, project_id), actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID
    )
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.COMPLETED, result=artifact)
    return store, run.run_id, node_run.node_run_id, attempt.attempt_id


def _score(*, attempt_id: str, node_run_id: str, run_id: str, dimension: str) -> RunEvalScore:
    return RunEvalScore(
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_id=dimension,
        raw_score=100.0,
        passed=True,
        method=EvalMethod.DETERMINISTIC,
    )


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
async def test_lineage_projects_run_graph_nodes_attempts_and_evals(spine: Any) -> None:
    store, run_id, node_run_id, attempt_id = await _run_one_node(
        spine, {"artifact": {"artifact_kind": "store_page"}}
    )
    await store.record_eval_score(
        _score(attempt_id=attempt_id, node_run_id=node_run_id, run_id=run_id, dimension="offer")
    )

    lineage = await run_lineage(store, run_id)
    assert lineage.run_id == run_id
    assert lineage.graph_id
    assert lineage.graph_content_hash
    assert lineage.status == RunStatus.COMPLETED.value or lineage.status == "created"
    assert [n.node_id for n in lineage.node_runs] == ["node-1"]
    node = lineage.node_runs[0]
    assert [a.attempt_id for a in node.attempts] == [attempt_id]
    assert node.attempts[0].result == {"artifact": {"artifact_kind": "store_page"}}
    assert [s.dimension_id for s in node.attempts[0].eval_scores] == ["offer"]
    assert [
        (b.goal_id, b.goal_revision, b.rubric_id, b.rubric_revision)
        for b in lineage.rubric_bindings
    ] == [(GOAL_ID, GOAL_REVISION, RUBRIC_ID, RUBRIC_REVISION)]


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
async def test_artifact_lineage_names_the_producing_attempt(spine: Any) -> None:
    artifact = {"artifact_kind": "store_page", "claims": [{"text": "c", "evidence": "s#1"}]}
    store, run_id, node_run_id, attempt_id = await _run_one_node(spine, artifact)

    _lineage, node, attempt = await artifact_lineage(store, run_id, artifact)
    assert (node.node_run_id, attempt.attempt_id) == (node_run_id, attempt_id)
    # An artifact nested one level inside an Attempt result resolves too.
    _, node2, attempt2 = await artifact_lineage(store, run_id, artifact["claims"][0])
    assert (node2.node_run_id, attempt2.attempt_id) == (node_run_id, attempt_id)


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
async def test_an_artifact_the_run_never_made_reports_honestly(spine: Any) -> None:
    store, run_id, _node_run_id, _attempt_id = await _run_one_node(
        spine, {"artifact": {"artifact_kind": "store_page"}}
    )
    lineage = await run_lineage(store, run_id)
    with pytest.raises(ArtifactNotInRunLineage):
        lineage.find_artifact({"artifact_kind": "artifact-from-nowhere"})


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
async def test_a_run_with_no_eval_records_reports_no_rubric(spine: Any) -> None:
    """Lineage derives bindings from evidence — never from caller memory."""
    store, run_id, _node_run_id, _attempt_id = await _run_one_node(
        spine, {"artifact": {"artifact_kind": "store_page"}}
    )
    lineage = await run_lineage(store, run_id)
    assert lineage.eval_scores == ()
    assert lineage.rubric_bindings == ()


@pytest.mark.asyncio
@pytest.mark.contract("behavioral")
async def test_lineage_of_an_unknown_run_raises_run_not_found(spine: Any) -> None:
    store, _workspace, _project_id = spine
    with pytest.raises(RunNotFound):
        await run_lineage(store, "run-nobody")
