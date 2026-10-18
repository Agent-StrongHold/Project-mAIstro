"""Attempt.cancellation_cause is staged unknown, and staging changed nothing (#1884).

The contract unit for #232's parent delivers exactly three things: the optional
canonical field, its narrow null-omitting serializer, and proof that every
existing construction/transition path still leaves the field unknown and emits
the same legacy-shaped payload. It deliberately adds no writer: recovery
predicates, reconcilers, store protocols and activation are later leaves, so
these tests assert model *shape*, never producer authorization.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from maistro.graph import Graph, Node
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs.consumer_claim import ClaimingInMemoryRunStore
from maistro.runs.lifecycle import reclaim_attempt, transition_attempt
from maistro.runs.model import Attempt, AttemptStatus, CancellationCause, ExecutionLease, RunStatus
from maistro.testing import DEFAULT_TEST_ACTOR_PRINCIPAL_ID

#: Exactly the fields a serialized Attempt carried before the staged field
#: existed. The stores persist whole-model dumps, so this is the payload shape
#: every pre-existing record has, and the one in-flight records must keep.
LEGACY_PAYLOAD_FIELDS = frozenset(
    {
        "attempt_id",
        "node_run_id",
        "ordinal",
        "status",
        "runtime_id",
        "executor_id",
        "execution_lease",
        "created_at",
        "started_at",
        "finished_at",
        "deadline_at",
        "resume_checkpoint_id",
        "result",
        "error",
        "metrics",
    }
)


def _cancelled(**overrides: object) -> Attempt:
    """A CANCELLED Attempt, the only shape a non-null cause may ride on."""
    fields: dict[str, Any] = {
        "node_run_id": "nr-1",
        "ordinal": 1,
        "status": AttemptStatus.CANCELLED,
        "finished_at": datetime.now(UTC),
    }
    fields.update(overrides)
    return Attempt(**fields)


class TestTheFieldStagesUnknown:
    def test_default_construction_leaves_the_cause_unknown(self) -> None:
        """The exact field set every store constructor passes, and nothing more."""
        attempt = Attempt(node_run_id="nr-1", ordinal=1)

        assert attempt.cancellation_cause is None

    def test_explicit_null_hydrates_unknown_too(self) -> None:
        attempt = Attempt(node_run_id="nr-1", ordinal=1, cancellation_cause=None)

        assert attempt.cancellation_cause is None

    @pytest.mark.parametrize("cause", [CancellationCause.REQUESTED, CancellationCause.RECOVERED])
    def test_exact_enum_members_hydrate(self, cause: CancellationCause) -> None:
        assert _cancelled(cancellation_cause=cause).cancellation_cause is cause

    @pytest.mark.parametrize("wire", ["requested", "recovered"])
    def test_exact_wire_values_hydrate(self, wire: str) -> None:
        attempt = Attempt.model_validate({**_cancelled().model_dump(), "cancellation_cause": wire})

        assert attempt.cancellation_cause is CancellationCause(wire)

    @pytest.mark.parametrize(
        "bad",
        [
            pytest.param(True, id="boolean"),
            pytest.param(False, id="boolean-false"),
            pytest.param(1, id="number"),
            pytest.param(3.14, id="float"),
            pytest.param("expired", id="unknown-string"),
            pytest.param("", id="empty-string"),
            pytest.param(["requested"], id="array"),
            pytest.param({"cause": "requested"}, id="object"),
        ],
    )
    def test_everything_else_fails_validation(self, bad: object) -> None:
        with pytest.raises(ValidationError):
            Attempt.model_validate({**_cancelled().model_dump(), "cancellation_cause": bad})

    def test_unknown_fields_are_still_refused(self) -> None:
        payload = {**_cancelled().model_dump(), "cancellation_cause": "requested", "bogus": 1}

        with pytest.raises(ValidationError):
            Attempt.model_validate(payload)


class TestNonNullCauseRequiresACancelledAttempt:
    def test_a_non_cancelled_status_cannot_carry_a_cause(self) -> None:
        with pytest.raises(ValidationError, match="requires status CANCELLED"):
            _cancelled(
                status=AttemptStatus.COMPLETED,
                result={"done": True},
                cancellation_cause=CancellationCause.REQUESTED,
            )

    def test_a_cancelled_attempt_without_finished_at_cannot_carry_a_cause(self) -> None:
        with pytest.raises(ValidationError, match="requires finished_at"):
            _cancelled(finished_at=None, cancellation_cause=CancellationCause.RECOVERED)

    def test_existing_lineage_status_and_time_validation_is_preserved(self) -> None:
        """The staged checks sit beside the old ones, not instead of them."""
        with pytest.raises(ValidationError, match="terminal Attempt requires finished_at"):
            _cancelled(finished_at=None)
        with pytest.raises(ValidationError, match="non-terminal Attempt cannot have"):
            _cancelled(status=AttemptStatus.RUNNING, started_at=datetime.now(UTC))
        with pytest.raises(ValidationError, match="node_run_id"):
            _cancelled(node_run_id="   ")

    def test_the_model_shape_accepts_future_writer_outputs_it_does_not_authorize(self) -> None:
        """Shape support is not writer authorization, and must not pretend otherwise.

        Dedicated recovery writers are later leaves. The model accepts their
        outputs -- RECOVERED on a leaseless orphan, or on an owned cancellation
        that retains a non-expiring lease -- so adding a writer never requires
        loosening this validation. Nothing here says a writer may produce these.
        """
        live_lease_attempt = _cancelled()
        live_lease = ExecutionLease(
            node_run_id=live_lease_attempt.node_run_id,
            attempt_id=live_lease_attempt.attempt_id,
            lease_epoch=1,
            holder="still-alive",
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

        leaseless = _cancelled(cancellation_cause=CancellationCause.RECOVERED)
        leased = Attempt.model_validate(
            {
                **live_lease_attempt.model_dump(),
                "execution_lease": live_lease,
                "cancellation_cause": CancellationCause.RECOVERED,
            }
        )

        assert leaseless.cancellation_cause is CancellationCause.RECOVERED
        assert leased.execution_lease is not None
        assert leased.cancellation_cause is CancellationCause.RECOVERED


class TestOrdinaryAssignmentCannotTouchTheCause:
    @pytest.mark.parametrize(
        ("value", "what"),
        [
            (CancellationCause.REQUESTED, "set"),
            (None, "clear"),
            (CancellationCause.RECOVERED, "change"),
        ],
    )
    def test_assignment_is_refused_in_every_direction(self, value: object, what: str) -> None:
        attempt = _cancelled(cancellation_cause=CancellationCause.REQUESTED)

        with pytest.raises(ValidationError):
            attempt.cancellation_cause = value  # type: ignore[assignment]

        assert attempt.cancellation_cause is CancellationCause.REQUESTED

    def test_unrelated_mutable_fields_still_assign(self) -> None:
        attempt = _cancelled()

        attempt.error = "settled by hand"

        assert attempt.error == "settled by hand"


class TestTheSerializerOmitsOnlyTheUnknownCause:
    def test_an_unknown_cause_is_absent_from_every_dump_of_an_unstaged_attempt(self) -> None:
        attempt = _cancelled()

        dumped = attempt.model_dump()
        json_payload = json.loads(attempt.model_dump_json())

        assert "cancellation_cause" not in dumped
        assert "cancellation_cause" not in json_payload
        assert set(dumped) == LEGACY_PAYLOAD_FIELDS

    def test_unrelated_null_keys_survive(self) -> None:
        dumped = _cancelled().model_dump()
        json_payload = json.loads(_cancelled().model_dump_json())

        assert dumped["result"] is None
        assert dumped["error"] is None
        assert dumped["started_at"] is None
        assert json_payload["result"] is None
        assert json_payload["metrics"] == {}

    def test_a_known_cause_serializes_to_its_exact_enum_value(self) -> None:
        attempt = _cancelled(cancellation_cause=CancellationCause.REQUESTED)

        assert attempt.model_dump()["cancellation_cause"] is CancellationCause.REQUESTED
        assert attempt.model_dump(mode="json")["cancellation_cause"] == "requested"
        assert json.loads(attempt.model_dump_json())["cancellation_cause"] == "requested"

    def test_a_known_cause_round_trips_and_an_omitted_one_reads_back_unknown(self) -> None:
        staged = _cancelled(cancellation_cause=CancellationCause.RECOVERED)

        assert Attempt.model_validate_json(staged.model_dump_json()).cancellation_cause is (
            CancellationCause.RECOVERED
        )
        assert Attempt.model_validate_json(_cancelled().model_dump_json()).cancellation_cause is (
            None
        )

    def test_existing_value_enums_datetimes_and_metrics_are_untouched(self) -> None:
        finished = datetime.now(UTC)
        attempt = _cancelled(
            status=AttemptStatus.COMPLETED,
            result={"answer": 42},
            error=None,
            metrics={"tokens": 7},
            finished_at=finished,
        )

        dumped = attempt.model_dump()
        json_payload = json.loads(attempt.model_dump_json())

        assert dumped["status"] is AttemptStatus.COMPLETED
        assert json_payload["status"] == "completed"
        assert dumped["result"] == {"answer": 42}
        assert dumped["metrics"] == {"tokens": 7}
        assert datetime.fromisoformat(json_payload["finished_at"]) == finished

    def test_the_field_stays_declared_in_the_model_schema(self) -> None:
        """Omitting the unknown value must not undeclare the field.

        The JSON schema is the contract other readers generate clients from;
        the serializer narrows payloads, not the declared shape.
        """
        assert "cancellation_cause" in Attempt.model_json_schema()["properties"]

    def test_the_serialization_mode_schema_keeps_every_declared_field(self) -> None:
        """A wrap serializer's return annotation drives the serialization-mode schema.

        Pydantic derives a model's serialization-mode JSON schema from the
        wrap serializer's return annotation when one exists: annotating
        ``-> dict[str, Any]`` collapses Attempt to an opaque
        ``{"type": "object", "additionalProperties": true}`` and hides every
        field from serialization-schema consumers, even though validation
        mode still lists them. The serializer must therefore stay free of a
        return annotation (verified against pydantic 2.13.5).
        """
        serialization = Attempt.model_json_schema(mode="serialization")

        assert set(serialization["properties"]) == LEGACY_PAYLOAD_FIELDS | {"cancellation_cause"}

    def test_the_serializer_applies_when_the_attempt_is_nested(self) -> None:
        class _ExecutionRecord(BaseModel):
            attempts: tuple[Attempt, ...]

        record = _ExecutionRecord(
            attempts=[
                _cancelled(),
                _cancelled(cancellation_cause=CancellationCause.RECOVERED),
            ]
        )

        payload = json.loads(record.model_dump_json())

        assert "cancellation_cause" not in payload["attempts"][0]
        assert payload["attempts"][1]["cancellation_cause"] == "recovered"


class TestExistingPathsStillLeaveTheCauseUnknown:
    def test_lifecycle_transitions_preserve_unknown(self) -> None:
        attempt = transition_attempt(Attempt(node_run_id="nr-1", ordinal=1), AttemptStatus.RUNNING)
        attempt = transition_attempt(attempt, AttemptStatus.CANCELLED, error="asked to stop")

        assert attempt.cancellation_cause is None
        assert "cancellation_cause" not in attempt.model_dump()
        assert set(attempt.model_dump()) == LEGACY_PAYLOAD_FIELDS

    def test_reclaim_writes_status_and_error_but_no_durable_cause(self) -> None:
        """Reclaim already lands on CANCELLED; it must not upgrade to a cause.

        Existing unknown-CANCELLED history is not reclassified by staging the
        field, and the reclaim path itself stays a status/error writer until a
        recovery leaf decides otherwise.
        """
        running = transition_attempt(Attempt(node_run_id="nr-1", ordinal=1), AttemptStatus.RUNNING)
        lease = ExecutionLease(
            node_run_id=running.node_run_id,
            attempt_id=running.attempt_id,
            lease_epoch=1,
            holder="quiet-executor",
        )
        leased = Attempt.model_validate({**running.model_dump(), "execution_lease": lease})

        reclaimed = reclaim_attempt(leased, at=datetime.now(UTC))

        assert reclaimed.status is AttemptStatus.CANCELLED
        assert reclaimed.cancellation_cause is None
        assert reclaimed.error is not None and "quiet-executor" in reclaimed.error
        assert "cancellation_cause" not in json.loads(reclaimed.model_dump_json())

    async def test_the_shared_consumer_claim_builder_leaves_the_cause_unknown(self) -> None:
        """The one builder every consumption path mints Attempts through."""
        project_store = InMemoryProjectScopeStore()
        root = await project_store.create_root("workspace-1")
        project = await project_store.create(
            workspace_id="workspace-1",
            parent_project_id=root.project_id,
            name="Project",
        )
        store = ClaimingInMemoryRunStore(project_store=project_store)
        graph = Graph(
            workspace_id=project.workspace_id,
            project_id=project.project_id,
            name="Pipeline",
            nodes=[Node(node_id="first", node_type="agent")],
        )
        run = await store.create_run(
            graph,
            actor_principal_id=DEFAULT_TEST_ACTOR_PRINCIPAL_ID,
            initial_status=RunStatus.QUEUED,
        )

        claim = await store.claim_consumer_run(
            run.run_id,
            node_id="first",
            runtime_id="python",
            executor_id="exec-1",
            lease_ttl=timedelta(seconds=60),
        )

        assert claim.attempt.cancellation_cause is None
        assert claim.attempt.execution_lease is not None
        assert set(claim.attempt.model_dump()) == LEGACY_PAYLOAD_FIELDS
        assert "cancellation_cause" not in json.loads(claim.attempt.model_dump_json())
