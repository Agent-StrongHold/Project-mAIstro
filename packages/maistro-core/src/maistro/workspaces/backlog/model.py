"""The Workspace BacklogItem record (#98).

A BacklogItem is durable work-source state: what someone -- a human, the
persistent Workspace Agent, a delegated Agent, later RSI -- may pick up next.
It is not a Goal. A Goal is desired-outcome/accountability state owned by
`maistro.goals` (#458); an item may point at one, by exact identity and
revision, but never copies the outcome into a second field family.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from maistro.interop import INTEROP_ONTOLOGY_V1, InteropContractError


def _as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class BacklogItemStatus(StrEnum):
    """The BACKLOG.md work status legend, value for value.

    BACKLOG.md stays the authority until #102 cuts over, so this mirrors it
    rather than inventing a claim/progress vocabulary; claim state is the
    nullable claim fields, reserved for #100.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IMPLEMENTED = "implemented"
    ACCEPTED_SPEC = "accepted_spec"
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    OBSOLETE = "obsolete"


class GoalReference(BaseModel):
    """An exact (goal_id, goal_revision) pointer into the canonical Goal owner."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    goal_id: StrictStr
    goal_revision: StrictStr | StrictInt

    @model_validator(mode="after")
    def _canonical(self) -> GoalReference:
        try:
            INTEROP_ONTOLOGY_V1.validate_projection("Goal", self.model_dump())
        except InteropContractError as exc:
            raise ValueError(str(exc)) from exc
        return self


class BacklogItem(BaseModel):
    """One Workspace/Project-scoped unit of work source."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    workspace_id: str
    project_id: str
    external_key: str | None = None
    title: str
    description: str = ""
    status: BacklogItemStatus = BacklogItemStatus.PROPOSED
    priority: str | None = None
    risk: str | None = None
    source: str | None = None
    owner_principal_id: str | None = None
    milestone: str | None = None
    acceptance_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    spec_refs: list[str] = Field(default_factory=list)
    scenario_refs: list[str] = Field(default_factory=list)
    allowed_scope: list[str] = Field(default_factory=list)
    protected_scope: list[str] = Field(default_factory=list)
    #: A free token; what each mode permits is #100/#103's to define.
    autonomy_mode: str | None = None
    parent_item_id: str | None = None
    rank: float = Field(default=0.0, allow_inf_nan=False)
    paused: bool = False
    pinned: bool = False
    archived_at: datetime | None = None
    goal_ref: GoalReference | None = None
    version: int = Field(default=1, ge=1)
    # Reserved for #100's claim/lease protocol; nothing here writes them.
    claimant_principal_id: str | None = None
    claimant_agent_id: str | None = None
    claim_run_id: str | None = None
    lease_expires_at: datetime | None = None
    fence_token: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _shape(self) -> BacklogItem:
        for name in ("item_id", "workspace_id", "project_id", "title"):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be a non-empty string")
        if self.parent_item_id == self.item_id:
            raise ValueError("a BacklogItem cannot be its own parent")
        for name in ("created_at", "updated_at", "archived_at", "lease_expires_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _as_utc(value))
        return self


class BacklogItemNotFound(KeyError):
    pass


class BacklogItemAlreadyExists(ValueError):
    """The item_id, or the (workspace_id, external_key) pair, is taken."""


class BacklogVersionConflict(RuntimeError):
    """`expected_version` is stale; `current_item` is what the store holds now."""

    def __init__(self, expected: int, current_item: BacklogItem) -> None:
        super().__init__(
            f"BacklogItem {current_item.item_id} is at version {current_item.version}, "
            f"not {expected}"
        )
        self.expected = expected
        self.current_item = current_item


class BacklogRelationError(ValueError):
    """A dependency, parent or Project reference the store refuses.

    `kind` is ``"self"``, ``"cycle"`` or ``"cross_workspace"`` (which includes
    a referenced Project that does not exist: from the item's Workspace it is
    indistinguishable from one that belongs to another).
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


#: #100's claim/lease fields: reserved, so neither `create` nor `update` sets them.
CLAIM_FIELDS = frozenset(
    {
        "claimant_principal_id",
        "claimant_agent_id",
        "claim_run_id",
        "lease_expires_at",
        "fence_token",
    }
)

#: Fields `update` will not change: identity, scope root, the version it owns,
#: the parent edge `set_parent` owns, and #100's claim fields.
IMMUTABLE_FIELDS = frozenset(
    {
        "item_id",
        "workspace_id",
        "version",
        "created_at",
        "updated_at",
        "parent_item_id",
    }
    | CLAIM_FIELDS
)


def new_item(item: BacklogItem) -> BacklogItem:
    """`item` as a store persists it on create: version 1, no claim."""
    claimed = sorted(name for name in CLAIM_FIELDS if getattr(item, name) is not None)
    if claimed:
        raise ValueError(f"BacklogItem.create cannot set {', '.join(claimed)}")
    return item.model_copy(update={"version": 1}, deep=True)


def apply_changes(current: BacklogItem, changes: dict[str, Any]) -> BacklogItem:
    """The next version of `current`, re-validated as a whole."""
    refused = sorted(set(changes) & IMMUTABLE_FIELDS)
    if refused:
        raise ValueError(f"BacklogItem.update cannot change {', '.join(refused)}")
    return BacklogItem.model_validate(
        {
            **current.model_dump(),
            **changes,
            "version": current.version + 1,
            "updated_at": datetime.now(UTC),
        }
    )


__all__ = [
    "CLAIM_FIELDS",
    "IMMUTABLE_FIELDS",
    "BacklogItem",
    "BacklogItemAlreadyExists",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogRelationError",
    "BacklogVersionConflict",
    "GoalReference",
    "apply_changes",
    "new_item",
]
