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
