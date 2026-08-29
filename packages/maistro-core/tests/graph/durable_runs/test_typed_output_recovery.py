"""Records already written with an emptied node output are handled explicitly (#566).

The serialization fix stops the loss; it does not undo it. These hold the two
halves of the disposition: the accepted Attempt is restored exactly, from
evidence the same record already carries, and every other emptied Attempt is
reported unrecoverable and left exactly as it was found.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.graph import Graph, Node
from maistro.graph.durable_runs.repair import (
    UNRECOVERABLE_NO_EVIDENCE,
    UNRECOVERABLE_NOT_ACCEPTED,
    recover_typed_attempt_outputs,
    survey_emptied_outputs,
)
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

#: What the emptied Attempt result looks like on disk: a whole `NodeResult`
#: dump whose `output` serialized through the empty declared schema.
EMPTIED = {"success": True, "output": {}, "latency_ms": 4, "status": "completed"}
#: What the node actually produced, as `NodeRun.result` recorded it.
PRODUCED = {"text": "done", "score": 7}


def _run() -> Run:
    graph = Graph(
        workspace_id="ws-1",
        project_id="project-1",
        name="Recovery",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    return Run(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        graph=GraphSnapshot.from_graph(graph),
        status=RunStatus.COMPLETED,
        finished_at=FINISHED,
    )


def _terminal_attempt(node_run_id: str, *, ordinal: int, result: object) -> Attempt:
    return Attempt(
        node_run_id=node_run_id,
        ordinal=ordinal,
        status=AttemptStatus.COMPLETED,
        result=result,
        finished_at=FINISHED,
    )


def _record(
    node_run: NodeRun,
    attempts: tuple[Attempt, ...],
    *,
    run: Run,
) -> DurableRunRecord:
    return DurableRunRecord(
        run=run,
        graph_state=GraphExecutionState(run_id=run.run_id, active_node_ids=("node-1",)),
        node_runs=(node_run,),
        attempts=attempts,
    )


def _accepting(run: Run, attempt: Attempt, *, node_run: NodeRun, result: object) -> NodeRun:
    outcome = AcceptedNodeOutcome(
        node_run_id=node_run.node_run_id,
        attempt_result=AttemptResult.from_attempt(attempt),
        logical_status=RunStatus.COMPLETED,
        result=result,
    )
    return node_run.model_copy(
        update={
            "status": RunStatus.COMPLETED,
            "finished_at": FINISHED,
            "accepted_outcome": outcome,
            "result": result,
        }
    )


def _accepted_case(*, produced: object = PRODUCED) -> DurableRunRecord:
    """A record whose one accepted Attempt lost its output to the old contract."""
    run = _run()
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    attempt = _terminal_attempt(node_run.node_run_id, ordinal=1, result=EMPTIED)
    accepted = _accepting(run, attempt, node_run=node_run, result=produced)
    return _record(accepted, (attempt,), run=run)


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_the_accepted_attempt_is_restored_from_the_node_runs_own_evidence() -> None:
    repaired, report = recover_typed_attempt_outputs(_accepted_case())

    assert repaired.attempts[0].result["output"] == PRODUCED
    assert [entry.attempt_id for entry in report.recovered] == [repaired.attempts[0].attempt_id]
    assert report.unrecoverable == ()
    assert report.changed is True


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_recovery_touches_nothing_else_in_the_attempt_result() -> None:
    repaired, _report = recover_typed_attempt_outputs(_accepted_case())

    restored = repaired.attempts[0].result
    assert {key: restored[key] for key in EMPTIED if key != "output"} == {
        key: value for key, value in EMPTIED.items() if key != "output"
    }


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_a_superseded_attempt_is_reported_unrecoverable_and_left_alone() -> None:
    run = _run()
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    superseded = _terminal_attempt(node_run.node_run_id, ordinal=1, result=EMPTIED)
    accepted_attempt = _terminal_attempt(node_run.node_run_id, ordinal=2, result=EMPTIED)
    accepted = _accepting(run, accepted_attempt, node_run=node_run, result=PRODUCED)
    record = _record(accepted, (superseded, accepted_attempt), run=run)

    repaired, report = recover_typed_attempt_outputs(record)

    assert repaired.attempts[0].result["output"] == {}
    assert repaired.attempts[1].result["output"] == PRODUCED
    assert [(entry.attempt_id, entry.reason) for entry in report.unrecoverable] == [
        (superseded.attempt_id, UNRECOVERABLE_NOT_ACCEPTED)
    ]


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_an_unaccepted_node_run_recovers_nothing() -> None:
    run = _run()
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    attempt = _terminal_attempt(node_run.node_run_id, ordinal=1, result=EMPTIED)
    record = _record(node_run, (attempt,), run=run)

    repaired, report = recover_typed_attempt_outputs(record)

    assert repaired is record
    assert report.changed is False
    assert [entry.reason for entry in report.unrecoverable] == [UNRECOVERABLE_NOT_ACCEPTED]


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_an_accepted_attempt_with_no_stored_output_is_named_separately() -> None:
    """The NodeRun accepted it, but recorded `{}` too -- there is nothing to restore."""
    repaired, report = recover_typed_attempt_outputs(_accepted_case(produced={}))

    assert repaired.attempts[0].result["output"] == {}
    assert [entry.reason for entry in report.unrecoverable] == [UNRECOVERABLE_NO_EVIDENCE]


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_an_attempt_that_genuinely_produced_a_value_is_not_touched() -> None:
    run = _run()
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    intact = {**EMPTIED, "output": PRODUCED}
    attempt = _terminal_attempt(node_run.node_run_id, ordinal=1, result=intact)
    accepted = _accepting(run, attempt, node_run=node_run, result=PRODUCED)
    record = _record(accepted, (attempt,), run=run)

    repaired, report = recover_typed_attempt_outputs(record)

    assert repaired is record
    assert report.recovered == ()
    assert report.unrecoverable == ()


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_an_attempt_with_no_result_at_all_is_not_an_emptied_output() -> None:
    run = _run()
    node_run = NodeRun(run_id=run.run_id, node_id="node-1", ordinal=1)
    attempt = Attempt(node_run_id=node_run.node_run_id, ordinal=1, result=None)
    record = _record(node_run, (attempt,), run=run)

    _repaired, report = recover_typed_attempt_outputs(record)

    assert report.recovered == ()
    assert report.unrecoverable == ()


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_the_survey_reports_across_records_and_changes_nothing() -> None:
    recoverable = _accepted_case()

    report = survey_emptied_outputs([recoverable, _accepted_case(produced={})])

    assert len(report.recovered) == 1
    assert len(report.unrecoverable) == 1
    assert report.changed is False
    assert recoverable.attempts[0].result["output"] == {}


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_a_repaired_record_advances_its_version() -> None:
    """`DurableRunStore.update` refuses a write that does not advance the version."""
    record = _accepted_case()

    repaired, _report = recover_typed_attempt_outputs(record)

    assert repaired.version == record.version + 1


@pytest.mark.ac("SPEC-082926-2844/AC-3")
def test_a_record_with_nothing_to_restore_keeps_its_version() -> None:
    record = _accepted_case(produced={})

    repaired, _report = recover_typed_attempt_outputs(record)

    assert repaired.version == record.version
