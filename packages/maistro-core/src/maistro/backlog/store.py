"""The BacklogItem store contract and its in-memory reference (#82).

Three implementations agree on one protocol -- this reference, the SQLite
twin, and the PostgreSQL twin -- and one conformance suite runs the same
bodies over all three, because a durable twin that agrees with the reference
only in its docstring is how `PgStrikeTracker` came to be unusable (#134).

**Optimistic concurrency.** Every content mutation takes an
``expected_version`` and is refused with ``BacklogVersionConflict`` (carrying
the store's current version) when it is stale. Conflict handling is the
caller's decision; the store never merges.

**Atomic claims.** At most one unexpired, unreleased claim exists per item.
The reference enforces it by check-then-set with no ``await`` between (single
event loop); the durable twins do it in one transaction (SQLite ``BEGIN
IMMEDIATE``; PostgreSQL ``SELECT ... FOR UPDATE`` on the item row). A claim
never mutates the item's content, version, or Goal linkage.

**Attributed history.** Every mutation appends ``BacklogEvent`` rows in the
same critical section as the state change, so provenance (#101) cannot drift
from state: there is no code path that edits an item without an event.

**Backend independence.** Nothing here imports RSI, a server package, or an
execution component. The Workspace boundary is the only tenancy axis this
module knows about; hard tenant isolation stays with the importing product
(ADR-019).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final, Protocol, runtime_checkable

from maistro.backlog.model import (
    _MUTABLE_STATUSES,
    _TERMINAL_STATUSES,
    BacklogClaim,
    BacklogClaimError,
    BacklogClosure,
    BacklogClosureError,
    BacklogEvent,
    BacklogEventKind,
    BacklogItem,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogOrigin,
    BacklogVersionConflict,
    status_is_terminal,
)

#: Sentinel for "leave this clearable field unchanged" in ``update_item``.
#: ``None`` means "clear it"; omitting the argument (the sentinel) means "no
#: opinion". A plain-``None`` default would make clearing impossible to
#: express.
UNSET: Final = object()

#: Default lease for a claim. Long enough to span an Agent work cycle, short
#: enough that a crashed holder does not hold an item forever; the lease
#: either expires or is explicitly released/extended, and every transition is
#: a recorded event.
DEFAULT_LEASE_SECONDS: Final = 900.0


@runtime_checkable
class BacklogStore(Protocol):
    """The one contract every backend implements (#98)."""

    async def create_item(
        self,
        *,
        workspace_id: str,
        title: str,
        actor: str,
        details: str = "",
        tags: tuple[str, ...] = (),
        milestone: str | None = None,
        package: str | None = None,
        risk_notes: str = "",
        parent_id: str | None = None,
        goal_id: str | None = None,
        goal_revision: int | None = None,
        source: str = "human",
        dependencies: tuple[str, ...] = (),
        origin: BacklogOrigin | None = None,
        priority: int = 3,
        rank: float = 1000.0,
        item_id: str | None = None,
        at: datetime | None = None,
    ) -> BacklogItem: ...

    async def get_item(self, item_id: str) -> BacklogItem | None: ...

    async def update_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        title: str | None = None,
        details: str | None = None,
        risk_notes: str | None = None,
        tags: tuple[str, ...] | None = None,
        milestone: str | None | object = UNSET,
        package: str | None | object = UNSET,
        parent_id: str | None | object = UNSET,
        goal_id: str | None | object = UNSET,
        goal_revision: int | None | object = UNSET,
        status: str | None = None,
        dependencies: tuple[str, ...] | None = None,
        origin: BacklogOrigin | None | object = UNSET,
        priority: int | None = None,
        rank: float | None = None,
        at: datetime | None = None,
    ) -> BacklogItem: ...

    async def close_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        outcome: str,
        closure_summary: str,
        evidence_refs: tuple[str, ...],
        at: datetime | None = None,
    ) -> BacklogItem: ...

    async def reopen_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogItem: ...

    async def list_items(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        tag: str | None = None,
        parent_id: str | None = None,
        roots_only: bool = False,
    ) -> list[BacklogItem]: ...

    async def claim_item(
        self,
        item_id: str,
        *,
        claimed_by: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogClaim: ...

    async def extend_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        lease_seconds: float,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogClaim: ...

    async def release_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        actor: str,
        at: datetime | None = None,
    ) -> None: ...

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None: ...

    async def events(self, item_id: str) -> list[BacklogEvent]: ...


