"""P1a model support without activating cancellation-cause writers (#1884)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    Attempt,
    AttemptResult,
    AttemptStatus,
    CancellationCause,
    ExecutionLease,
)

_CREATED = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
_STARTED = _CREATED + timedelta(seconds=1)
_FINISHED = _CREATED + timedelta(seconds=10)

# Independently frozen from model.py at cf4a562b / blob 0de6b8ed, before P1a.
# In particular, result=None and the other absent evidence remain explicit.
_LEGACY_JSON = (
    '{"attempt_id":"attempt-fixed","node_run_id":"node-fixed","ordinal":1,'
    '"status":"cancelled","runtime_id":"python","executor_id":"worker-fixed",'
    '"execution_lease":null,"created_at":"2026-10-03T12:00:00Z",'
    '"started_at":"2026-10-03T12:00:01Z","finished_at":"2026-10-03T12:00:10Z",'
    '"deadline_at":null,"resume_checkpoint_id":null,"result":null,'
    '"error":null,"metrics":{}}'
)


def _legacy_payload(status: AttemptStatus = AttemptStatus.CANCELLED) -> dict[str, Any]:
    """Independent pre-change Python payload, never derived from the new serializer."""
    return {
        "attempt_id": "attempt-fixed",
        "node_run_id": "node-fixed",
        "ordinal": 1,
        "status": status,
        "runtime_id": "python",
        "executor_id": "worker-fixed",
        "execution_lease": None,
        "created_at": _CREATED,
        "started_at": None if status is AttemptStatus.CREATED else _STARTED,
        "finished_at": _FINISHED if status in TERMINAL_ATTEMPT_STATUSES else None,
        "deadline_at": None,
        "resume_checkpoint_id": None,
        "result": None,
        "error": None,
        "metrics": {},
    }


def _attempt(**updates: Any) -> Attempt:
    return Attempt.model_validate({**_legacy_payload(), **updates})


@pytest.mark.parametrize("status", list(AttemptStatus))
@pytest.mark.parametrize("explicit_null", [False, True])
def test_absent_and_null_cancellation_cause_stay_unknown(
    status: AttemptStatus, explicit_null: bool
) -> None:
    payload = _legacy_payload(status)
    if explicit_null:
        payload["cancellation_cause"] = None
    attempt = Attempt.model_validate(payload)
    assert attempt.cancellation_cause is None
    assert "cancellation_cause" not in attempt.model_dump()
    wire = json.loads(attempt.model_dump_json())
    if explicit_null:
        wire["cancellation_cause"] = None
    assert Attempt.model_validate_json(json.dumps(wire)).cancellation_cause is None


@pytest.mark.parametrize("status", list(AttemptStatus))
@pytest.mark.parametrize("cause", list(CancellationCause))
def test_only_cancelled_attempt_accepts_typed_cancellation_cause(
    status: AttemptStatus, cause: CancellationCause
) -> None:
    payload = {**_legacy_payload(status), "cancellation_cause": cause}
    if status is not AttemptStatus.CANCELLED:
        with pytest.raises(ValidationError, match="cancellation_cause"):
            Attempt.model_validate(payload)
        return
    attempt = Attempt.model_validate(payload)
    assert attempt.cancellation_cause is cause
    assert attempt.model_dump()["cancellation_cause"] is cause
    assert attempt.model_dump(mode="json")["cancellation_cause"] == cause.value
    assert Attempt.model_validate_json(attempt.model_dump_json()).cancellation_cause is cause
    assert _attempt(cancellation_cause=cause.value).cancellation_cause is cause
    with pytest.raises(ValidationError, match="finished_at"):
        _attempt(cancellation_cause=cause, finished_at=None)


@pytest.mark.parametrize(
    "value",
    [True, False, 0, 1, -1, 1.0, "", "unknown", "RECOVERED", " recovered ", [], {}, b"recovered"],
)
def test_invalid_cancellation_cause_values_are_refused(value: Any) -> None:
    with pytest.raises(ValidationError, match="cancellation_cause"):
        _attempt(cancellation_cause=value)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _attempt(unrecognized_cancellation_cause="recovered")


@pytest.mark.parametrize("original", [None, *list(CancellationCause)])
def test_cancellation_cause_is_assignment_frozen_without_freezing_attempt(
    original: CancellationCause | None,
) -> None:
    attempt = _attempt(cancellation_cause=original)
    for replacement in (None, *list(CancellationCause)):
        with pytest.raises(ValidationError, match="frozen_field"):
            attempt.cancellation_cause = replacement
        assert attempt.cancellation_cause is original
    attempt.error = "display-only annotation"
    assert attempt.error == "display-only annotation"
    # model_copy is explicitly not a durable authority or a validation boundary.
    copied = attempt.model_copy(update={"cancellation_cause": CancellationCause.RECOVERED})
    assert copied.cancellation_cause is CancellationCause.RECOVERED
    assert attempt.cancellation_cause is original


def test_null_cause_serialization_preserves_legacy_payload() -> None:
    for payload in (_legacy_payload(), {**_legacy_payload(), "cancellation_cause": None}):
        attempt = Attempt.model_validate(payload)
        assert attempt.model_dump() == _legacy_payload()
        assert attempt.model_dump(mode="json") == json.loads(_LEGACY_JSON)
        assert attempt.model_dump_json() == _LEGACY_JSON
        assert attempt.model_dump(round_trip=True) == _legacy_payload()
        assert attempt.model_dump(include={"cancellation_cause", "result"}) == {"result": None}
        assert attempt.model_dump(exclude={"error"}) == {
            key: value for key, value in _legacy_payload().items() if key != "error"
        }
        assert "cancellation_cause" not in attempt.model_dump(exclude_unset=True)
        assert "cancellation_cause" not in attempt.model_dump(exclude_defaults=True)
        assert AttemptResult.from_attempt(attempt).model_dump()["result"] is None
        assert "cancellation_cause" not in AttemptResult.from_attempt(attempt).model_dump()
    typed = _attempt(cancellation_cause="requested")
    assert typed.model_dump(mode="json", include={"cancellation_cause", "result"}) == {
        "cancellation_cause": "requested",
        "result": None,
    }
    assert typed.model_dump(exclude={"cancellation_cause"}) == _legacy_payload()
    assert typed.model_dump(mode="json", exclude_defaults=True)["cancellation_cause"] == "requested"
    assert typed.model_dump(mode="json", exclude_unset=True)["cancellation_cause"] == "requested"


@pytest.mark.parametrize("lease_kind", ["absent", "expired", "future", "infinite"])
def test_recovered_shape_does_not_require_expired_lease(lease_kind: str) -> None:
    lease = None
    if lease_kind != "absent":
        expiry = {
            "expired": _CREATED + timedelta(seconds=5),
            "future": _CREATED + timedelta(days=1),
            "infinite": None,
        }[lease_kind]
        lease = ExecutionLease(
            node_run_id="node-fixed",
            attempt_id="attempt-fixed",
            lease_epoch=1,
            holder="worker-fixed",
            fencing_token="fence-fixed",
            issued_at=_CREATED,
            expires_at=expiry,
        )
    attempt = _attempt(cancellation_cause="recovered", execution_lease=lease)
    assert attempt.execution_lease == lease
    assert attempt.cancellation_cause is CancellationCause.RECOVERED
    assert Attempt.model_validate_json(attempt.model_dump_json()) == attempt


@pytest.mark.parametrize("cause", [None, *list(CancellationCause)])
def test_nested_serialization_preserves_cause_selection_and_other_evidence(
    cause: CancellationCause | None,
) -> None:
    class Envelope(BaseModel):
        attempts: list[Attempt]
        other: None = None

    attempt = _attempt(
        cancellation_cause=cause,
        result={"missing": None, "value": [1, "a"]},
        metrics={"count": 2, "optional": None},
    )
    envelope = Envelope(attempts=[attempt])
    serialized = envelope.model_dump(mode="json")
    expected = json.loads(_LEGACY_JSON)
    expected["result"] = {"missing": None, "value": [1, "a"]}
    expected["metrics"] = {"count": 2, "optional": None}
    if cause is not None:
        expected["cancellation_cause"] = cause.value
    assert serialized == {"attempts": [expected], "other": None}
    assert json.loads(envelope.model_dump_json()) == serialized
    assert Envelope.model_validate_json(envelope.model_dump_json()) == envelope
    selected = envelope.model_dump(
        mode="json", include={"attempts": {0: {"cancellation_cause", "result"}}}
    )
    selected_evidence = {
        key: value for key, value in expected.items() if key in {"cancellation_cause", "result"}
    }
    assert selected == {"attempts": [selected_evidence]}


def test_existing_lifecycle_paths_do_not_mint_cancellation_cause() -> None:
    from maistro.runs.lifecycle import (
        reclaim_attempt,
        reclaimed_attempt_error,
        transition_attempt,
    )

    created = Attempt.model_validate(_legacy_payload(AttemptStatus.CREATED))
    running = transition_attempt(created, AttemptStatus.RUNNING, at=_STARTED)
    requested = transition_attempt(
        running, AttemptStatus.CANCELLED, at=_FINISHED, error="requested by caller"
    )
    lease = ExecutionLease(
        node_run_id=created.node_run_id,
        attempt_id=created.attempt_id,
        lease_epoch=1,
        holder="worker-fixed",
        fencing_token="fence-fixed",
        issued_at=_CREATED,
        expires_at=_CREATED + timedelta(seconds=5),
    )
    leased = Attempt.model_validate({**running.model_dump(), "execution_lease": lease})
    reclaimed = reclaim_attempt(leased, at=_FINISHED)
    for attempt in (created, running, requested, reclaimed):
        assert attempt.cancellation_cause is None
        assert "cancellation_cause" not in attempt.model_dump()
    assert requested.model_dump() == {**_legacy_payload(), "error": "requested by caller"}
    assert reclaimed.model_dump() == {
        **_legacy_payload(),
        "execution_lease": lease.model_dump(),
        "error": reclaimed_attempt_error("worker-fixed"),
    }


async def test_existing_inmemory_creation_and_claim_defaults_stay_unknown() -> None:
    from maistro.graph import Graph, Node
    from maistro.projects.scope_store import InMemoryProjectScopeStore
    from maistro.runs.consumer_claim import ClaimingInMemoryRunStore
    from maistro.runs.model import RunStatus

    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("cause-model-defaults")
    store = ClaimingInMemoryRunStore(project_store=projects)
    graph = Graph(
        workspace_id="cause-model-defaults",
        project_id=root.project_id,
        name="cause model defaults",
        nodes=[Node(node_id="step", node_type="test")],
    )
    first = await store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id="test:cause-creation"
    )
    node = await store.create_node_run(first.run_id, node_id="step")
    created = await store.create_attempt(node.node_run_id)
    second = await store.create_run(
        graph, initial_status=RunStatus.QUEUED, actor_principal_id="test:cause-claim"
    )
    claimed = await store.claim_consumer_run(
        second.run_id,
        node_id="step",
        runtime_id="python",
        executor_id="test-worker",
        lease_ttl=timedelta(seconds=30),
    )
    assert created.status is AttemptStatus.CREATED
    assert claimed.attempt.status is AttemptStatus.RUNNING
    for attempt in (created, claimed.attempt):
        assert attempt.cancellation_cause is None
        assert "cancellation_cause" not in attempt.model_dump(mode="json")
        assert await store.get_attempt(attempt.attempt_id) == attempt
