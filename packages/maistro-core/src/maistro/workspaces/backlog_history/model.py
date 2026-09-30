"""The Workspace BacklogItem history record (#101).

A `BacklogHistoryEvent` is an append-only receipt about a BacklogItem: who
changed what, when, and which canonical evidence justifies it. It is *not* a
second execution lifecycle — execution stays `Goal -> Graph -> Run ->
NodeRun -> Attempt` (ADR-081226-a66b); a history event only *references* Runs,
Goals and reconciliation decisions by their canonical identity, it never
copies their state or re-derives it. The event kinds below name audit
categories in a journal, not work states: nothing here schedules, executes, or
transitions anything.

Closure is the guarded case: recording a completion without evidence refs is
refused outright, and a Run reference — even a Run that reported success — is
never sufficient by itself (ADR-082426-19ed: a Run cannot claim success over a
failed node; ADR-083026-12f7: a run record declares what it reports). Evidence
is what the acceptance criteria and, where linked, the canonical Goal
success/stop conditions accept; the model enforces only that it was named.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from maistro.interop import INTEROP_ONTOLOGY_V1, InteropContractError

#: The initial status a discovered child item enters with (#101): discovered
#: prerequisites and defects become PROPOSED work — they may widen the tree of
#: candidate work, never the scope of the item that discovered them.
DISCOVERED_INITIAL_STATUS = "proposed"


def _as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class BacklogHistoryEventKind(StrEnum):
    """Audit categories of the append-only BacklogItem journal (#101).

    These name *journal entries*, not work states: no value here is, or may
    become, an execution lifecycle. The BACKLOG.md status legend itself stays
    the item's status vocabulary — history events carry it only as opaque
    `from_status`/`to_status` strings, so this module never forks it.
    """

    ITEM_RECORDED = "item_recorded"
    FIELDS_CHANGED = "fields_changed"
    STATUS_MOVED = "status_moved"
    CLAIM_RECORDED = "claim_recorded"
    CLAIM_RELEASED = "claim_released"
    BLOCKER_RECORDED = "blocker_recorded"
    BLOCKER_CLEARED = "blocker_cleared"
    PROGRESS_NOTED = "progress_noted"
    DECOMPOSITION_RECORDED = "decomposition_recorded"
    DISCOVERED_WORK_RECORDED = "discovered_work_recorded"
    GOAL_BOUND = "goal_bound"
    RECONCILIATION_RECORDED = "reconciliation_recorded"
    RUN_EVIDENCE_RECORDED = "run_evidence_recorded"
    CLOSURE_RECORDED = "closure_recorded"
    REOPENED = "reopened"


class GoalLink(BaseModel):
    """An exact (goal_id, goal_revision) pointer to the canonical Goal (#458).

    A reference, never a copy: the Goal's outcome, accountability and
    lifecycle stay owned by `maistro.goals`. Validated against the published
    interop ontology so a history event can only point at a Goal the way the
    ontology says a Goal is identified.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: StrictStr
    goal_revision: StrictStr | StrictInt

    @model_validator(mode="after")
    def _canonical(self) -> GoalLink:
        try:
            INTEROP_ONTOLOGY_V1.validate_projection("Goal", self.model_dump())
        except InteropContractError as exc:
            raise ValueError(str(exc)) from exc
        return self


class RunReference(BaseModel):
    """A pointer to canonical execution evidence: Run, and optionally the
    NodeRun/Attempt inside it that produced what the entry cites."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: StrictStr
    node_run_id: str | None = None
    attempt_id: str | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> RunReference:
        if not self.run_id.strip():
            raise ValueError("run_id must be a non-empty string")
        return self


class ReconciliationReference(BaseModel):
    """A pointer to a reconciliation decision and its outcome.

    `decision_ref` names the reconciliation record (Goal/Backlog reconciler
    output, #804/#805/#806 consumers); `reason` says why a later Run or replan
    was required. The decision itself stays wherever it was recorded.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_ref: StrictStr
    outcome: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _non_empty(self) -> ReconciliationReference:
        if not self.decision_ref.strip():
            raise ValueError("decision_ref must be a non-empty string")
        return self


class FieldChange(BaseModel):
    """One field's before/after pair, so an edit is auditable without
    reconstructing it from payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: StrictStr
    before: Any = None
    after: Any = None

    @model_validator(mode="after")
    def _non_empty(self) -> FieldChange:
        if not self.field.strip():
            raise ValueError("field must be a non-empty string")
        return self


class BacklogHistoryEvent(BaseModel):
    """One append-only entry in a BacklogItem's history.

    Everything canonical is a reference: `goal_link` points at the Goal,
    `run_refs` at Runs, `evaluation_refs` at evaluation Runs, `reconciliation`
    at a reconciliation decision, `evidence_refs` at whatever artifacts the
    item's acceptance accepts. The store assigns `sequence` per
    (workspace, item); callers never set it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workspace_id: StrictStr
    project_id: StrictStr
    item_id: StrictStr
    kind: BacklogHistoryEventKind
    #: Store-assigned per (workspace_id, item_id), starting at 1. ``None``
    #: only before `append` persists the event.
    sequence: int | None = Field(default=None, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor_principal_id: str | None = None
    actor_agent_id: str | None = None
    summary: str = ""
    from_status: str | None = None
    to_status: str | None = None
    changed_fields: tuple[FieldChange, ...] = ()
    goal_link: GoalLink | None = None
    run_refs: tuple[RunReference, ...] = ()
    evaluation_refs: tuple[str, ...] = ()
    reconciliation: ReconciliationReference | None = None
    evidence_refs: tuple[str, ...] = ()
    child_item_ids: tuple[str, ...] = ()
    #: Only DISCOVERED_WORK_RECORDED sets this, and only to
    #: `DISCOVERED_INITIAL_STATUS`: discovered work enters as PROPOSED.
    child_initial_status: str | None = None
    blocker_reason: str | None = None
    waiting_on: str | None = None
    reason: str | None = None
    #: Where the item came from: a source BacklogItem id, spec id, or scenario
    #: id — the provenance every autonomous artifact must carry (#101).
    source_ref: str | None = None

    @model_validator(mode="after")
    def _identities(self) -> BacklogHistoryEvent:
        for name in ("workspace_id", "project_id", "item_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        object.__setattr__(self, "occurred_at", _as_utc(self.occurred_at))
        return self

    @model_validator(mode="after")
    def _status_shape(self) -> BacklogHistoryEvent:
        if self.kind is not BacklogHistoryEventKind.STATUS_MOVED:
            return self
        if not self.from_status or not self.to_status:
            raise ValueError("status_moved events need from_status and to_status")
        if self.from_status == self.to_status:
            raise ValueError("status_moved needs two different statuses")
        return self

    @model_validator(mode="after")
    def _recorded_facts(self) -> BacklogHistoryEvent:
        """Per-kind payloads of the item's own story: closure, splits, finds.

        Every check is kind-specific and one event carries exactly one kind,
        so the guards are mutually exclusive and the split across this and
        `_linked_facts` below cannot reorder which refusal an event meets.
        """
        if self.kind is BacklogHistoryEventKind.CLOSURE_RECORDED and (
            not self.evidence_refs or any(not ref.strip() for ref in self.evidence_refs)
        ):
            raise ValueError(
                "closure_recorded requires non-blank evidence_refs: completion is "
                "evidence-driven, "
                "never a model assertion and never merely a Run that reported success"
            )
        if self.kind is BacklogHistoryEventKind.DECOMPOSITION_RECORDED and not self.child_item_ids:
            raise ValueError("decomposition_recorded requires child_item_ids")
        if self.kind is BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED:
            self._require_discovered_shape()
        return self

    @model_validator(mode="after")
    def _linked_facts(self) -> BacklogHistoryEvent:
        """Per-kind payloads that point at canonical state: Goals,
        reconciliation decisions, Run/evaluation evidence."""
        if self.kind is BacklogHistoryEventKind.GOAL_BOUND and self.goal_link is None:
            raise ValueError("goal_bound requires goal_link")
        if self.kind is BacklogHistoryEventKind.RECONCILIATION_RECORDED and (
            self.reconciliation is None
        ):
            raise ValueError("reconciliation_recorded requires reconciliation")
        if self.kind is BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED and not (
            self.run_refs or self.evaluation_refs
        ):
            raise ValueError("run_evidence_recorded requires run_refs or evaluation_refs")
        return self

    def _require_discovered_shape(self) -> None:
        if not self.child_item_ids:
            raise ValueError("discovered_work_recorded requires child_item_ids")
        if self.child_initial_status is not None and (
            self.child_initial_status != DISCOVERED_INITIAL_STATUS
        ):
            raise ValueError(
                f"discovered work enters as {DISCOVERED_INITIAL_STATUS!r}, not "
                f"{self.child_initial_status!r}"
            )

    @model_validator(mode="after")
    def _reasoned_facts(self) -> BacklogHistoryEvent:
        if self.kind is BacklogHistoryEventKind.BLOCKER_RECORDED and (
            not self.blocker_reason or not self.blocker_reason.strip()
        ):
            raise ValueError("blocker_recorded requires blocker_reason")
        if self.kind is BacklogHistoryEventKind.REOPENED and (
            not self.reason or not self.reason.strip()
        ):
            raise ValueError("reopened requires reason")
        return self


if TYPE_CHECKING:

    def _vulture_pydantic_contract_usage() -> None:
        """Keep pydantic-owned surface visible to the production-only scan.

        The ``@model_validator`` hooks are invoked by pydantic during
        validation, never by a traceable in-package call, and a brand-new
        per-identity ledger bank cannot self-authorize against the trusted
        base — the same situation the ``maistro.types.config`` and
        ``maistro.scheduling.admission`` shims document. ``changed_fields``
        is the before/after payload the API serializes for the wire, the
        durable journal round-trips via ``model_dump_json``, and the tests
        read back; none of those readers lies inside ``packages/*/src``.
        """
        _ = (
            GoalLink._canonical,
            RunReference._non_empty,
            ReconciliationReference._non_empty,
            FieldChange._non_empty,
            BacklogHistoryEvent._status_shape,
            BacklogHistoryEvent._recorded_facts,
            BacklogHistoryEvent._linked_facts,
            BacklogHistoryEvent._reasoned_facts,
            BacklogHistoryEvent.changed_fields,
        )

    _ = _vulture_pydantic_contract_usage


class BacklogHistoryError(ValueError):
    """Base class for history-layer refusals."""


class ClosureEvidenceMissing(BacklogHistoryError):
    """A completion was asserted without evidence; it is not recorded."""


class BacklogEventAlreadyExists(BacklogHistoryError):
    """The event_id is already in the journal; history is append-only."""


__all__ = [
    "DISCOVERED_INITIAL_STATUS",
    "BacklogEventAlreadyExists",
    "BacklogHistoryError",
    "BacklogHistoryEvent",
    "BacklogHistoryEventKind",
    "ClosureEvidenceMissing",
    "FieldChange",
    "GoalLink",
    "ReconciliationReference",
    "RunReference",
]
