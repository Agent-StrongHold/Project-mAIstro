"""Immutable task evidence and the task-agnostic preparation seam (#1845)."""

from __future__ import annotations

import inspect
import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from maistro.agents.intents import IntentRegistry
from maistro.graph.definitions import Graph
from maistro.observability.correlation import bind_execution_context
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.admission_identity import RootAdmissionEnvelope
from maistro.runs.evidence_json import NON_FINITE_TAG, decode_evidence, json_of, model_of_json
from maistro.runs.model import GraphSnapshot, Run, RunStatus, evidence_values_equal
from maistro.runs.pg_store import PgRunStore
from maistro.runs.store import RunIntegrityError
from maistro.tasks import admission
from maistro.tasks.admission import (
    RootRunPreparer,
    build_root_admission_envelope,
    prepare_task_root,
)
from maistro.tasks.idempotency import (
    DERIVED_KEY_PREFIX,
    IDEMPOTENCY_KEY_PROVENANCE,
    TASK_SUBMIT_ACTION,
    InvalidIdempotencyKey,
    _to_us,
    admission_scope_key,
    from_epoch_us,
    request_fingerprint,
)
from maistro.tasks.models import TaskCreate, TaskResponse, TaskStatus

T0 = datetime(2026, 10, 18, 8, 0, 0, 123456, tzinfo=UTC)
GENERATION = UUID("12345678-1234-4234-8234-123456789abc")


def _envelope(request: TaskCreate | None = None, **overrides: Any) -> RootAdmissionEnvelope:
    arguments: dict[str, Any] = {
        "workspace_id": "original-workspace",
        "project_id": "original-project",
        "generation_id": GENERATION,
        "receipt_id": "original-receipt",
        "created_at": T0,
        "origin_principal_id": "authenticated-origin",
        "explicit_key": " original-key ",
        "service_principal_id": "authenticated-service",
        "delegation_id": "authenticated-delegation",
        "actor_kind": "service",
        "request_id": "original-request",
    }
    arguments.update(overrides)
    return build_root_admission_envelope(
        request if request is not None else TaskCreate(description="Fix the parser"), **arguments
    )


def _provenance(envelope: RootAdmissionEnvelope) -> dict[str, Any]:
    decoded = decode_evidence(json.loads(envelope.provenance_snapshot.text))
    assert isinstance(decoded, dict)
    return decoded


class _Preparer:
    def __init__(self) -> None:
        self.calls: list[tuple[Graph, dict[str, Any]]] = []

    async def __call__(self, graph: Graph, **kwargs: Any) -> Run:
        self.calls.append((graph, kwargs))
        return Run(
            workspace_id=graph.workspace_id,
            project_id=graph.project_id,
            graph=GraphSnapshot.from_graph(graph),
            actor_principal_id=kwargs["actor_principal_id"],
            provenance=kwargs["provenance"],
            status=kwargs["initial_status"],
        )


def test_original_request_fingerprint_precedes_authenticated_receipt_overlays() -> None:
    request = TaskCreate(
        description="Fix the parser",
        workspace="/checkout/not-a-canonical-workspace",
        tier=None,
        user_id="untrusted-user",
        service_principal_id="body-service",
        delegation_id="body-delegation",
        actor_kind="user",
        session_id="session-original",
    )
    before = request.model_copy(deep=True)
    envelope = _envelope(request)
    assert request == before
    assert model_of_json(TaskCreate, envelope.request_snapshot.text) == before
    assert envelope.fingerprint == request_fingerprint(before)
    assert envelope.fingerprint != request_fingerprint(
        request.model_copy(update={"service_principal_id": "authenticated-service"})
    )
    receipt = model_of_json(TaskResponse, envelope.receipt_snapshot.text)
    assert (receipt.task_id, receipt.created_at) == ("original-receipt", T0)
    assert receipt.status is TaskStatus.QUEUED and receipt.phase == "queued"
    assert receipt.run_id is None and receipt.started_at is None and receipt.result is None
    assert receipt.tier == 2 and receipt.workspace == request.workspace
    assert receipt.user_id == envelope.actor_principal_id == "authenticated-origin"
    assert receipt.service_principal_id == "authenticated-service"
    assert receipt.delegation_id == "authenticated-delegation" and receipt.actor_kind == "service"
    provenance = _provenance(envelope)
    assert provenance["task_id"] == receipt.task_id
    assert provenance["task_payload"] == receipt.model_dump(mode="json")
    assert provenance["admission_source"] == "task_queue"
    assert provenance["session_id"] == "session-original"
    assert provenance["request_id"] == "original-request"
    assert provenance["user_id"] == "authenticated-origin"
    assert provenance["service_principal_id"] == "authenticated-service"
    assert provenance["delegation_id"] == "authenticated-delegation"
    assert provenance["actor_kind"] == "service"


