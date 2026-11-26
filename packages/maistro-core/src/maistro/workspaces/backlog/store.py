"""The BacklogItem store contract and its in-memory reference (#98, #100).

Every content mutation takes an `expected_version` compare-and-set, so a UI
edit and an agent edit cannot silently overwrite one another. On top of that,
#100 adds the claim service: an atomic, fenced lease on the right to progress
one item, shared by humans, the persistent Workspace Agent, delegated Agents
and later RSI.

**Claims.** At most one unexpired claim exists per item, and taking it is a
single atomic transition: the loser gets `BacklogClaimHeld` carrying the
winner. The policy gates (claimable status pool, satisfied dependencies,
autonomy mode, allowed/protected scope) run inside the same critical section
as the write, so an item cannot be claimed past a gate that was true only
before the claim landed. A claim never touches `goal_ref` or any content
field -- claiming is not Goal ownership.

**Fencing.** The fence token is a per-item monotone counter. It advances on
every claim and every release, so a receipt from a finished claim can never
open a later one: while an item is actively claimed, `update` must present the
current fence, and a stale holder is refused with `BacklogStaleFence` even if
it somehow holds the right `expected_version`. Editing is the store-level
enforcement; a consumer about to launch later work for an item must consult
`active_claim` first and only proceed while the live claim is its own -- the
claim service never launches anything itself and never touches the canonical
Goal -> Graph -> Run spine.

**Re-eligibility.** Abandoned/failed work returns to the claimable pool only
through deterministic policy: the lease expiring (checked against the caller
supplied clock, never a timer), an explicit `release_claim`, or a contributor
moving the status back into the pool. Retiring a claimed item releases its
claim in the same write.
"""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces.backlog.model import (
    CLAIM_FIELDS,
    CLAIMABLE_STATUSES,
    DEFAULT_LEASE_SECONDS,
    BacklogClaim,
    BacklogClaimHeld,
    BacklogClaimRefused,
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogRelationError,
    BacklogStaleFence,
    BacklogVersionConflict,
    apply_changes,
    new_item,
    require_claim_policy,
    require_claimant,
    require_lease,
)


