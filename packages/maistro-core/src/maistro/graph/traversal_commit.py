"""Authoritative durable facts for logical Graph traversal state changes.

A :class:`TraversalCommit` represents authoritative graph *advancement* after
logical source visits have accepted physical outcomes. A
:class:`TraversalCheckpoint` represents a durable non-advancing state capture,
such as HITL/wait suspension, where requiring an accepted completed outcome
would erase the paused visit that caused the checkpoint.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from maistro.graph.execution_state import GraphEdgeDecision, GraphExecutionState
from maistro.runs.model import AcceptedNodeOutcome, RunStatus

_JSON_VALUE = TypeAdapter(object)


def _json_value(value: object) -> object:
    """Project arbitrary Pydantic-supported values into stable JSON-mode data."""
    return _JSON_VALUE.dump_python(value, mode="json")


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _same_json_value(left: object, right: object) -> bool:
    return json.dumps(
        _json_value(left), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ) == json.dumps(_json_value(right), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def graph_state_hash(state: GraphExecutionState) -> str:
    """Return a stable digest of the complete persisted traversal projection."""
    return _digest(state.model_dump(mode="json"))


def edge_decision_id(decision: GraphEdgeDecision) -> str:
    """Return stable identity for one visit-correlated routing decision."""
    return _digest(decision.model_dump(mode="json"))


def _base_accepted_outcome_payload(outcome: AcceptedNodeOutcome) -> dict[str, object]:
    """Return the pre-logical-projection identity payload for compatibility."""
    return {
        "node_run_id": outcome.node_run_id,
        "attempt_result": outcome.attempt_result.model_dump(mode="json"),
    }


def accepted_outcome_id(outcome: AcceptedNodeOutcome) -> str:
    """Return stable identity for accepted physical evidence and logical projection.

    Existing default COMPLETED projections retain the identity introduced by the
    TraversalCommit contract. Distinct logical dispositions or transformed
    logical result/error projections use an explicit v2 namespace. Acceptance
    wall-clock time remains excluded so crash reconstruction is idempotent.
    """
    physical = _base_accepted_outcome_payload(outcome)
    if (
        outcome.logical_status is RunStatus.COMPLETED
        and _same_json_value(outcome.result, outcome.attempt_result.result)
        and outcome.error == outcome.attempt_result.error
    ):
        return _digest(physical)
    return _digest(
        {
            "identity_version": 2,
            "physical": physical,
            "logical_status": outcome.logical_status.value,
            "logical_result": _json_value(outcome.result),
            "logical_error": outcome.error,
        }
    )


def _commit_identity(
    *,
    run_id: str,
    prior_commit_id: str | None,
    graph_snapshot_hash: str,
    prior_state_hash: str,
    ordered_source_node_run_ids: tuple[str, ...],
    accepted_outcome_ids: tuple[str, ...],
    edge_decision_ids: tuple[str, ...],
    resulting_frontier: tuple[str, ...],
    resulting_state_hash: str,
    checkpoint_id: str | None,
    commit_sequence: int,
) -> str:
    return _digest(
        {
            "run_id": run_id,
            "prior_commit_id": prior_commit_id,
            "graph_snapshot_hash": graph_snapshot_hash,
            "prior_state_hash": prior_state_hash,
            "ordered_source_node_run_ids": ordered_source_node_run_ids,
            "accepted_outcome_ids": accepted_outcome_ids,
            "edge_decision_ids": edge_decision_ids,
            "resulting_frontier": resulting_frontier,
            "resulting_state_hash": resulting_state_hash,
            "checkpoint_id": checkpoint_id,
            "commit_sequence": commit_sequence,
        }
    )


def _checkpoint_identity(
    *,
    run_id: str,
    graph_snapshot_hash: str,
    state_hash: str,
    ordered_source_node_run_ids: tuple[str, ...],
    checkpoint_id: str | None,
    checkpoint_sequence: int,
) -> str:
    return _digest(
        {
            "run_id": run_id,
            "graph_snapshot_hash": graph_snapshot_hash,
            "state_hash": state_hash,
            "ordered_source_node_run_ids": ordered_source_node_run_ids,
            "checkpoint_id": checkpoint_id,
            "checkpoint_sequence": checkpoint_sequence,
        }
    )


def _require_commit_identity(value: str) -> str:
    if not value.strip():
        raise ValueError("TraversalCommit identities and hashes must be non-empty")
    return value


def _require_commit_members(value: tuple[str, ...]) -> tuple[str, ...]:
    if any(not item.strip() for item in value):
        raise ValueError("TraversalCommit identity collections cannot contain empty values")
    return value


def _validate_commit_collections(
    *,
    source_ids: tuple[str, ...],
    outcome_ids: tuple[str, ...],
    decision_ids: tuple[str, ...],
    frontier: tuple[str, ...],
) -> None:
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source NodeRuns must appear once per TraversalCommit")
    if len(outcome_ids) != len(source_ids):
        raise ValueError("every advancing source NodeRun must contribute one accepted outcome")
    if len(outcome_ids) != len(set(outcome_ids)):
        raise ValueError("accepted outcomes must be unique per TraversalCommit")
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("edge decisions must be unique per TraversalCommit")
    if len(frontier) != len(set(frontier)):
        raise ValueError("resulting frontier must not contain duplicate nodes")


def _validate_commit_chain(commit_sequence: int, prior_commit_id: str | None) -> None:
    if commit_sequence == 1 and prior_commit_id is not None:
        raise ValueError("initial TraversalCommit cannot have a prior_commit_id")
    if commit_sequence > 1 and not prior_commit_id:
        raise ValueError("noninitial TraversalCommit requires prior_commit_id")


def _validate_transition_inputs(
    *,
    prior_state: GraphExecutionState,
    resulting_state: GraphExecutionState,
    ordered_source_node_run_ids: tuple[str, ...],
    accepted_outcomes: tuple[AcceptedNodeOutcome, ...],
    edge_decisions: tuple[GraphEdgeDecision, ...],
) -> None:
    if prior_state.run_id != resulting_state.run_id:
        raise ValueError("TraversalCommit cannot cross Run identity")
    outcome_node_runs = tuple(outcome.node_run_id for outcome in accepted_outcomes)
    if outcome_node_runs != ordered_source_node_run_ids:
        raise ValueError("accepted outcomes must match source NodeRuns in deterministic order")
    source_set = set(ordered_source_node_run_ids)
    if any(decision.source_node_run_id not in source_set for decision in edge_decisions):
        raise ValueError("routing decisions must come from this commit's source NodeRuns")
    prior_decisions = prior_state.edge_decisions
    resulting_decisions = resulting_state.edge_decisions
    if (
        len(resulting_decisions) < len(prior_decisions)
        or resulting_decisions[: len(prior_decisions)] != prior_decisions
    ):
        raise ValueError("resulting state must preserve prior routing-decision history")
    if resulting_decisions[len(prior_decisions) :] != edge_decisions:
        raise ValueError(
            "commit routing decisions must exactly match decisions added by transition"
        )


class TraversalCommit(BaseModel):
    """One accepted advancing transition between durable Graph traversal states."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    traversal_commit_id: str
    run_id: str
    prior_commit_id: str | None = None
    graph_snapshot_hash: str
    prior_state_hash: str
    ordered_source_node_run_ids: tuple[str, ...]
    accepted_outcome_ids: tuple[str, ...]
    edge_decision_ids: tuple[str, ...]
    resulting_frontier: tuple[str, ...]
    resulting_state_hash: str
    checkpoint_id: str | None = None
    commit_sequence: int = Field(ge=1)
    committed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator(
        "traversal_commit_id",
        "run_id",
        "graph_snapshot_hash",
        "prior_state_hash",
        "resulting_state_hash",
    )
    @classmethod
    def _non_empty_identity(cls, value: str) -> str:
        return _require_commit_identity(value)

    @field_validator(
        "ordered_source_node_run_ids",
        "accepted_outcome_ids",
        "edge_decision_ids",
        "resulting_frontier",
    )
    @classmethod
    def _non_empty_members(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _require_commit_members(value)

    @model_validator(mode="after")
    def _validate_cardinality_and_identity(self) -> TraversalCommit:
        _validate_commit_chain(self.commit_sequence, self.prior_commit_id)
        _validate_commit_collections(
            source_ids=self.ordered_source_node_run_ids,
            outcome_ids=self.accepted_outcome_ids,
            decision_ids=self.edge_decision_ids,
            frontier=self.resulting_frontier,
        )
        expected = _commit_identity(
            run_id=self.run_id,
            prior_commit_id=self.prior_commit_id,
            graph_snapshot_hash=self.graph_snapshot_hash,
            prior_state_hash=self.prior_state_hash,
            ordered_source_node_run_ids=self.ordered_source_node_run_ids,
            accepted_outcome_ids=self.accepted_outcome_ids,
            edge_decision_ids=self.edge_decision_ids,
            resulting_frontier=self.resulting_frontier,
            resulting_state_hash=self.resulting_state_hash,
            checkpoint_id=self.checkpoint_id,
            commit_sequence=self.commit_sequence,
        )
        if self.traversal_commit_id != expected:
            raise ValueError("TraversalCommit identity does not match its authoritative content")
        return self

    @classmethod
    def from_transition(
        cls,
        *,
        graph_snapshot_hash: str,
        prior_state: GraphExecutionState,
        resulting_state: GraphExecutionState,
        ordered_source_node_run_ids: tuple[str, ...],
        accepted_outcomes: tuple[AcceptedNodeOutcome, ...],
        edge_decisions: tuple[GraphEdgeDecision, ...],
        commit_sequence: int,
        prior_commit_id: str | None = None,
        checkpoint_id: str | None = None,
    ) -> TraversalCommit:
        """Construct a content-addressed commit from one complete advancing transition."""
        _validate_transition_inputs(
            prior_state=prior_state,
            resulting_state=resulting_state,
            ordered_source_node_run_ids=ordered_source_node_run_ids,
            accepted_outcomes=accepted_outcomes,
            edge_decisions=edge_decisions,
        )
        prior_hash = graph_state_hash(prior_state)
        outcome_ids = tuple(accepted_outcome_id(item) for item in accepted_outcomes)
        decision_ids = tuple(edge_decision_id(item) for item in edge_decisions)
        frontier = resulting_state.active_node_ids
        resulting_hash = graph_state_hash(resulting_state)
        commit_id = _commit_identity(
            run_id=prior_state.run_id,
            prior_commit_id=prior_commit_id,
            graph_snapshot_hash=graph_snapshot_hash,
            prior_state_hash=prior_hash,
            ordered_source_node_run_ids=ordered_source_node_run_ids,
            accepted_outcome_ids=outcome_ids,
            edge_decision_ids=decision_ids,
            resulting_frontier=frontier,
            resulting_state_hash=resulting_hash,
            checkpoint_id=checkpoint_id,
            commit_sequence=commit_sequence,
        )
        return cls(
            traversal_commit_id=commit_id,
            run_id=prior_state.run_id,
            prior_commit_id=prior_commit_id,
            graph_snapshot_hash=graph_snapshot_hash,
            prior_state_hash=prior_hash,
            ordered_source_node_run_ids=ordered_source_node_run_ids,
            accepted_outcome_ids=outcome_ids,
            edge_decision_ids=decision_ids,
            resulting_frontier=frontier,
            resulting_state_hash=resulting_hash,
            checkpoint_id=checkpoint_id,
            commit_sequence=commit_sequence,
        )


class TraversalCheckpoint(BaseModel):
    """Durable non-advancing traversal state caused by pause/wait/checkpointing.

    Unlike TraversalCommit, this fact does not claim that every source visit has
    an accepted completed outcome or that routing advanced. It preserves the
    exact paused/waiting logical visit identities that causally produced the
    durable state so HITL and wait recovery do not disappear from provenance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    traversal_checkpoint_id: str
    run_id: str
    graph_snapshot_hash: str
    state_hash: str
    ordered_source_node_run_ids: tuple[str, ...]
    checkpoint_id: str | None = None
    checkpoint_sequence: int = Field(ge=1)
    checkpointed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _validate_identity(self) -> TraversalCheckpoint:
        if (
            not self.run_id.strip()
            or not self.graph_snapshot_hash.strip()
            or not self.state_hash.strip()
        ):
            raise ValueError("TraversalCheckpoint identities and hashes must be non-empty")
        if any(not item.strip() for item in self.ordered_source_node_run_ids):
            raise ValueError("TraversalCheckpoint source NodeRun IDs cannot be empty")
        if len(self.ordered_source_node_run_ids) != len(set(self.ordered_source_node_run_ids)):
            raise ValueError("TraversalCheckpoint source NodeRuns must be unique")
        expected = _checkpoint_identity(
            run_id=self.run_id,
            graph_snapshot_hash=self.graph_snapshot_hash,
            state_hash=self.state_hash,
            ordered_source_node_run_ids=self.ordered_source_node_run_ids,
            checkpoint_id=self.checkpoint_id,
            checkpoint_sequence=self.checkpoint_sequence,
        )
        if self.traversal_checkpoint_id != expected:
            raise ValueError(
                "TraversalCheckpoint identity does not match its authoritative content"
            )
        return self

    @classmethod
    def from_state(
        cls,
        *,
        graph_snapshot_hash: str,
        state: GraphExecutionState,
        ordered_source_node_run_ids: tuple[str, ...],
        checkpoint_sequence: int,
        checkpoint_id: str | None = None,
    ) -> TraversalCheckpoint:
        state_hash = graph_state_hash(state)
        identity = _checkpoint_identity(
            run_id=state.run_id,
            graph_snapshot_hash=graph_snapshot_hash,
            state_hash=state_hash,
            ordered_source_node_run_ids=ordered_source_node_run_ids,
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=checkpoint_sequence,
        )
        return cls(
            traversal_checkpoint_id=identity,
            run_id=state.run_id,
            graph_snapshot_hash=graph_snapshot_hash,
            state_hash=state_hash,
            ordered_source_node_run_ids=ordered_source_node_run_ids,
            checkpoint_id=checkpoint_id,
            checkpoint_sequence=checkpoint_sequence,
        )


if TYPE_CHECKING:

    def _vulture_traversal_contract_usage(
        commit: TraversalCommit,
        checkpoint: TraversalCheckpoint,
    ) -> None:
        _ = commit.traversal_commit_id
        _ = commit.run_id
        _ = commit.prior_commit_id
        _ = commit.graph_snapshot_hash
        _ = commit.prior_state_hash
        _ = commit.ordered_source_node_run_ids
        _ = commit.accepted_outcome_ids
        _ = commit.edge_decision_ids
        _ = commit.resulting_frontier
        _ = commit.resulting_state_hash
        _ = commit.checkpoint_id
        _ = commit.commit_sequence
        _ = commit.committed_at
        _ = checkpoint.traversal_checkpoint_id
        _ = checkpoint.run_id
        _ = checkpoint.graph_snapshot_hash
        _ = checkpoint.state_hash
        _ = checkpoint.ordered_source_node_run_ids
        _ = checkpoint.checkpoint_id
        _ = checkpoint.checkpoint_sequence
        _ = checkpoint.checkpointed_at
        _ = TraversalCommit._non_empty_identity
        _ = TraversalCommit._non_empty_members
        _ = TraversalCommit._validate_cardinality_and_identity
        _ = TraversalCommit.from_transition
        _ = TraversalCheckpoint.from_state

    _: object
    _ = _vulture_traversal_contract_usage
    _ = _base_accepted_outcome_payload
    _ = _json_value
    _ = _same_json_value


__all__ = [
    "TraversalCheckpoint",
    "TraversalCommit",
    "accepted_outcome_id",
    "edge_decision_id",
    "graph_state_hash",
]