def test_v1_scope_uses_origin_workspace_action_and_key_but_not_project() -> None:
    envelope = _envelope()
    assert envelope.scope_key == admission_scope_key(
        principal="authenticated-origin",
        workspace_id="original-workspace",
        action=TASK_SUBMIT_ACTION,
        key="original-key",
    )
    assert _envelope(project_id="other-project").scope_key == envelope.scope_key
    assert _envelope(service_principal_id="other-service").scope_key == envelope.scope_key
    assert _envelope().action == TASK_SUBMIT_ACTION


@pytest.mark.parametrize(
    "overrides",
    [
        {"origin_principal_id": "other-origin"},
        {"workspace_id": "other-workspace"},
        {"explicit_key": "other-key"},
    ],
)
def test_distinct_authentication_scopes_remain_distinct(overrides: dict[str, str]) -> None:
    assert _envelope(None, **overrides).scope_key != _envelope().scope_key


@pytest.mark.parametrize("header,body", [(None, None), (" ", None), (None, " ")])
def test_derived_key_is_not_fabricated_as_client_provenance(
    header: str | None, body: str | None
) -> None:
    envelope = _envelope(
        TaskCreate(description="Fix the parser", idempotency_key=body), explicit_key=header
    )
    assert envelope.scope_key == admission_scope_key(
        principal=envelope.origin_principal_id,
        workspace_id=envelope.workspace_id,
        action=TASK_SUBMIT_ACTION,
        key=f"{DERIVED_KEY_PREFIX}{envelope.fingerprint}",
    )
    assert model_of_json(TaskResponse, envelope.receipt_snapshot.text).idempotency_key is None
    assert IDEMPOTENCY_KEY_PROVENANCE not in _provenance(envelope)


@pytest.mark.parametrize("header,body", [("key", None), (None, " key "), (" key ", "key")])
def test_explicit_key_normalization_preserves_original_request(
    header: str | None, body: str | None
) -> None:
    request = TaskCreate(description="Fix the parser", idempotency_key=body)
    envelope = _envelope(request, explicit_key=header)
    assert model_of_json(TaskCreate, envelope.request_snapshot.text).idempotency_key == body
    assert model_of_json(TaskResponse, envelope.receipt_snapshot.text).idempotency_key == "key"
    assert _provenance(envelope)[IDEMPOTENCY_KEY_PROVENANCE] == "key"


def test_conflicting_key_sources_keep_existing_refusal() -> None:
    with pytest.raises(InvalidIdempotencyKey, match="conflicting"):
        _envelope(TaskCreate(description="Fix", idempotency_key="body"), explicit_key="header")


@pytest.mark.parametrize(
    "created_at",
    [
        T0,
        T0.astimezone(timezone(timedelta(hours=5, minutes=30))),
        datetime(2026, 3, 7, 12, tzinfo=ZoneInfo("America/New_York")),
        datetime(2026, 10, 31, 12, tzinfo=ZoneInfo("America/New_York")),
    ],
)
def test_replay_expiry_is_exactly_24_utc_hours_even_across_dst(created_at: datetime) -> None:
    envelope = _envelope(created_at=created_at)
    assert envelope.created_at_us == _to_us(created_at)
    assert envelope.expires_at_us - envelope.created_at_us == 86_400_000_000
    assert from_epoch_us(envelope.expires_at_us) == created_at.astimezone(UTC) + timedelta(hours=24)
    assert model_of_json(TaskResponse, envelope.receipt_snapshot.text).created_at == created_at