def _now(at: datetime | None) -> datetime:
    return at if at is not None else datetime.now(UTC)


def _require_fresh_version(item: BacklogItem, expected_version: int) -> None:
    """Refuse a stale-content edit; the store never merges (#82: conflict handling)."""
    if expected_version != item.version:
        raise BacklogVersionConflict(item.item_id, item.version)


def _require_valid_outcome(outcome: str) -> None:
    if not status_is_terminal(outcome):
        raise BacklogClosureError(str(outcome), f"{outcome!r} is not a terminal outcome")


def _plan_changes(
    item: BacklogItem,
    *,
    title: str | None,
    details: str | None,
    risk_notes: str | None,
    tags: tuple[str, ...] | None,
    milestone: str | None | object,
    package: str | None | object,
    parent_id: str | None | object,
    goal_id: str | None | object,
    goal_revision: int | None | object,
    status: str | None,
    dependencies: tuple[str, ...] | None,
    origin: BacklogOrigin | None | object,
    priority: int | None,
    rank: float | None,
) -> dict[str, object]:
    """Compute the changed fields for ``update_item``, or ``{}`` for a no-op.

    Shared change-planning so the reference and the durable stores cannot
    disagree about what an edit means. Fields passed as ``UNSET`` are left
    alone; ``None`` clears a clearable field; a ``status`` change among the
    mutable statuses is allowed, while terminal statuses are reachable only
    through ``close_item``/``reopen_item``.
    """
    changes: dict[str, object] = {}
    provided = {
        "title": title,
        "details": details,
        "risk_notes": risk_notes,
        "tags": tags,
        # "no opinion" semantics for dependencies too: an empty tuple is a
        # real state (no blockers), so absence of the argument cannot clear.
        "dependencies": dependencies,
        "priority": priority,
        "rank": rank,
    }
    changes.update({field: value for field, value in provided.items() if value is not None})
    clearable = (
        ("milestone", milestone),
        ("package", package),
        ("parent_id", parent_id),
        ("goal_id", goal_id),
        ("goal_revision", goal_revision),
        ("origin", origin),
    )
    for field, value in clearable:
        if value is not UNSET and value != getattr(item, field):
            changes[field] = value
    if status is not None and status is not item.status:
        if status not in _MUTABLE_STATUSES:
            raise ValueError(
                "terminal statuses are reached through close_item and left "
                "through reopen_item, which record closure evidence"
            )
        changes["status"] = status
    return changes


def _listable(
    item: BacklogItem,
    workspace_id: str,
    *,
    status: str | None,
    tag: str | None,
    parent_id: str | None,
    roots_only: bool,
) -> bool:
    """Whether one stored item matches the list filter, evaluated per row.

    Every optional filter must hold for the item to be listed; ``None`` (and
    ``roots_only=False``) means "no opinion". Splitting the predicate out of
    the comprehension keeps the reference store's one-pass filter readable
    without growing a C block, and the row is still deep-copied by the caller
    so no listed item aliases store state.
    """
    if item.workspace_id != workspace_id:
        return False
    if status is not None and item.status is not status:
        return False
    if tag is not None and tag not in item.tags:
        return False
    if parent_id is not None and item.parent_id != parent_id:
        return False
    return not roots_only or item.parent_id is None


