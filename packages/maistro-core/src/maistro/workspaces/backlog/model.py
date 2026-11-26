"""The Workspace BacklogItem record (#98) and its claim/lease policy (#100).

A BacklogItem is durable work-source state: what someone -- a human, the
persistent Workspace Agent, a delegated Agent, later RSI -- may pick up next.
It is not a Goal. A Goal is desired-outcome/accountability state owned by
`maistro.goals` (#458); an item may point at one, by exact identity and
revision, but never copies the outcome into a second field family.

A claim is not Goal ownership either (#100): it is a temporary, fenced lease
on the right to progress one item. Taking, renewing or releasing a claim
never touches `goal_ref` -- the canonical Goal's ownership and delegation
stay exactly where `maistro.goals` keeps them.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from maistro.interop import INTEROP_ONTOLOGY_V1, InteropContractError


def _as_utc(value: datetime) -> datetime:
    if value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# The members and fields carrying inline vulture ``V107``/``V105`` markers are
# the declarative surface: stores persist whole items via ``model_dump_json``
# and pydantic dispatches the validators at runtime, so static name-level
# scanning cannot see a read. The declarations carry inline vulture markers
# instead of ledger debt — the same disposition the Goal revision contract
# uses (maistro.goals.model, #805/#806).
class BacklogItemStatus(StrEnum):
    """The BACKLOG.md work status legend, value for value.

    BACKLOG.md stays the authority until #102 cuts over, so this mirrors it
    rather than inventing a claim/progress vocabulary; claim state is the
    nullable claim fields, reserved for #100.
    """

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IMPLEMENTED = "implemented"
    ACCEPTED_SPEC = "accepted_spec"  # noqa: V107
    SUPERSEDED = "superseded"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    OBSOLETE = "obsolete"  # noqa: V107


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
    owner_principal_id: str | None = None  # noqa: V107
    milestone: str | None = None
    acceptance_refs: list[str] = Field(default_factory=list)  # noqa: V107
    evidence_refs: list[str] = Field(default_factory=list)
    spec_refs: list[str] = Field(default_factory=list)  # noqa: V107
    scenario_refs: list[str] = Field(default_factory=list)  # noqa: V107
    allowed_scope: list[str] = Field(default_factory=list)  # noqa: V107
    protected_scope: list[str] = Field(default_factory=list)  # noqa: V107
    #: A free token; what each mode permits is #100/#103's to define.
    autonomy_mode: str | None = None  # noqa: V107
    parent_item_id: str | None = None
    rank: float = Field(default=0.0, allow_inf_nan=False)
    paused: bool = False
    pinned: bool = False
    archived_at: datetime | None = None
    goal_ref: GoalReference | None = None  # noqa: V107
    version: int = Field(default=1, ge=1)
    # Reserved for #100's claim/lease protocol; nothing here writes them.
    claimant_principal_id: str | None = None
    claimant_agent_id: str | None = None
    claim_run_id: str | None = None
    lease_expires_at: datetime | None = None
    fence_token: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")  # noqa: V105
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
        # A store may pass its own live object (e.g. InMemoryBacklogItemStore's
        # `_items` entry). Copy it so a caller mutating the conflict payload
        # cannot change persisted state without going through compare-and-set.
        self.current_item = current_item.model_copy(deep=True)


class BacklogRelationError(ValueError):
    """A dependency, parent or Project reference the store refuses.

    `kind` is ``"self"``, ``"cycle"`` or ``"cross_workspace"`` (which includes
    a referenced Project that does not exist: from the item's Workspace it is
    indistinguishable from one that belongs to another).
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind


#: Default lease for a claim (#100): long enough to span an Agent work cycle,
#: short enough that a crashed holder does not hold an item forever. An
#: expired lease re-opens the item deterministically; every other exit from a
#: claim is release, or the item leaving the claimable status pool.
DEFAULT_LEASE_SECONDS: float = 900.0

