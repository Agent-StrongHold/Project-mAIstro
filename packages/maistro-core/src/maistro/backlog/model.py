"""Canonical BacklogItem: Workspace work-source and control-plane state (#82).

A BacklogItem is portfolio, work-source, acceptance and control-plane state for
one Workspace. It is deliberately *not* a Goal and not a scheduler:

- **Not a Goal.** The canonical Goal (Goal -> Graph -> Run -> NodeRun ->
  Attempt) owns desired outcomes and Agent ownership. A BacklogItem may link
  to a Goal by ``goal_id`` / ``goal_revision`` -- read-only references -- but
  claiming, closing or editing an item never writes canonical Goal state.
  Claim/lease coordinates *who may progress an item now*; it never reassigns
  a Goal's owning Agent.
- **Not an execution authority.** A claim is a lease on the *right to progress
  the item*, not a Run lease. Physical execution stays with the canonical
  spine; ``ExecutionLease``/``StaleExecutionFence`` are untouched.
- **Not RSI infrastructure.** This module imports nothing from
  ``maistro_rsi``; it is ordinary Workspace control-plane substrate consumed
  by humans, the persistent Workspace Agent, delegated Agents, and (later,
  optionally) #50.

Closure evidence is required before an item may reach a terminal status
(``done`` / ``rejected``), matching the rule the root ``BACKLOG.md`` gate
(``scripts/check-backlog-consistency.py``) already enforces on terminal
Markdown items. Until #102 performs the explicit authority cutover, the root
``BACKLOG.md`` stays canonical; this service is the structured state that
cutover will migrate into.

Three store implementations share one contract: the in-memory reference in
``maistro.backlog.store`` and its durable SQLite/PostgreSQL twins, read
against the same conformance suite. PostgreSQL tables are owned by Alembic
migration ``052_backlog_work_source`` -- a durable store never creates its own
schema (one schema owner; see ``maistro.workspaces.wiring``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _naive_as_utc(value: datetime) -> datetime:
    """A bare wall-clock value here means UTC, not the reading process's zone.

    Same rule as ``maistro.workspaces.model``: ``astimezone()`` on a naive
    datetime asks the platform to guess the zone it was written in, so the
    same stored row would decode to a different instant per reader.
    """

    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


class BacklogItemStatus(StrEnum):
    """Portfolio state of one work item.

    Distinct from any claim/lease state and from canonical Goal state: an
    item may be ``in_progress`` with no live claim (progress paused) and a
    claimed item's linked Goal is untouched.
    """

    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        return self in _TERMINAL_STATUSES


_TERMINAL_STATUSES = frozenset({BacklogItemStatus.DONE, BacklogItemStatus.REJECTED})

#: Statuses an item may move between through ordinary edits. Terminal statuses
#: are entered only through ``close_item`` (which requires closure evidence)
#: and left only through ``reopen_item`` -- both recorded decisions.
_MUTABLE_STATUSES = frozenset(
    {BacklogItemStatus.OPEN, BacklogItemStatus.IN_PROGRESS, BacklogItemStatus.BLOCKED}
)


class BacklogEventKind(StrEnum):
    """Provenance record kinds appended to an item's history.

    Every state change is a durable, attributed record (#101): the actor, the
    instant, and the item ``version`` the change produced. There is no edit
    path that bypasses the event log.
    """

    CREATED = "created"
    UPDATED = "updated"
    STATUS_CHANGED = "status_changed"
    DECOMPOSED = "decomposed"
    CLAIMED = "claimed"
    LEASE_EXTENDED = "lease_extended"
    CLAIM_RELEASED = "claim_released"
    CLOSED = "closed"
    REOPENED = "reopened"


class BacklogClosure(BaseModel):
    """Acceptance evidence recorded when an item reaches a terminal status.

    ``evidence_refs`` are opaque references the reviewer can resolve -- Run
    ids, spec/ADR paths, review links. Closure without at least one is the
    "done, trust me" state the closure-evidence rule exists to prevent.
    """

    model_config = ConfigDict(extra="forbid")

    summary: str
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    closed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("summary")
    @classmethod
    def _require_non_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("closure summary must be a non-empty string")
        return value

    @field_validator("evidence_refs")
    @classmethod
    def _require_resolvable_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not ref.strip() for ref in value):
            raise ValueError("evidence references must be non-empty strings")
        return value

    @model_validator(mode="after")
    def _normalize_closed_at(self) -> BacklogClosure:
        object.__setattr__(self, "closed_at", _naive_as_utc(self.closed_at))
        return self


class BacklogItem(BaseModel):
    """One unit of Workspace work: scope, risk, acceptance, and linkage.

    ``parent_id`` decomposes an item into children in the same Workspace.
    ``goal_id``/``goal_revision`` reference canonical Goal state read-only;
    nothing in this model writes or copies Goal ownership or lifecycle.
    ``version`` is the optimistic-concurrency counter: every mutation bumps
    it, and an edit against a stale version is refused rather than merged.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    workspace_id: str
    parent_id: str | None = None
    title: str
    details: str = ""
    status: BacklogItemStatus = BacklogItemStatus.OPEN
    tags: tuple[str, ...] = ()
    milestone: str | None = None
    package: str | None = None
    risk_notes: str = ""
    goal_id: str | None = None
    goal_revision: int | None = None
    source: str = "human"
    version: int = Field(default=1, ge=1)
    created_by: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    closure: BacklogClosure | None = None

    @field_validator("item_id", "workspace_id", "title", "created_by", "source")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @field_validator("tags")
    @classmethod
    def _clean_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Strip, drop empties, deduplicate preserving first-seen order."""
        cleaned: list[str] = []
        for tag in value:
            stripped = tag.strip()
            if stripped and stripped not in cleaned:
                cleaned.append(stripped)
        return tuple(cleaned)

    @field_validator("goal_revision")
    @classmethod
    def _require_positive_revision(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("goal_revision must be a positive integer")
        return value

    @model_validator(mode="after")
    def _enforce_consistency(self) -> BacklogItem:
        object.__setattr__(self, "created_at", _naive_as_utc(self.created_at))
        object.__setattr__(self, "updated_at", _naive_as_utc(self.updated_at))
        if self.status.is_terminal != (self.closure is not None):
            raise ValueError(
                "a terminal item (done/rejected) carries closure evidence; "
                "a non-terminal item carries none"
            )
        if self.parent_id is not None and self.parent_id == self.item_id:
            raise ValueError("an item cannot be its own parent")
        return self


class BacklogClaim(BaseModel):
    """A live lease on the right to progress one item.

    Exactly one unexpired, unreleased claim may exist per item. Holding a
    claim grants nothing by itself: authorization comes from the existing
    Workspace owners, and a claim never mutates the item's Goal linkage.
    """

    model_config = ConfigDict(extra="forbid")

    item_id: str
    claim_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    claimed_by: str
    claimed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    lease_expires_at: datetime
    released_at: datetime | None = None

    @field_validator("item_id", "claim_id", "claimed_by")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _normalize_timestamps(self) -> BacklogClaim:
        object.__setattr__(self, "claimed_at", _naive_as_utc(self.claimed_at))
        object.__setattr__(self, "lease_expires_at", _naive_as_utc(self.lease_expires_at))
        if self.released_at is not None:
            object.__setattr__(self, "released_at", _naive_as_utc(self.released_at))
        return self

    def is_active(self, *, at: datetime) -> bool:
        return self.released_at is None and self.lease_expires_at > at


class BacklogEvent(BaseModel):
    """One attributed, append-only history record for one item (#101)."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    item_id: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str
    kind: BacklogEventKind
    #: The item version this event produced (or observed, for claim events).
    item_version: int = Field(ge=1)
    payload: dict[str, object] = Field(default_factory=dict)

    @field_validator("event_id", "item_id", "actor")
    @classmethod
    def _require_non_blank_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _normalize_at(self) -> BacklogEvent:
        object.__setattr__(self, "at", _naive_as_utc(self.at))
        return self


class BacklogItemNotFound(KeyError):
    pass


class BacklogVersionConflict(ValueError):
    """An edit arrived against a stale ``expected_version``.

    Carries the store's current version so the loser can re-read and decide,
    rather than guess. The conflict is refused, never merged (#82: conflict /
    version handling).
    """

    def __init__(self, item_id: str, current_version: int) -> None:
        super().__init__(
            f"backlog item {item_id!r} is at version {current_version}; "
            "the edit carried a stale expected_version"
        )
        self.item_id = item_id
        self.current_version = current_version


class BacklogClaimError(RuntimeError):
    """The item already holds an active claim, held by ``claim``."""

    def __init__(self, item_id: str, claim: BacklogClaim) -> None:
        super().__init__(
            f"backlog item {item_id!r} is already claimed by {claim.claimed_by!r} "
            f"(claim {claim.claim_id}, lease until {claim.lease_expires_at.isoformat()})"
        )
        self.item_id = item_id
        self.claim = claim


class BacklogClosureError(ValueError):
    """Closure was attempted without the evidence the terminal state requires."""

    def __init__(self, item_id: str, reason: str) -> None:
        super().__init__(f"backlog item {item_id!r}: {reason}")
        self.item_id = item_id


__all__ = [
    "BacklogClaim",
    "BacklogClaimError",
    "BacklogClosure",
    "BacklogClosureError",
    "BacklogEvent",
    "BacklogEventKind",
    "BacklogItem",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogVersionConflict",
]