class InMemoryBacklogStore:
    """The reference. The other two stores are read against it."""

    def __init__(self) -> None:
        self._items: dict[str, BacklogItem] = {}
        self._claims: dict[str, BacklogClaim] = {}
        self._events: dict[str, list[BacklogEvent]] = {}

    # -- reads ----------------------------------------------------------

    async def get_item(self, item_id: str) -> BacklogItem | None:
        item = self._items.get(item_id)
        return item.model_copy(deep=True) if item is not None else None

    async def list_items(
        self,
        workspace_id: str,
        *,
        status: str | None = None,
        tag: str | None = None,
        parent_id: str | None = None,
        roots_only: bool = False,
    ) -> list[BacklogItem]:
        found = [
            item.model_copy(deep=True)
            for item in self._items.values()
            if _listable(
                item,
                workspace_id,
                status=status,
                tag=tag,
                parent_id=parent_id,
                roots_only=roots_only,
            )
        ]
        found.sort(key=lambda item: (item.created_at, item.item_id))
        return found

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None:
        now = _now(at)
        self._require_item(item_id)
        claim = self._claims.get(item_id)
        if claim is not None and claim.is_active(at=now):
            return claim.model_copy(deep=True)
        return None

    async def events(self, item_id: str) -> list[BacklogEvent]:
        self._require_item(item_id)
        return [event.model_copy(deep=True) for event in self._events.get(item_id, [])]

    # -- writes ---------------------------------------------------------

    async def create_item(
        self,
        *,
        workspace_id: str,
        title: str,
        actor: str,
        details: str = "",
        tags: tuple[str, ...] = (),
        milestone: str | None = None,
        package: str | None = None,
        risk_notes: str = "",
        parent_id: str | None = None,
        goal_id: str | None = None,
        goal_revision: int | None = None,
        source: str = "human",
        dependencies: tuple[str, ...] = (),
        origin: BacklogOrigin | None = None,
        priority: int = 3,
        rank: float = 1000.0,
        item_id: str | None = None,
        at: datetime | None = None,
    ) -> BacklogItem:
        item = BacklogItem(
            workspace_id=workspace_id,
            title=title,
            created_by=actor,
            details=details,
            tags=tags,
            milestone=milestone,
            package=package,
            risk_notes=risk_notes,
            parent_id=parent_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            source=source,
            dependencies=dependencies,
            origin=origin,
            priority=priority,
            rank=rank,
            **({"item_id": item_id} if item_id is not None else {}),
        )
        if item.item_id in self._items:
            raise ValueError(f"BacklogItem {item.item_id!r} already exists")
        if parent_id is not None:
            await self._require_decomposable_parent(parent_id, child=item, at=at)
        self._items[item.item_id] = item
        self._events[item.item_id] = [
            BacklogEvent(
                item_id=item.item_id,
                actor=actor,
                kind=BacklogEventKind.CREATED,
                item_version=item.version,
                payload={"title": item.title, "parent_id": parent_id},
                **({"at": at} if at is not None else {}),
            )
        ]
        if parent_id is not None:
            parent = self._items[parent_id]
            self._events[parent_id].append(
                BacklogEvent(
                    item_id=parent_id,
                    actor=actor,
                    kind=BacklogEventKind.DECOMPOSED,
                    item_version=parent.version,
                    payload={"child_id": item.item_id, "child_title": item.title},
                    **({"at": at} if at is not None else {}),
                )
            )
        return item.model_copy(deep=True)

    async def update_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        title: str | None = None,
        details: str | None = None,
        risk_notes: str | None = None,
        tags: tuple[str, ...] | None = None,
        milestone: str | None | object = UNSET,
        package: str | None | object = UNSET,
        parent_id: str | None | object = UNSET,
        goal_id: str | None | object = UNSET,
        goal_revision: int | None | object = UNSET,
        status: str | None = None,
        dependencies: tuple[str, ...] | None = None,
        origin: BacklogOrigin | None | object = UNSET,
        priority: int | None = None,
        rank: float | None = None,
        at: datetime | None = None,
    ) -> BacklogItem:
        item = self._require_item(item_id)
        self._require_fresh_version(item, expected_version)
        changes = _plan_changes(
            item,
            title=title,
            details=details,
            risk_notes=risk_notes,
            tags=tags,
            milestone=milestone,
            package=package,
            parent_id=parent_id,
            goal_id=goal_id,
            goal_revision=goal_revision,
            status=status,
            dependencies=dependencies,
            origin=origin,
            priority=priority,
            rank=rank,
        )
        if "parent_id" in changes and changes["parent_id"] is not None:
            new_parent = str(changes["parent_id"])
            await self._require_decomposable_parent(new_parent, child=item, at=at)
        if not changes:
            return item.model_copy(deep=True)
        updated = item.model_copy(
            update={
                **changes,
                "version": item.version + 1,
                "updated_at": _now(at),
            }
        )
        # Revalidate: the model guards status/closure pairing and field shape.
        updated = BacklogItem.model_validate(updated.model_dump())
        self._items[item_id] = updated
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=actor,
                kind=BacklogEventKind.STATUS_CHANGED
                if "status" in changes
                else BacklogEventKind.UPDATED,
                item_version=updated.version,
                payload=dict(changes),
                **({"at": at} if at is not None else {}),
            ),
        )
        return updated.model_copy(deep=True)

    async def close_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        outcome: str,
        closure_summary: str,
        evidence_refs: tuple[str, ...],
        at: datetime | None = None,
    ) -> BacklogItem:
        item = self._require_item(item_id)
        self._require_fresh_version(item, expected_version)
        if outcome not in _TERMINAL_STATUSES:
            raise BacklogClosureError(item_id, f"{outcome!r} is not a terminal outcome")
        if status_is_terminal(item.status):
            raise BacklogClosureError(item_id, f"item is already closed ({item.status})")
        try:
            closure = BacklogClosure(
                summary=closure_summary,
                evidence_refs=tuple(evidence_refs),
                **({"closed_at": at} if at is not None else {}),
            )
        except ValueError as exc:
            raise BacklogClosureError(item_id, f"closure evidence incomplete: {exc}") from exc
        open_children = [
            child.item_id
            for child in self._items.values()
            if child.parent_id == item_id and not status_is_terminal(child.status)
        ]
        if open_children:
            raise BacklogClosureError(
                item_id,
                f"cannot close while child {sorted(open_children)[0]!r} is still open",
            )
        closed_at = _now(at)
        updated = item.model_copy(
            update={
                "status": outcome,
                "closure": closure,
                "version": item.version + 1,
                "updated_at": closed_at,
            }
        )
        self._items[item_id] = updated
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=actor,
                kind=BacklogEventKind.CLOSED,
                item_version=updated.version,
                payload={
                    "outcome": outcome,
                    "closure_summary": closure.summary,
                    "evidence_refs": list(closure.evidence_refs),
                },
                **({"at": at} if at is not None else {}),
            ),
        )
        return updated.model_copy(deep=True)

    async def reopen_item(
        self,
        item_id: str,
        *,
        expected_version: int,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogItem:
        item = self._require_item(item_id)
        self._require_fresh_version(item, expected_version)
        if not status_is_terminal(item.status):
            raise BacklogClosureError(item_id, f"item is not closed (status {item.status})")
        updated = item.model_copy(
            update={
                "status": BacklogItemStatus.OPEN,
                "closure": None,
                "version": item.version + 1,
                "updated_at": _now(at),
            }
        )
        self._items[item_id] = updated
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=actor,
                kind=BacklogEventKind.REOPENED,
                item_version=updated.version,
                payload={"previous_status": item.status},
                **({"at": at} if at is not None else {}),
            ),
        )
        return updated.model_copy(deep=True)

    async def claim_item(
        self,
        item_id: str,
        *,
        claimed_by: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogClaim:
        item = self._require_item(item_id)
        now = _now(at)
        if status_is_terminal(item.status):
            raise BacklogClosureError(item_id, f"a closed item ({item.status}) cannot be claimed")
        existing = self._claims.get(item_id)
        if existing is not None and existing.is_active(at=now):
            raise BacklogClaimError(item_id, existing)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        claim = BacklogClaim(
            item_id=item_id,
            claimed_by=claimed_by,
            claimed_at=now,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        self._claims[item_id] = claim
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=claimed_by,
                kind=BacklogEventKind.CLAIMED,
                item_version=item.version,
                payload={
                    "claim_id": claim.claim_id,
                    "lease_expires_at": claim.lease_expires_at.isoformat(),
                },
                **({"at": at} if at is not None else {}),
            ),
        )
        return claim.model_copy(deep=True)

    async def extend_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        lease_seconds: float,
        actor: str,
        at: datetime | None = None,
    ) -> BacklogClaim:
        item = self._require_item(item_id)
        now = _now(at)
        claim = self._active_claim_or_none(item_id, now)
        if claim is None:
            raise BacklogItemNotFound(f"no active claim on backlog item {item_id!r}")
        if claim.claim_id != claim_id:
            raise BacklogClaimError(item_id, claim)
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        extended = claim.model_copy(
            update={"lease_expires_at": now + timedelta(seconds=lease_seconds)}
        )
        self._claims[item_id] = extended
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=actor,
                kind=BacklogEventKind.LEASE_EXTENDED,
                item_version=item.version,
                payload={
                    "claim_id": claim_id,
                    "lease_expires_at": extended.lease_expires_at.isoformat(),
                },
                **({"at": at} if at is not None else {}),
            ),
        )
        return extended.model_copy(deep=True)

    async def release_claim(
        self,
        item_id: str,
        *,
        claim_id: str,
        actor: str,
        at: datetime | None = None,
    ) -> None:
        item = self._require_item(item_id)
        now = _now(at)
        claim = self._active_claim_or_none(item_id, now)
        if claim is None or claim.claim_id != claim_id:
            raise BacklogItemNotFound(f"no active claim {claim_id!r} on backlog item {item_id!r}")
        released = claim.model_copy(update={"released_at": now})
        self._claims[item_id] = released
        self._append(
            item_id,
            BacklogEvent(
                item_id=item_id,
                actor=actor,
                kind=BacklogEventKind.CLAIM_RELEASED,
                item_version=item.version,
                payload={"claim_id": claim_id},
                **({"at": at} if at is not None else {}),
            ),
        )

    # -- internals ------------------------------------------------------

    def _require_item(self, item_id: str) -> BacklogItem:
        item = self._items.get(item_id)
        if item is None:
            raise BacklogItemNotFound(item_id)
        return item

    @staticmethod
    def _require_fresh_version(item: BacklogItem, expected_version: int) -> None:
        if expected_version != item.version:
            raise BacklogVersionConflict(item.item_id, item.version)

    def _active_claim_or_none(self, item_id: str, now: datetime) -> BacklogClaim | None:
        claim = self._claims.get(item_id)
        return claim if claim is not None and claim.is_active(at=now) else None

    async def _require_decomposable_parent(
        self, parent_id: str, *, child: BacklogItem, at: datetime | None
    ) -> None:
        parent = self._items.get(parent_id)
        if parent is None:
            raise BacklogItemNotFound(parent_id)
        if parent.workspace_id != child.workspace_id:
            raise ValueError("a child item must live in its parent's Workspace")
        if status_is_terminal(parent.status):
            raise BacklogClosureError(parent_id, "cannot decompose a closed item")
        # Refuse cycles: walking up from the new parent must never reach the child.
        walker = parent
        seen: set[str] = set()
        while walker.parent_id is not None and walker.parent_id not in seen:
            if walker.parent_id == child.item_id:
                raise ValueError("decomposition would create a parent/child cycle")
            seen.add(walker.parent_id)
            walker = self._items[walker.parent_id]

    def _append(self, item_id: str, event: BacklogEvent) -> None:
        self._events.setdefault(item_id, []).append(event)


__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "UNSET",
    "BacklogStore",
    "InMemoryBacklogStore",
]