@runtime_checkable
class BacklogItemStore(Protocol):
    """Workspace/Project-scoped BacklogItems and their structured relations.

    Every write that changes an item's fields is a compare-and-set on
    `version`, so a UI edit and an agent edit cannot silently overwrite one
    another: the loser gets `BacklogVersionConflict` carrying the winner.
    Relations (dependencies, parent) never cross a Workspace and never close
    a cycle.
    """

    async def create(self, item: BacklogItem) -> BacklogItem:
        """Persist a new item at version 1."""
        ...

    async def get(self, item_id: str) -> BacklogItem | None:
        """The item, or ``None``."""
        ...

    async def list(
        self,
        workspace_id: str,
        project_id: str | None = None,
        status: BacklogItemStatus | None = None,
    ) -> builtins.list[BacklogItem]:
        """Items in the Workspace, ordered by (rank, created_at, item_id)."""
        ...

    async def update(
        self,
        item_id: str,
        *,
        expected_version: int,
        changes: Mapping[str, Any],
        fence_token: int | None = None,
    ) -> BacklogItem:
        """Apply `changes` iff the item is still at `expected_version`.

        While the item is actively claimed, `fence_token` must be the live
        claim's fence; a stale (or absent) token is refused even against the
        right version (#100)."""
        ...

    async def claim(
        self,
        item_id: str,
        *,
        principal_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        scope: Iterable[str] = (),
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogItem:
        """Take the item's claim atomically, or refuse why not (#100).

        `principal_id`/`agent_id` record who holds it, `run_id` the canonical
        Run the claim progresses where one exists. `scope` declares what the
        claimant intends to work in and is checked against the item's
        allowed/protected scope. One winner per item; the loser gets
        `BacklogClaimHeld`. A claim never touches `goal_ref`."""
        ...

    async def renew_claim(
        self,
        item_id: str,
        *,
        fence_token: int,
        lease_seconds: float,
        at: datetime | None = None,
    ) -> BacklogItem:
        """Extend the live claim's lease; the fence stays the same generation.

        Only the current holder (presenting the live fence) may renew; an
        expired claim is gone and re-claiming is the way back."""
        ...

    async def release_claim(
        self,
        item_id: str,
        *,
        fence_token: int,
        at: datetime | None = None,
    ) -> BacklogItem:
        """Give the claim up: the holder fields clear and the fence advances,
        so this receipt can never open a later claim."""
        ...

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None:
        """The item's live claim, or ``None`` once the lease has expired.

        Consumers about to launch later work for an item check this first and
        proceed only while the claim is theirs at the current fence."""
        ...

    async def add_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        """Record that `item_id` depends on `depends_on_item_id` (idempotent)."""
        ...

    async def remove_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        """Drop the edge if present."""
        ...

    async def dependencies_of(self, item_id: str) -> builtins.list[BacklogItem]:
        """Items `item_id` depends on."""
        ...

    async def dependents_of(self, item_id: str) -> builtins.list[BacklogItem]:
        """Items that depend on `item_id`."""
        ...

    async def children_of(self, item_id: str) -> builtins.list[BacklogItem]:
        """Items whose parent is `item_id`."""
        ...

    async def set_parent(
        self, item_id: str, parent_item_id: str | None, *, expected_version: int
    ) -> BacklogItem:
        """Re-parent (or detach) the item, bumping its version."""
        ...


async def require_project_in_workspace(
    project_store: ProjectScopeStore, project_id: str, workspace_id: str
) -> None:
    project = await project_store.get(project_id)
    if project is None or project.workspace_id != workspace_id:
        raise BacklogRelationError(
            "cross_workspace", f"Project {project_id} is not in Workspace {workspace_id}"
        )


def require_same_workspace(item: BacklogItem, other: BacklogItem) -> None:
    if other.workspace_id != item.workspace_id:
        raise BacklogRelationError(
            "cross_workspace",
            f"BacklogItem {other.item_id} is not in Workspace {item.workspace_id}",
        )


def require_not_self(item_id: str, other_id: str) -> None:
    if item_id == other_id:
        raise BacklogRelationError("self", f"BacklogItem {item_id} cannot relate to itself")


def sort_key(item: BacklogItem) -> tuple[float, str, str]:
    return (item.rank, item.created_at.isoformat(), item.item_id)


def _sorted_copies(items: Iterable[BacklogItem]) -> builtins.list[BacklogItem]:
    """Callers get their own objects, so mutating one cannot skip a version bump."""
    return [item.model_copy(deep=True) for item in sorted(items, key=sort_key)]


# -- claim/lease mechanics (#100), shared by every backend --------------------


def claim_now(at: datetime | None) -> datetime:
    """The clock the claim math runs on: the caller's reading or now (UTC).

    A naive reading means UTC, not this process's zone -- the same rule the
    model applies to its own timestamps, so a lease written from a naive
    reading compares equal no matter who reads it back."""
    if at is None:
        return datetime.now(UTC)
    if at.utcoffset() is None:
        return at.replace(tzinfo=UTC)
    return at.astimezone(UTC)


def active_claim_of(item: BacklogItem, now: datetime) -> BacklogClaim | None:
    """The item's claim as a snapshot, while -- and only while -- the lease is
    still live. An expired claim is no claim: the item is eligible again."""
    if item.fence_token is None or item.lease_expires_at is None:
        return None
    claim = BacklogClaim(
        item_id=item.item_id,
        claimant_principal_id=item.claimant_principal_id,
        claimant_agent_id=item.claimant_agent_id,
        claim_run_id=item.claim_run_id,
        fence_token=item.fence_token,
        lease_expires_at=item.lease_expires_at,
    )
    return claim if claim.is_active(at=now) else None


def refuse_held_claim(item: BacklogItem, now: datetime) -> None:
    """`claim`'s first gate: one live claim per item."""
    claim = active_claim_of(item, now)
    if claim is not None:
        raise BacklogClaimHeld(item, claim)


def plan_claim(
    item: BacklogItem,
    *,
    principal_id: str | None,
    agent_id: str | None,
    run_id: str | None,
    now: datetime,
    lease_seconds: float,
) -> BacklogItem:
    """The next version of `item` under a fresh claim: claimant fields set,
    lease stamped, fence advanced one generation, nothing else touched."""
    return item.model_copy(
        update={
            "claimant_principal_id": principal_id or None,
            "claimant_agent_id": agent_id or None,
            "claim_run_id": run_id or None,
            "fence_token": (item.fence_token or 0) + 1,
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "version": item.version + 1,
            "updated_at": now,
        }
    )


def plan_renew(item: BacklogItem, *, now: datetime, lease_seconds: float) -> BacklogItem:
    """The next version of `item` with the live claim's lease extended; the
    fence stays this generation's token."""
    return item.model_copy(
        update={
            "lease_expires_at": now + timedelta(seconds=lease_seconds),
            "version": item.version + 1,
            "updated_at": now,
        }
    )


def plan_release(item: BacklogItem, *, now: datetime) -> BacklogItem:
    """The next version of `item` with the claim given up: holder fields and
    lease clear, the fence advances so this receipt can never re-open the
    item's next claim."""
    return item.model_copy(
        update={
            "claimant_principal_id": None,
            "claimant_agent_id": None,
            "claim_run_id": None,
            "lease_expires_at": None,
            "fence_token": (item.fence_token or 0) + 1,
            "version": item.version + 1,
            "updated_at": now,
        }
    )


def require_current_fence(item: BacklogItem, fence_token: int | None, *, now: datetime) -> None:
    """An actively claimed item edits only under its live fence (#100).

    A stale holder -- lease lost to expiry and re-claim, or claim released and
    re-taken -- is refused even with the right `expected_version`: the fence,
    not the version, is what expired for them."""
    if active_claim_of(item, now) is None:
        return
    if fence_token is None or fence_token != item.fence_token:
        raise BacklogStaleFence(fence_token, item)


def require_claim_holder(item: BacklogItem, fence_token: int, now: datetime) -> None:
    """`renew_claim`/`release_claim` gate: a live claim held at this fence.

    An expired claim is already gone -- re-claiming is the way back, so the
    refusal says so rather than pretending to renew or release."""
    if active_claim_of(item, now) is None:
        raise BacklogClaimRefused(item.item_id, "no active claim to hold")
    if fence_token != item.fence_token:
        raise BacklogStaleFence(fence_token, item)


def release_if_retired(updated: BacklogItem) -> BacklogItem:
    """An item leaving the claimable status pool gives up any claim record in
    the same write: retired/finished work holds no lease (#100)."""
    if updated.status in CLAIMABLE_STATUSES:
        return updated
    if not any(getattr(updated, name) is not None for name in CLAIM_FIELDS):
        return updated
    return updated.model_copy(update=dict.fromkeys(CLAIM_FIELDS))


class InMemoryBacklogItemStore:
    """Reference implementation; the contract the durable stores are held to."""

    def __init__(self, *, project_store: ProjectScopeStore) -> None:
        self._project_store = project_store
        self._items: dict[str, BacklogItem] = {}
        self._depends_on: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    async def create(self, item: BacklogItem) -> BacklogItem:
        created = new_item(item)
        async with self._lock:
            if created.item_id in self._items or self._external_key_taken(created):
                raise BacklogItemAlreadyExists(created.item_id)
            await require_project_in_workspace(
                self._project_store, created.project_id, created.workspace_id
            )
            if created.parent_item_id is not None:
                require_same_workspace(created, self._require(created.parent_item_id))
            self._items[created.item_id] = created
        return created.model_copy(deep=True)

    async def get(self, item_id: str) -> BacklogItem | None:
        item = self._items.get(item_id)
        return item.model_copy(deep=True) if item is not None else None

    async def list(
        self,
        workspace_id: str,
        project_id: str | None = None,
        status: BacklogItemStatus | None = None,
    ) -> builtins.list[BacklogItem]:
        return _sorted_copies(
            item
            for item in self._items.values()
            if item.workspace_id == workspace_id
            and (project_id is None or item.project_id == project_id)
            and (status is None or item.status == status)
        )

    async def update(
        self,
        item_id: str,
        *,
        expected_version: int,
        changes: Mapping[str, Any],
        fence_token: int | None = None,
    ) -> BacklogItem:
        async with self._lock:
            current = self._require(item_id)
            require_current_fence(current, fence_token, now=claim_now(None))
            if current.version != expected_version:
                raise BacklogVersionConflict(expected_version, current)
            updated = apply_changes(current, dict(changes))
            updated = release_if_retired(updated)
            if updated.external_key != current.external_key and self._external_key_taken(updated):
                raise BacklogItemAlreadyExists(updated.external_key or item_id)
            if updated.project_id != current.project_id:
                await require_project_in_workspace(
                    self._project_store, updated.project_id, updated.workspace_id
                )
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

    async def claim(
        self,
        item_id: str,
        *,
        principal_id: str | None = None,
        agent_id: str | None = None,
        run_id: str | None = None,
        scope: Iterable[str] = (),
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogItem:
        require_claimant(principal_id, agent_id)
        require_lease(lease_seconds)
        now = claim_now(at)
        async with self._lock:
            current = self._require(item_id)
            refuse_held_claim(current, now)
            require_claim_policy(
                current,
                self._dependencies_of(current.item_id),
                agent_id=agent_id,
                scope=tuple(scope),
            )
            updated = plan_claim(
                current,
                principal_id=principal_id,
                agent_id=agent_id,
                run_id=run_id,
                now=now,
                lease_seconds=lease_seconds,
            )
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

    async def renew_claim(
        self,
        item_id: str,
        *,
        fence_token: int,
        lease_seconds: float,
        at: datetime | None = None,
    ) -> BacklogItem:
        require_lease(lease_seconds)
        now = claim_now(at)
        async with self._lock:
            current = self._require(item_id)
            require_claim_holder(current, fence_token, now)
            updated = plan_renew(current, now=now, lease_seconds=lease_seconds)
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

    async def release_claim(
        self,
        item_id: str,
        *,
        fence_token: int,
        at: datetime | None = None,
    ) -> BacklogItem:
        now = claim_now(at)
        async with self._lock:
            current = self._require(item_id)
            require_claim_holder(current, fence_token, now)
            updated = plan_release(current, now=now)
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

    async def active_claim(
        self, item_id: str, *, at: datetime | None = None
    ) -> BacklogClaim | None:
        current = self._require(item_id)
        return active_claim_of(current, claim_now(at))

    async def add_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        async with self._lock:
            item = self._require(item_id)
            other = self._require(depends_on_item_id)
            require_not_self(item_id, depends_on_item_id)
            require_same_workspace(item, other)
            if item_id in self._reachable(depends_on_item_id):
                raise BacklogRelationError(
                    "cycle", f"{item_id} -> {depends_on_item_id} closes a dependency cycle"
                )
            self._depends_on.setdefault(item_id, set()).add(depends_on_item_id)

    async def remove_dependency(self, item_id: str, depends_on_item_id: str) -> None:
        async with self._lock:
            self._require(item_id)
            self._depends_on.get(item_id, set()).discard(depends_on_item_id)

    async def dependencies_of(self, item_id: str) -> builtins.list[BacklogItem]:
        self._require(item_id)
        return _sorted_copies(self._dependencies_of(item_id))

    async def dependents_of(self, item_id: str) -> builtins.list[BacklogItem]:
        self._require(item_id)
        return _sorted_copies(
            (self._items[i] for i, deps in self._depends_on.items() if item_id in deps)
        )

    async def children_of(self, item_id: str) -> builtins.list[BacklogItem]:
        self._require(item_id)
        return _sorted_copies(
            item for item in self._items.values() if item.parent_item_id == item_id
        )

    async def set_parent(
        self, item_id: str, parent_item_id: str | None, *, expected_version: int
    ) -> BacklogItem:
        async with self._lock:
            current = self._current(item_id, expected_version)
            if parent_item_id is not None:
                require_not_self(item_id, parent_item_id)
                require_same_workspace(current, self._require(parent_item_id))
                if item_id in self._ancestry(parent_item_id):
                    raise BacklogRelationError(
                        "cycle", f"{parent_item_id} is a descendant of {item_id}"
                    )
            updated = apply_changes(current, {}).model_copy(
                update={"parent_item_id": parent_item_id}
            )
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

    def _require(self, item_id: str) -> BacklogItem:
        item = self._items.get(item_id)
        if item is None:
            raise BacklogItemNotFound(item_id)
        return item

    def _dependencies_of(self, item_id: str) -> builtins.list[BacklogItem]:
        """The dependency rows, without re-entering the lock: the claim gate
        reads them inside the critical section it already holds."""
        ids = self._depends_on.get(item_id, set())
        return [self._items[i] for i in ids]

    def _current(self, item_id: str, expected_version: int) -> BacklogItem:
        current = self._require(item_id)
        if current.version != expected_version:
            raise BacklogVersionConflict(expected_version, current)
        return current

    def _external_key_taken(self, item: BacklogItem) -> bool:
        return item.external_key is not None and any(
            other.external_key == item.external_key
            and other.workspace_id == item.workspace_id
            and other.item_id != item.item_id
            for other in self._items.values()
        )

    def _reachable(self, start: str) -> set[str]:
        seen: set[str] = set()
        frontier = [start]
        while frontier:
            node = frontier.pop()
            if node in seen:
                continue
            seen.add(node)
            frontier.extend(self._depends_on.get(node, ()))
        return seen

    def _ancestry(self, start: str) -> set[str]:
        seen: set[str] = set()
        node: str | None = start
        while node is not None and node not in seen:
            seen.add(node)
            node = self._items[node].parent_item_id
        return seen


__all__ = [
    "BacklogItemStore",
    "InMemoryBacklogItemStore",
    "active_claim_of",
    "claim_now",
    "plan_claim",
    "plan_release",
    "plan_renew",
    "refuse_held_claim",
    "release_if_retired",
    "require_claim_holder",
    "require_current_fence",
]
