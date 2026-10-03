"""Recording BacklogItem history: the semantics the acceptance needs (#101).

These helpers are the difference between "a journal exists" and "history is
auditable": each one knows which entry kind a fact is, what it must carry, and
what may never happen — a completion without evidence, a discovered
prerequisite that widens scope instead of entering as PROPOSED, a parent whose
acceptance criteria disappear inside a decomposition.

Everything canonical stays a reference: Goals by exact identity/revision
(#458), execution by Run/NodeRun/Attempt ids, reconciliation by decision_ref.
Nothing here drives execution; the only write is the append.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, StrictStr, model_validator

from maistro.workspaces.backlog_history.model import (
    DISCOVERED_INITIAL_STATUS,
    BacklogHistoryError,
    BacklogHistoryEvent,
    BacklogHistoryEventKind,
    ClosureEvidenceMissing,
    FieldChange,
    GoalLink,
    ReconciliationReference,
    RunReference,
)
from maistro.workspaces.backlog_history.store import BacklogHistoryStore


class BacklogSubject(BaseModel):
    """The (workspace, project, item) identity every entry is filed under."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: StrictStr
    project_id: StrictStr
    item_id: StrictStr

    @model_validator(mode="after")
    def _non_empty(self) -> BacklogSubject:
        for name in ("workspace_id", "project_id", "item_id"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        return self


def _unchanged(value: Sequence[str]) -> FieldChange:
    """An explicit 'this was exactly the list when the entry was written'."""
    return FieldChange(field="acceptance_refs", before=list(value), after=list(value))


async def item_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    source_ref: str | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """The item exists: the journal's first entry, with its provenance."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.ITEM_RECORDED,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
            source_ref=source_ref,
        ),
    )


async def fields_changed(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """Record field-level edits as before/after pairs, so a rewrite of, say,
    the parent's acceptance criteria is a visible event, never a silent one."""
    changed = [
        FieldChange(field=name, before=before.get(name), after=after.get(name))
        for name in sorted(set(before) | set(after))
        if before.get(name) != after.get(name)
    ]
    if not changed:
        raise BacklogHistoryError("fields_changed with no difference is not history")
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.FIELDS_CHANGED,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
            changed_fields=tuple(changed),
        ),
    )


async def status_moved(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    from_status: str,
    to_status: str,
    reason: str | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """A BACKLOG.md legend move, recorded with both ends."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.STATUS_MOVED,
            from_status=from_status,
            to_status=to_status,
            reason=reason,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


_CLAIM_FIELDS = ("claimant_principal_id", "claimant_agent_id", "claim_run_id", "fence_token")


async def claim_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    claimant_principal_id: str | None = None,
    claimant_agent_id: str | None = None,
    claim_run_id: str | None = None,
    fence_token: int | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """A claim (#100's reserved fields) was taken on the item."""
    claimed = {
        "claimant_principal_id": claimant_principal_id,
        "claimant_agent_id": claimant_agent_id,
        "claim_run_id": claim_run_id,
        "fence_token": fence_token,
    }
    set_fields = {name: value for name, value in claimed.items() if value is not None}
    if not set_fields:
        raise BacklogHistoryError("claim_recorded without a claim records nothing")
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.CLAIM_RECORDED,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            changed_fields=tuple(
                FieldChange(field=name, before=None, after=value)
                for name, value in set_fields.items()
            ),
        ),
    )


async def claim_released(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    previous: Mapping[str, Any],
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """The claim was released; `previous` holds what it cleared."""
    released = {name: previous[name] for name in _CLAIM_FIELDS if previous.get(name) is not None}
    if not released:
        raise BacklogHistoryError("claim_released without a previous claim records nothing")
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.CLAIM_RELEASED,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            changed_fields=tuple(
                FieldChange(field=name, before=value, after=None)
                for name, value in released.items()
            ),
        ),
    )


async def blocker_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    blocker_reason: str,
    waiting_on: str | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """The item is blocked; `waiting_on` names what it waits for (e.g. a human)."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.BLOCKER_RECORDED,
            blocker_reason=blocker_reason,
            waiting_on=waiting_on,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


async def blocker_cleared(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    summary: str = "",
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.BLOCKER_CLEARED,
            summary=summary,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


async def progress_noted(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    note: str,
    evidence_refs: Sequence[str] = (),
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """Partial progress on an open item. Progress is never closure: this entry
    implies no status, so the parent stays open until evidence says otherwise."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.PROGRESS_NOTED,
            summary=note,
            evidence_refs=tuple(evidence_refs),
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


async def decomposition_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    child_item_ids: Sequence[str],
    parent_acceptance_refs: Sequence[str],
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """A large item was decomposed into children.

    The receipt carries the parent's acceptance criteria *as they were*: the
    split must not rewrite what the parent was accepted to deliver, and any
    later change to that list is a separate, visible `fields_changed` entry.
    """
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.DECOMPOSITION_RECORDED,
            child_item_ids=tuple(child_item_ids),
            changed_fields=(_unchanged(parent_acceptance_refs),),
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
        ),
    )


