"""Contract tests for the read-only AG-UI projection spike."""

from maistro.events.envelope import EventEnvelope
from maistro.events.agui_projection import project_agui_event


def test_allowlisted_event_projects_canonical_identity() -> None:
    event = EventEnvelope(
        type="run.started",
        workspace_id="ws-1",
        run_id="run-1",
        sequence=4,
        payload={"secret": "must-not-leak"},
    )
    projected = project_agui_event(event)
    assert projected == {
        "type": "CUSTOM",
        "name": "maistro.lifecycle",
        "value": {
            "eventId": event.event_id,
            "workspaceId": "ws-1",
            "runId": "run-1",
            "sequence": 4,
            "lifecycle": "run.started",
        },
    }


def test_unknown_event_never_leaks_payload() -> None:
    event = EventEnvelope(
        type="internal.secret",
        workspace_id="ws-1",
        run_id="run-1",
        sequence=1,
        payload={"token": "secret"},
    )
    assert project_agui_event(event) is None


def test_unpersisted_event_not_projected() -> None:
    event = EventEnvelope(type="run.started", workspace_id="ws-1", run_id="run-1")
    assert project_agui_event(event) is None


def test_non_workspace_event_not_projected() -> None:
    event = EventEnvelope(
        type="run.started", stream_scope="global", run_id="run-1", sequence=1
    )
    assert project_agui_event(event) is None

import pytest

from maistro.events.agui_projection import (
    AGUI_PROTOCOL_VERSION,
    project_agui_run_events,
    project_agui_run_start,
    project_agui_run_terminal,
)
from maistro.runs.model import RunStatus, TERMINAL_RUN_STATUSES


def test_agui_run_start_declares_producer_version() -> None:
    assert project_agui_run_start(thread_id="thread-1", run_id="run-1") == {
        "type": "RUN_STARTED",
        "threadId": "thread-1",
        "runId": "run-1",
        "protocolVersion": AGUI_PROTOCOL_VERSION,
    }
    assert AGUI_PROTOCOL_VERSION == "1.0"


@pytest.mark.parametrize("field", ["thread_id", "run_id"])
def test_start_requires_nonempty_identity(field: str) -> None:
    data = {"thread_id": "thread-1", "run_id": "run-1"}
    data[field] = ""
    with pytest.raises(ValueError):
        project_agui_run_start(**data)


def test_completed_run_is_successful_agui_completion() -> None:
    assert project_agui_run_terminal(
        thread_id="thread-1", run_id="run-1", status="completed"
    ) == {"type": "RUN_FINISHED", "threadId": "thread-1", "runId": "run-1"}


def test_cancelled_run_is_not_accidentally_successful() -> None:
    assert project_agui_run_terminal(
        thread_id="thread-1", run_id="run-1", status="cancelled"
    ) == {
        "type": "RUN_FINISHED",
        "threadId": "thread-1",
        "runId": "run-1",
        "outcome": {"type": "cancelled"},
    }


def test_failed_run_does_not_expose_exception_text() -> None:
    assert project_agui_run_terminal(
        thread_id="thread-1", run_id="run-1", status="failed"
    ) == {"type": "RUN_ERROR", "message": "The run failed.", "code": "maistro.run.failed"}


@pytest.mark.parametrize("status", ["created", "queued", "running", "waiting", "paused"])
def test_nonterminal_run_must_not_be_marked_finished(status: str) -> None:
    assert project_agui_run_terminal(
        thread_id="thread-1", run_id="run-1", status=status  # type: ignore[arg-type]
    ) is None


def test_unknown_status_is_an_error_not_implicit_success() -> None:
    with pytest.raises(ValueError):
        project_agui_run_terminal(
            thread_id="thread-1", run_id="run-1", status="unexpected"  # type: ignore[arg-type]
        )


def test_status_vocabulary_matches_canonical_run_enum() -> None:
    # A new canonical status forces an explicit reviewed AG-UI projection decision.
    projected = {"created", "queued", "running", "waiting", "paused", "completed", "failed", "cancelled", "timed_out"}
    assert projected == {status.value for status in RunStatus}
    assert {"completed", "failed", "cancelled", "timed_out"} == {s.value for s in TERMINAL_RUN_STATUSES}


def test_run_events_order_filter_and_dedupe_canonical_sequences() -> None:
    first = EventEnvelope(
        type="run.started", workspace_id="ws-1", run_id="run-1", sequence=1
    )
    foreign = EventEnvelope(
        type="run.started", workspace_id="ws-2", run_id="run-1", sequence=2
    )
    other_run = EventEnvelope(
        type="run.started", workspace_id="ws-1", run_id="run-2", sequence=3
    )
    internal = EventEnvelope(
        type="internal.secret", workspace_id="ws-1", run_id="run-1", sequence=4,
        payload={"password": "never"},
    )
    later = EventEnvelope(
        type="run.completed", workspace_id="ws-1", run_id="run-1", sequence=5
    )
    frames = project_agui_run_events(
        [later, other_run, foreign, first, internal, later],
        workspace_id="ws-1", run_id="run-1",
    )
    assert [frame["value"]["sequence"] for frame in frames] == [1, 5]
    assert [frame["value"]["runId"] for frame in frames] == ["run-1", "run-1"]
    assert project_agui_run_events(
        [first, later], workspace_id="ws-1", run_id="run-1", after_sequence=1
    ) == [frames[-1]]


def test_invalid_cursor_is_refused() -> None:
    with pytest.raises(ValueError):
        project_agui_run_events([], workspace_id="ws-1", run_id="run-1", after_sequence=-1)


def test_timed_out_run_reports_failure() -> None:
    assert project_agui_run_terminal(
        thread_id="thread-1", run_id="run-1", status="timed_out"
    ) == {"type": "RUN_ERROR", "message": "The run timed out.", "code": "maistro.run.timed_out"}
