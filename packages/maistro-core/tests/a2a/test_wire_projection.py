"""Tests for status-only A2A v1 wire projection over canonical Runs (#2500)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from maistro.a2a.wire_projection import A2AProjectionError, project_a2a_task_status
from maistro.runs.model import Run, RunStatus


def _run(status: RunStatus) -> Run:
    # Construct only projection inputs. This is not a Run admission test.
    return Run.model_construct(
        run_id="run-canonical-1",
        workspace_id="secret-ws",
        actor_principal_id="secret-actor",
        status=status,
        result={"api_key": "never expose"},
        error="internal stack trace",
        provenance={"password": "no"},
        updated_at=datetime(2026, 11, 22, 12, 34, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (RunStatus.CREATED, "TASK_STATE_SUBMITTED"),
        (RunStatus.QUEUED, "TASK_STATE_SUBMITTED"),
        (RunStatus.RUNNING, "TASK_STATE_WORKING"),
        (RunStatus.WAITING, "TASK_STATE_WORKING"),
        (RunStatus.PAUSED, "TASK_STATE_WORKING"),
        (RunStatus.COMPLETED, "TASK_STATE_COMPLETED"),
        (RunStatus.FAILED, "TASK_STATE_FAILED"),
        (RunStatus.CANCELLED, "TASK_STATE_CANCELED"),
        (RunStatus.TIMED_OUT, "TASK_STATE_FAILED"),
    ],
)
def test_every_canonical_status_has_an_explicit_wire_mapping(
    status: RunStatus, expected: str,
) -> None:
    task = project_a2a_task_status(_run(status), context_id="a2a-context-1")
    assert task == {
        "id": "run-canonical-1",
        "contextId": "a2a-context-1",
        "status": {
            "state": expected,
            "timestamp": "2026-11-22T12:34:00Z",
        },
    }


def test_status_contract_covers_entire_run_enum() -> None:
    # New statuses should force a deliberate A2A protocol decision.
    supported = {
        "created", "queued", "running", "waiting", "paused",
        "completed", "failed", "cancelled", "timed_out",
    }
    assert supported == {status.value for status in RunStatus}


def test_paused_run_is_not_invented_human_input_required() -> None:
    task = project_a2a_task_status(_run(RunStatus.PAUSED), context_id="ctx")
    assert task["status"]["state"] == "TASK_STATE_WORKING"


def test_no_sensitive_execution_information_crosses_transport() -> None:
    task = project_a2a_task_status(_run(RunStatus.COMPLETED), context_id="ctx")
    assert set(task) == {"id", "contextId", "status"}
    assert "secret-ws" not in str(task)
    assert "secret-actor" not in str(task)
    assert "api_key" not in str(task)
    assert "stack trace" not in str(task)
    assert "password" not in str(task)


@pytest.mark.parametrize("context_id", ["", "   "])
def test_blank_external_context_refused(context_id: str) -> None:
    with pytest.raises(A2AProjectionError):
        project_a2a_task_status(_run(RunStatus.RUNNING), context_id=context_id)


def test_naive_utc_time_refused() -> None:
    run = _run(RunStatus.RUNNING)
    run.updated_at = datetime(2026, 11, 22, 12, 34)
    with pytest.raises(A2AProjectionError):
        project_a2a_task_status(run, context_id="ctx")


def test_unknown_status_is_not_misrepresented_as_working() -> None:
    run = _run(RunStatus.RUNNING)
    run.status = "new-status"  # type: ignore[assignment]
    with pytest.raises(A2AProjectionError):
        project_a2a_task_status(run, context_id="ctx")