#: The statuses an item may be claimed from (#100's deterministic pool). Parked
#: (blocked), retired (superseded/obsolete/abandoned) and finished (implemented)
#: items are refused; working one starts by moving it back into the pool.
CLAIMABLE_STATUSES = frozenset(
    {
        BacklogItemStatus.PROPOSED,
        BacklogItemStatus.ACCEPTED,
        BacklogItemStatus.ACCEPTED_SPEC,
    }
)

#: A dependency stays the claim gate until its own work is done or retired:
#: an abandoned dependency blocks until the edge is dropped or the dependency
#: re-opens -- both deterministic moves, never a silent claim over it.
DEPENDENCY_SATISFIED_STATUSES = frozenset(
    {
        BacklogItemStatus.IMPLEMENTED,
        BacklogItemStatus.SUPERSEDED,
        BacklogItemStatus.OBSOLETE,
    }
)

#: The autonomy modes (#103's vocabulary) under which an Agent may hold a
#: claim. `human-only` and every unrecognized token refuse Agent claims:
#: an unknown constraint is a constraint, not a permission.
AGENT_CLAIMABLE_AUTONOMY_MODES = frozenset(
    {
        "autonomous",
        "autonomous-with-promotion-approval",
        "human-review-required",
    }
)

#: #100's claim/lease fields: reserved for the claim service, so neither
#: `create` nor `update` sets them -- only `claim`/`renew_claim`/`release_claim`
#: do, and retiring an item releases what it held.
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


