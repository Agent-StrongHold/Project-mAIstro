"""Tests for `maistro repair` (maistro.cli._repair).

The door for SPEC-082926-2844's recovery. A repair nobody can invoke does not
repair anything, so these drive the commands an operator actually runs: the
read-only survey, and the apply that writes back only what can be restored
exactly.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from maistro.cli._repair import repair_apply, repair_survey
from maistro.graph import Graph, Node
from maistro.graph.durable_runs.stores import SqliteDurableRunStore
from maistro.graph.durable_runs.types import DurableRunRecord
from maistro.graph.execution_state import GraphExecutionState
from maistro.runs.model import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)

FINISHED = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
PROJECT = "project-1"
EMPTIED = {"success": True, "output": {}, "latency_ms": 4, "status": "completed"}
PRODUCED = {"text": "done", "score": 7}


def _record(*, accepted: bool, produced: object = PRODUCED) -> DurableRunRecord:
    graph = Graph(
        workspace_id="ws-1",
        project_id=PROJECT,
        name="Repair",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    run = Run(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.COMPLETED,
        finished_at=FINISHED,
    )
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    attempt = Attempt(
        node_run_id=node_run.node_run_id,
        ordinal=1,
        status=AttemptStatus.COMPLETED,
        result=EMPTIED,
        finished_at=FINISHED,
    )
    if accepted:
        node_run = node_run.model_copy(
            update={
                "status": RunStatus.COMPLETED,
                "finished_at": FINISHED,
                "accepted_outcome": AcceptedNodeOutcome(
                    node_run_id=node_run.node_run_id,
                    attempt_result=AttemptResult.from_attempt(attempt),
                    logical_status=RunStatus.COMPLETED,
                    result=produced,
                ),
                "result": produced,
            }
        )
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        attempts=(attempt,),
    )


def _seed(db_path: Path, *records: DurableRunRecord) -> SqliteDurableRunStore:
    store = SqliteDurableRunStore(db_path)
    for record in records:
        asyncio.run(store.create(record))
    return store


def _stored_output(db_path: Path, run_id: str) -> object:
    reread = asyncio.run(SqliteDurableRunStore(db_path).get(run_id))
    assert reread is not None
    return reread.attempts[0].result["output"]


@pytest.mark.ac("SPEC-082926-2844/AC-4")
def test_survey_reports_a_recoverable_output_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    record = _record(accepted=True)
    _seed(db_path, record)

    repair_survey(db_path, PROJECT)

    assert "Read-only" in capsys.readouterr().out
    assert _stored_output(db_path, record.run_id) == {}


@pytest.mark.ac("SPEC-082926-2844/AC-4")
def test_survey_says_so_when_there_is_nothing_to_repair(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    _seed(db_path)

    repair_survey(db_path, PROJECT)

    assert "No emptied Attempt outputs." in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-2844/AC-4")
def test_apply_writes_the_restored_output_back(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    record = _record(accepted=True)
    _seed(db_path, record)

    repair_apply(db_path, PROJECT)

    assert "restored 1 Attempt output(s)" in capsys.readouterr().out
    assert _stored_output(db_path, record.run_id) == PRODUCED


@pytest.mark.ac("SPEC-082926-2844/AC-4")
def test_apply_reports_what_it_had_to_leave_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "runs.sqlite3"
    record = _record(accepted=False)
    _seed(db_path, record)

    repair_apply(db_path, PROJECT)

    out = capsys.readouterr().out
    assert "Nothing to restore." in out
    assert "stay empty" in out
    assert _stored_output(db_path, record.run_id) == {}
