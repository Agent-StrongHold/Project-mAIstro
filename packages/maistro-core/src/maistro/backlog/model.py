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
migration ``059_backlog_work_source`` -- a durable store never creates its own
schema (one schema owner; see ``maistro.workspaces.wiring``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _naive_as_utc(value: datetime) -> datetime:
    """A bare wall-clock value here means UTC, not the reading process's zone.

    Same rule as ``maistro.workspaces.model``: ``astimezone()`` on a naive
    datetime asks the platform to guess the zone it was written in, so the
    same stored row would decode to a different instant per reader.
    """

    return value if value.utcoffset() is not None else value.replace(tzinfo=UTC)


class BacklogItemStatus:
    """Portfolio state vocabulary of one work item.

    Deliberately NOT a typed Literal/Enum work-state ladder (#101 convention;
    same resolution the Conductor backlog surface took in #99): the documented
    legend is the vocabulary and code carries it as boundary-validated opaque
    strings, so a planning surface cannot fork a second execution lifecycle —
    the execution-lifecycles ledger counts this as zero new vocabularies.
    Membership is fail-closed at the boundary: the ``status`` field validator
    on :class:`BacklogItem`, :func:`require_valid_status` and the stores' own
    status filters refuse unknown values, which is the enforcement an Enum
    provided without the second vocabulary.

    Distinct from any claim/lease state and from canonical Goal state: an
    item may be ``in_progress`` with no live claim (progress paused) and a
    claimed item's linked Goal is untouched.
    """

    OPEN: Final = "open"
    IN_PROGRESS: Final = "in_progress"
    BLOCKED: Final = "blocked"
    DONE: Final = "done"
    REJECTED: Final = "rejected"


_ALL_STATUSES = frozenset(
    {
        BacklogItemStatus.OPEN,
        BacklogItemStatus.IN_PROGRESS,
        BacklogItemStatus.BLOCKED,
        BacklogItemStatus.DONE,
        BacklogItemStatus.REJECTED,
    }
)

_TERMINAL_STATUSES = frozenset({BacklogItemStatus.DONE, BacklogItemStatus.REJECTED})

#: Statuses an item may move between through ordinary edits. Terminal statuses
#: are entered only through ``close_item`` (which requires closure evidence)
#: and left only through ``reopen_item`` -- both recorded decisions.
_MUTABLE_STATUSES = frozenset(
    {BacklogItemStatus.OPEN, BacklogItemStatus.IN_PROGRESS, BacklogItemStatus.BLOCKED}
)


def status_is_terminal(status: str) -> bool:
    """Whether ``status`` is a terminal outcome (entered only via close_item)."""
    return status in _TERMINAL_STATUSES


def require_valid_status(status: str) -> str:
    """Fail closed on a status the documented vocabulary does not define."""
    if status not in _ALL_STATUSES:
        raise ValueError(
            f"unknown backlog status {status!r}; expected one of: "
            + ", ".join(sorted(_ALL_STATUSES))
        )
    return status


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


class BacklogOrigin(BaseModel):
    """Provenance of an item imported from the Markdown backlog (#102).

    The root ``BACKLOG.md`` is the hand-maintained authority until the
    cutover; after it, the database is authoritative and the Markdown file is
    generated. ``BacklogOrigin`` is what makes that reversible and the export
    deterministic: it carries the item's position in the document and the
    Markdown-vocabulary status word verbatim, so the generated file renders
    every imported item exactly as it was written, while ``BacklogItem.status``
    carries the structured open/closed projection.

    ``body`` lines are stored verbatim (whitespace included): they are the
    item's acceptance criteria, evidence and prose as written, and the export
    must not editorialize them.
    """

    model_config = ConfigDict(extra="forbid")

    #: Which document the item was imported from (e.g. ``BACKLOG.md``).
    document: str
    #: The top-level ``## `` heading the item sits under.
    section: str
    #: The ``### `` heading, when the section has one.
    subsection: str | None = None
    #: Position of the item among the document's items (0-based, import order).
    order: int = Field(ge=0)
    #: The status legend word, verbatim ("Proposed", "Implemented", ...).
    status_word: str
    #: The ``gap-*`` marker from the status, when present.
    gap_marker: str | None = None
    #: The milestone suffix, when present.
    milestone_text: str | None = None
    #: Text after the closing ``**`` on the header line (e.g. a trailing
    #: "Blocked-by" annotation). It renders back on the header line.
    header_suffix: str | None = None
    #: The item's non-header lines, verbatim, in document order.
    body: tuple[str, ...] = ()

    @field_validator("document", "status_word")
    @classmethod
    def _require_non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must be a non-empty string")
        return value

    # ``section`` is deliberately allowed to be empty: an item above the
    # first ``## `` heading sits in the document preamble, and that is a
    # real position, not missing data.


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
    status: str = BacklogItemStatus.OPEN
    tags: tuple[str, ...] = ()
    milestone: str | None = None
    package: str | None = None
    risk_notes: str = ""
    goal_id: str | None = None
    goal_revision: int | None = None
    #: Stable ids of items this item is blocked by (``blocked-by:`` in the
    #: Markdown backlog). Order is the document's order; duplicates are
    #: dropped. Referential integrity is enforced at the store/service layer,
    #: not here: the model is data, the graph check is a decision.
    dependencies: tuple[str, ...] = ()
    #: Explicit human priority: 1 is highest, 5 is lowest. Stored as given,
    #: never rewritten by the system (SPEC-092626-1831) — an agent's
    #: "what should I work on" selection is deterministic on this plus rank,
    #: and a human re-prioritizing is what changes the answer.
    priority: int = Field(default=3, ge=1, le=5)
    #: Manual ordering within a priority band; selection's tiebreaker.
    rank: float = 1000.0
    #: Import provenance for items that came from the Markdown backlog (#102).
    #: ``None`` for items created natively in the database.
    origin: BacklogOrigin | None = None
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

    @field_validator("status")
    @classmethod
    def _status_is_a_defined_value(cls, value: str) -> str:
        """Fail closed on a status the documented vocabulary does not define."""
        return require_valid_status(value)

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

    @field_validator("dependencies")
    @classmethod
    def _clean_dependencies(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Same hygiene as tags: strip, drop empties, dedup, keep order."""
        cleaned: list[str] = []
        for dep in value:
            stripped = dep.strip()
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
        if status_is_terminal(self.status) != (self.closure is not None):
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
    "BacklogOrigin",
    "BacklogVersionConflict",
]