class BacklogClaim(BaseModel):
    """A snapshot of one item's live claim (#100), built by the store.

    A receipt, not a grant: holding one confers nothing by itself. Progressing
    the item is what the fence token -- echoed here -- authorizes, and only
    while `lease_expires_at` is in the future.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    item_id: str
    claimant_principal_id: str | None = None  # noqa: V107
    claimant_agent_id: str | None = None  # noqa: V107
    claim_run_id: str | None = None  # noqa: V107
    fence_token: int
    lease_expires_at: datetime  # noqa: V107

    @model_validator(mode="after")
    def _normalize(self) -> BacklogClaim:
        if not self.item_id.strip():
            raise ValueError("item_id must be a non-empty string")
        object.__setattr__(self, "lease_expires_at", _as_utc(self.lease_expires_at))
        return self

    def is_active(self, *, at: datetime) -> bool:
        return self.lease_expires_at > _as_utc(at)


class BacklogClaimHeld(RuntimeError):
    """The item is already under a live claim; `claim` is who holds it.

    `current_item` is the store's state at refusal (a detached copy), so the
    loser can see the holder and the fence it would need -- and cannot win --
    without a second read.
    """

    def __init__(self, current_item: BacklogItem, claim: BacklogClaim) -> None:
        holder = claim.claimant_agent_id or claim.claimant_principal_id or "unknown"
        super().__init__(
            f"BacklogItem {current_item.item_id} is claimed by {holder} "
            f"(fence {claim.fence_token}, lease until "
            f"{claim.lease_expires_at.isoformat()})"
        )
        self.claim = claim
        self.current_item = current_item.model_copy(deep=True)


class BacklogClaimRefused(RuntimeError):
    """The claim policy refused this claim; `reason` names the gate that did."""

    def __init__(self, item_id: str, reason: str) -> None:
        super().__init__(f"BacklogItem {item_id} claim refused: {reason}")
        self.item_id = item_id
        self.reason = reason


class BacklogStaleFence(RuntimeError):
    """`presented` is not the item's current fence token; the holder lost it.

    Happens when a lease expired and another actor claimed the item (or the
    claim was released and re-taken): the old receipt must not edit, complete,
    or launch later work over the new holder. `current_item` is what the store
    holds now (a detached copy).
    """

    def __init__(self, presented: int | None, current_item: BacklogItem) -> None:
        super().__init__(
            f"BacklogItem {current_item.item_id} holds fence "
            f"{current_item.fence_token}, not {presented}"
        )
        self.presented = presented
        self.current_item = current_item.model_copy(deep=True)


def require_claimant(principal_id: str | None, agent_id: str | None) -> None:
    """A claim names who holds it: a principal, an Agent, or both."""
    if not (principal_id or "").strip() and not (agent_id or "").strip():
        raise ValueError("a claim needs a claimant: principal_id or agent_id")


def require_lease(lease_seconds: float) -> None:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")


def _scope_violation(scope: Sequence[str], item: BacklogItem) -> str | None:
    """The first declared scope token the item's own scope fields forbid.

    A declared token must sit inside the allowed scope (when one is declared)
    and outside the protected scope, with path semantics: a protected
    ``deploy/`` covers ``deploy/prod.yml`` and an allowed ``packages/`` covers
    ``packages/maistro-core/src/x.py`` (the #103 campaign-area rule). Tokens
    carrying ``.`` or ``..`` segments are refused before any boundary
    comparison: `PurePosixPath` keeps them verbatim, so an un-normalized
    ``packages/../deploy/prod.yml`` would pass both checks below while the
    path actually resolves into the protected tree.
    """
    for token in scope:
        stripped = token.strip()
        if not stripped:
            continue
        if any(part in (".", "..") for part in stripped.split("/")):
            return f"{stripped!r} contains '.' or '..' path segments"
        if any(_covers(boundary, stripped) for boundary in item.protected_scope):
            return f"{stripped!r} is inside the item's protected scope"
        if item.allowed_scope and not any(
            _covers(boundary, stripped) for boundary in item.allowed_scope
        ):
            return f"{stripped!r} is outside the item's allowed scope"
    return None


def _covers(boundary: str, token: str) -> bool:
    """`token` equals `boundary` or lives underneath it, segment-aware.

    Callers must refuse ``.``/``..`` segments first (`_scope_violation` does):
    `PurePosixPath` preserves them, so this comparison alone would treat
    ``packages/../deploy/x`` as inside ``packages/``.
    """
    base = PurePosixPath(boundary.strip().strip("/"))
    path = PurePosixPath(token.strip().strip("/"))
    return path == base or base in path.parents


def require_claim_policy(
    item: BacklogItem,
    dependencies: Iterable[BacklogItem],
    *,
    agent_id: str | None,
    scope: Sequence[str] = (),
) -> None:
    """#100's pre-claim gates, in one place so both stores enforce the same
    policy: the item must sit in the claimable status pool, every dependency
    must be satisfied, an Agent claimant must have a mode that permits one,
    and any declared scope must respect allowed/protected scope."""
    if item.status not in CLAIMABLE_STATUSES:
        raise BacklogClaimRefused(item.item_id, f"status {item.status.value!r} is not claimable")
    blocking = sorted(
        dependency.item_id
        for dependency in dependencies
        if dependency.status not in DEPENDENCY_SATISFIED_STATUSES
    )
    if blocking:
        raise BacklogClaimRefused(item.item_id, f"open dependencies: {', '.join(blocking)}")
    if (
        agent_id is not None
        and item.autonomy_mode is not None
        and item.autonomy_mode not in AGENT_CLAIMABLE_AUTONOMY_MODES
    ):
        raise BacklogClaimRefused(
            item.item_id,
            f"autonomy mode {item.autonomy_mode!r} does not permit Agent claims",
        )
    violation = _scope_violation(scope, item)
    if violation is not None:
        raise BacklogClaimRefused(item.item_id, violation)


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
    "AGENT_CLAIMABLE_AUTONOMY_MODES",
    "CLAIMABLE_STATUSES",
    "CLAIM_FIELDS",
    "DEFAULT_LEASE_SECONDS",
    "DEPENDENCY_SATISFIED_STATUSES",
    "IMMUTABLE_FIELDS",
    "BacklogClaim",
    "BacklogClaimHeld",
    "BacklogClaimRefused",
    "BacklogItem",
    "BacklogItemAlreadyExists",
    "BacklogItemNotFound",
    "BacklogItemStatus",
    "BacklogRelationError",
    "BacklogStaleFence",
    "BacklogVersionConflict",
    "GoalReference",
    "apply_changes",
    "new_item",
    "require_claim_policy",
    "require_claimant",
    "require_lease",
]
