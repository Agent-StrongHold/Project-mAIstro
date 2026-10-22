"""BacklogItem — the canonical backlog record for Conductor work (#98 shape).

The board/list/detail UI (#99) is a client of the service in
``services.backlog``; this model is what that service stores and returns.
Field vocabulary follows SPEC-092626-1831: an item carries an explicit human
priority kept separate from any system selection score, exactly one autonomy
mode, durable operator controls (pin-next, pause, park-with-evidence via
``blocked_reason``), goal linkage by reference, and per-change provenance.

The model deliberately does NOT copy Goal ownership or lifecycle: ``goal_id``
and ``goal_revision`` are references, per ADR-092626-c1e7 invariant 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Autonomy modes, verbatim from SPEC-092626-1831. The spec leaves the default
#: open (Q2); this service picks ``human-review-required`` as the fail-safe
#: default — a human reviews before an item counts as done — and records that
#: choice here so #103's campaign work inherits one vocabulary.
AutonomyMode = Literal[
    "autonomous",
    "autonomous-with-promotion-approval",
    "human-review-required",
    "human-only",
]
AUTONOMY_MODES: tuple[str, ...] = (
    "autonomous",
    "autonomous-with-promotion-approval",
    "human-review-required",
    "human-only",
)
DEFAULT_AUTONOMY_MODE: AutonomyMode = "human-review-required"

#: Board columns, as runtime-validated data. Deliberately NOT a typed
#: Literal/Enum work-state ladder (#101 convention): the documented legend
#: stays the item's status vocabulary and code carries it as opaque,
#: boundary-validated strings, so a planning surface cannot fork a second
#: execution lifecycle (SPEC-092626-1831 — an item references Goal/Run
#: state, never copies it; the execution-lifecycles ledger counts this as
#: zero new vocabularies). Membership is fail-closed at the boundary: the
#: validator below and the same check in services.backlog refuse unknown
#: values, which is the enforcement the Literal provided without the
#: second vocabulary.
BACKLOG_STATUSES: tuple[str, ...] = ("todo", "in_progress", "blocked", "done")
DEFAULT_BACKLOG_STATUS = "todo"

RiskLevel = Literal["low", "medium", "high"]
RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high")


class ProvenanceEntry(BaseModel):
    """One attributed change. Every mutation appends exactly one entry."""

    model_config = ConfigDict(extra="ignore")

    actor: str
    action: str
    at: datetime
    detail: dict[str, Any] = {}


class BacklogItem(BaseModel):
    # validate_assignment: mutations go through ``setattr`` in the service;
    # every assignment is re-validated so a bad enum or out-of-range priority
    # is refused at the boundary instead of stored.
    model_config = ConfigDict(extra="ignore", validate_assignment=True)

    id: str
    title: str = Field(min_length=1, max_length=300)
    description: str = ""
    status: str = DEFAULT_BACKLOG_STATUS

    #: Explicit human priority: stored as given, never rewritten by the system
    #: (SPEC-092626-1831). 1 is highest, 5 is lowest.
    priority: int = Field(default=3, ge=1, le=5)
    #: Manual ordering inside a board column; reorder writes it explicitly.
    rank: float = 1000.0

    #: Operator controls — durable, attributed, and cleared the same way.
    pinned: bool = False
    paused: bool = False
    paused_reason: str | None = None

    archived: bool = False
    #: Why the item was parked/blocked. Evidence, per the campaign spec.
    blocked_reason: str | None = None

    #: Decomposition: a parent references its children; children carry parent_id.
    parent_id: str | None = None
    dependencies: list[str] = []

    #: Inspection fields required by #99's detail view.
    acceptance_evidence: str = ""
    source: str = ""
    risk: RiskLevel = "medium"
    autonomy_mode: AutonomyMode = DEFAULT_AUTONOMY_MODE

    #: Linked canonical Goal — a reference, never an owned copy.
    goal_id: str | None = None
    goal_revision: int | None = None

    #: Authorization scope. A personal item has no workspace and answers only
    #: to its owner; a workspace item answers to its Workspace membership.
    owner_id: str
    workspace_id: str | None = None

    #: Optimistic concurrency. Every mutation bumps this; a write that names a
    #: stale version is refused with the current copy attached (recoverable).
    version: int = 1

    #: Appended per mutation, oldest first, capped by the service.
    provenance: list[ProvenanceEntry] = []

    created_at: datetime
    updated_at: datetime

    @field_validator("status")
    @classmethod
    def _status_is_a_legend_value(cls, value: str) -> str:
        """Fail closed on a status the documented legend does not define."""
        if value not in BACKLOG_STATUSES:
            raise ValueError(
                f"unknown backlog status {value!r}; expected one of: " + ", ".join(BACKLOG_STATUSES)
            )
        return value