def test_naive_generation_time_is_refused() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _envelope(created_at=T0.replace(tzinfo=None))


def test_builder_is_deterministic_and_never_reads_a_current_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class NoClock:
        @classmethod
        def now(cls, *_args: Any, **_kwargs: Any) -> datetime:
            raise AssertionError("generation creation time belongs to the caller")

    before = _envelope()
    monkeypatch.setattr(admission, "datetime", NoClock)
    assert _envelope() == before


@pytest.mark.parametrize("request_id", ["captured-once", None])
def test_builder_uses_captured_request_id_without_reading_ambient_context(
    request_id: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden() -> Any:
        raise AssertionError("the immutable builder consulted ambient request state")

    monkeypatch.setattr(admission, "current_execution_context", forbidden)
    envelope = _envelope(request_id=request_id)
    assert _provenance(envelope).get("request_id") == request_id


@pytest.mark.parametrize("value,token", [(math.nan, "nan"), (math.inf, "inf"), (-math.inf, "-inf")])
def test_nonfinite_context_survives_all_original_snapshots(value: float, token: str) -> None:
    request = TaskCreate(description="Numeric evidence", program_context={"nested": [value]})
    envelope = _envelope(request)
    for snapshot in (envelope.request_snapshot, envelope.receipt_snapshot):
        raw = json.loads(snapshot.text)
        assert raw["program_context"] == {"nested": [{NON_FINITE_TAG: token}]}
        restored = decode_evidence(raw)["program_context"]["nested"][0]
        assert math.isnan(restored) if math.isnan(value) else restored == value
    restored_provenance = _provenance(envelope)["task_payload"]["program_context"]
    assert evidence_values_equal(restored_provenance, request.program_context)
    # Evidence preservation does not redefine the shipped fingerprint algorithm.
    assert envelope.fingerprint == request_fingerprint(request)


def test_arbitrary_context_is_json_shaped_without_losing_nested_nonfinites() -> None:
    request = TaskCreate(
        description="Rich evidence",
        program_context={"tuple": (math.inf, {"at": T0, "id": GENERATION}), "bytes": b"text"},
    )
    envelope = _envelope(request)
    context = model_of_json(TaskCreate, envelope.request_snapshot.text).program_context
    assert context == {
        "tuple": [math.inf, {"at": "2026-10-18T08:00:00.123456Z", "id": str(GENERATION)}],
        "bytes": "text",
    }


def test_snapshots_detach_from_request_and_decoded_receipt_mutations() -> None:
    request = TaskCreate(description="Original", constraints=["keep"], program_context={"x": [1]})
    envelope = _envelope(request)
    original_text = envelope.request_snapshot.text
    request.description = "Changed"
    request.constraints.append("changed")
    assert request.program_context is not None
    request.program_context["x"].append(2)
    decoded = model_of_json(TaskResponse, envelope.receipt_snapshot.text)
    assert decoded.program_context is not None
    decoded.program_context["x"].append(3)
    assert envelope.request_snapshot.text == original_text
    assert model_of_json(TaskResponse, envelope.receipt_snapshot.text).program_context == {"x": [1]}
    with pytest.raises(FrozenInstanceError):
        envelope.receipt_id = "changed"  # type: ignore[misc]


async def test_preparation_uses_original_scope_actor_provenance_and_queued_state() -> None:
    envelope = _envelope(TaskCreate(description="Original work", agent_id="original-agent"))
    preparer = _Preparer()
    with bind_execution_context(request_id="retry-must-not-replace-original"):
        run = await prepare_task_root(envelope, prepare_root_run=preparer)
    assert len(preparer.calls) == 1
    graph, kwargs = preparer.calls[0]
    assert (graph.workspace_id, graph.project_id) == (envelope.workspace_id, envelope.project_id)
    assert graph.description == "Original work" and len(graph.nodes) == 1 and graph.edges == []
    assert graph.nodes[0].parameters["to_agent"] == "original-agent"
    assert kwargs["actor_principal_id"] == envelope.actor_principal_id
    assert kwargs["provenance"] == _provenance(envelope)
    assert run.status is RunStatus.QUEUED and run.parent_run_id is None
    assert run.parent_node_run_id is None


async def test_preparation_uses_supplied_intent_registry() -> None:
    preparer = _Preparer()
    await prepare_task_root(
        _envelope(TaskCreate(description="Custom work", task_type="custom")),
        prepare_root_run=preparer,
        intents=IntentRegistry({"custom": "chosen-agent"}),
    )
    assert preparer.calls[0][0].nodes[0].parameters["to_agent"] == "chosen-agent"


async def test_nonfinite_evidence_survives_preparation_and_canonical_run_serialization() -> None:
    context = {"values": [math.nan, math.inf, -math.inf]}
    envelope = _envelope(TaskCreate(description="Numeric evidence", program_context=context))
    run = await prepare_task_root(envelope, prepare_root_run=_Preparer())
    assert evidence_values_equal(run.provenance["task_payload"]["program_context"], context)
    restored = model_of_json(Run, json_of(run))
    assert evidence_values_equal(restored.provenance["task_payload"]["program_context"], context)


async def test_retry_preparation_gets_fresh_mutable_graph_and_provenance() -> None:
    envelope = _envelope(TaskCreate(description="Original", program_context={"values": [1]}))
    preparer = _Preparer()
    await prepare_task_root(envelope, prepare_root_run=preparer)
    graph, kwargs = preparer.calls[0]
    graph.nodes[0].parameters["task"] = "Corrupted by first callback"
    kwargs["provenance"]["task_payload"]["program_context"]["values"].append(2)
    await prepare_task_root(envelope, prepare_root_run=preparer)
    second_graph, second_kwargs = preparer.calls[1]
    assert second_graph is not graph
    assert second_graph.nodes[0].parameters["task"] == "Original"
    assert second_kwargs["provenance"] == _provenance(envelope)


def test_preparer_protocol_keeps_current_goal_and_canonical_callback_signature() -> None:
    expected = inspect.signature(PgRunStore.prepare_root_run).parameters
    actual = inspect.signature(RootRunPreparer.__call__).parameters
    assert list(actual) == list(expected)
    assert {name: parameter.default for name, parameter in actual.items()} == {
        name: parameter.default for name, parameter in expected.items()
    }


class _NoDatabase:
    def acquire(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("root preparation must not acquire the Run database")


async def test_adapter_calls_real_canonical_preparer_without_inserting() -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("original-workspace")
    runs = PgRunStore(_NoDatabase(), project_store=projects)
    envelope = _envelope(project_id=root.project_id)
    run = await prepare_task_root(envelope, prepare_root_run=runs.prepare_root_run)
    assert run.status is RunStatus.QUEUED
    assert run.actor_principal_id == "authenticated-origin"
    assert run.graph.project_id == root.project_id
    assert run.provenance == _provenance(envelope)


@pytest.mark.parametrize("bad_scope", ["missing-project", "wrong-workspace"])
async def test_preparation_preserves_canonical_project_validation(bad_scope: str) -> None:
    projects = InMemoryProjectScopeStore()
    root = await projects.create_root("original-workspace")
    runs = PgRunStore(_NoDatabase(), project_store=projects)
    envelope = _envelope(project_id=root.project_id)
    envelope = (
        replace(envelope, project_id="missing")
        if bad_scope == "missing-project"
        else replace(envelope, workspace_id="wrong")
    )
    with pytest.raises(RunIntegrityError):
        await prepare_task_root(envelope, prepare_root_run=runs.prepare_root_run)


async def test_preparation_failure_is_propagated_without_adapter_policy() -> None:
    failure = RuntimeError("canonical preparation refused")

    async def fail(graph: Graph, **_kwargs: Any) -> Run:
        raise failure

    with pytest.raises(RuntimeError) as caught:
        await prepare_task_root(_envelope(), prepare_root_run=fail)
    assert caught.value is failure