async def discovered_work_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    child_item_ids: Sequence[str],
    discovered_by_run_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """A prerequisite or defect was discovered while working the item.

    The children enter as PROPOSED — recorded scope, not silently widened
    scope; `discovered_by_run_id` points at the Run that found them.
    """
    run_refs = () if discovered_by_run_id is None else (RunReference(run_id=discovered_by_run_id),)
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.DISCOVERED_WORK_RECORDED,
            child_item_ids=tuple(child_item_ids),
            child_initial_status=DISCOVERED_INITIAL_STATUS,
            run_refs=run_refs,
            actor_agent_id=actor_agent_id,
            summary=summary,
        ),
    )


async def goal_bound(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    goal_id: str,
    goal_revision: str | int,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """The item was linked to a canonical Goal by exact identity/revision."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.GOAL_BOUND,
            goal_link=GoalLink(goal_id=goal_id, goal_revision=goal_revision),
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
        ),
    )


async def reconciliation_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    decision_ref: str,
    outcome: str | None = None,
    reason: str | None = None,
    goal_id: str | None = None,
    goal_revision: str | int | None = None,
    run_refs: Sequence[RunReference] = (),
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """A reconciliation decision touched the item; the decision stays where it
    was made, the journal keeps the pointer and the outcome.

    A Goal is linked only by its exact (goal_id, goal_revision) identity
    (#458): supplying one half without the other is rejected, never silently
    dropped — a partial pair must not become a link-less journal entry.
    """
    if (goal_id is None) != (goal_revision is None):
        raise BacklogHistoryError(
            "reconciliation_recorded needs goal_id and goal_revision together "
            "(the exact Goal identity) or neither — a partial pair is rejected"
        )
    # The guard above leaves the pair both-set or both-None; testing both
    # sides narrows the Optional for the type checker without restating the
    # guard as an assert.
    goal_link: GoalLink | None = (
        None
        if goal_id is None or goal_revision is None
        else GoalLink(goal_id=goal_id, goal_revision=goal_revision)
    )
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.RECONCILIATION_RECORDED,
            reconciliation=ReconciliationReference(
                decision_ref=decision_ref, outcome=outcome, reason=reason
            ),
            goal_link=goal_link,
            run_refs=tuple(run_refs),
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


async def run_evidence_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    run_refs: Sequence[RunReference] = (),
    evaluation_refs: Sequence[str] = (),
    reason: str | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """Graph/Run/evaluation evidence was attached to the item.

    `reason` is where "why a later Run/replan was required" lives. This entry
    alone never closes anything: evidence is attached, closure is decided
    against the item's acceptance (and Goal conditions, where linked).
    """
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.RUN_EVIDENCE_RECORDED,
            run_refs=tuple(run_refs),
            evaluation_refs=tuple(evaluation_refs),
            reason=reason,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
        ),
    )


async def closure_recorded(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    evidence_refs: Sequence[str],
    run_refs: Sequence[RunReference] = (),
    evaluation_refs: Sequence[str] = (),
    to_status: str | None = None,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
    summary: str = "",
) -> BacklogHistoryEvent:
    """Completion, recorded against evidence.

    `evidence_refs` is mandatory — the acceptance criteria (and, where the
    item is linked, the canonical Goal success/stop conditions) decide
    completion; a Run that reported success is supporting evidence at best and
    is never sufficient alone. `to_status` records the legend move this
    closure justifies; it is a receipt, not the move itself.
    """
    if not evidence_refs:
        raise ClosureEvidenceMissing(
            f"BacklogItem {subject.item_id} cannot be closed without evidence_refs; "
            "a completed Run is not closure evidence by itself"
        )
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.CLOSURE_RECORDED,
            evidence_refs=tuple(evidence_refs),
            run_refs=tuple(run_refs),
            evaluation_refs=tuple(evaluation_refs),
            to_status=to_status,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
            summary=summary,
        ),
    )


async def reopened(
    store: BacklogHistoryStore,
    subject: BacklogSubject,
    *,
    reason: str,
    actor_principal_id: str | None = None,
    actor_agent_id: str | None = None,
) -> BacklogHistoryEvent:
    """A closed item was reopened; the reason is mandatory."""
    return await store.append(
        BacklogHistoryEvent(
            workspace_id=subject.workspace_id,
            project_id=subject.project_id,
            item_id=subject.item_id,
            kind=BacklogHistoryEventKind.REOPENED,
            reason=reason,
            actor_principal_id=actor_principal_id,
            actor_agent_id=actor_agent_id,
        ),
    )


if TYPE_CHECKING:

    def _vulture_pydantic_contract_usage() -> None:
        """Keep pydantic-owned surface visible to the production-only scan.

        ``BacklogSubject._non_empty`` is a ``@model_validator`` hook pydantic
        invokes during validation, never a traceable in-package call, and a
        brand-new per-identity ledger bank cannot self-authorize against the
        trusted base — see ``maistro.workspaces.backlog_history.model``'s
        shim for the full situation.
        """
        _ = (BacklogSubject._non_empty,)

    _ = _vulture_pydantic_contract_usage


__all__ = [
    "BacklogSubject",
    "blocker_cleared",
    "blocker_recorded",
    "claim_recorded",
    "claim_released",
    "closure_recorded",
    "decomposition_recorded",
    "discovered_work_recorded",
    "fields_changed",
    "goal_bound",
    "item_recorded",
    "progress_noted",
    "reconciliation_recorded",
    "reopened",
    "run_evidence_recorded",
    "status_moved",
]
