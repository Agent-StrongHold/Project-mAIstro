"""Authorized agent work surface over the backlog store (#102).

The cutover acceptance requires that authorized RSI/agent
list/select/claim/write works against the database after the Markdown file
stops being the authority. The durable store already provides claims and
optimistic concurrency; what it does not provide is the authorization
decision — and it must not: tenancy is the caller's concern (the store is
Workspace-scoped, not an authorization point).

:class:`AgentBacklogSurface` is that thin, fail-closed decision layer in one
place so every agent caller (RSI loop, delegated agent, tool surface) shares
one vocabulary and one audit story:

- ``list`` — items visible in a workspace the actor may read;
- ``select`` — the highest-priority claimable item for an actor, so an agent
  asks "what should I work on" instead of scraping the list;
- ``claim`` — a lease on the right to progress the item (never Goal
  ownership, never an execution lease — ADR-092626-c1e7);
- ``write`` — an edit attributed to the actor, checked against the claim:
  a claim is required for writes while an active claim exists, and the
  claimant must be the writer. With no live claim, the workspace's normal
  edit rules apply (editors may edit);
- ``release`` — end the lease; expiry is checked, never implied.

Authorization is delegated to a single ``authorize`` callable the embedder
supplies; the surface fails closed when it returns nothing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Literal

from maistro.backlog.model import (
    BacklogClaim,
    BacklogClaimError,
    BacklogItem,
    BacklogItemStatus,
    status_is_terminal,
)
from maistro.backlog.store import DEFAULT_LEASE_SECONDS, BacklogStore

Role = Literal["viewer", "editor", "owner"]

Authorize = Callable[[str, str, str], Awaitable[Role | None]]
"""Decide the actor's role for ``(actor, workspace_id, action)``.

``action`` is one of ``"read"``, ``"claim"``, ``"write"``. Returning ``None``
means no relationship: the surface answers with not-found semantics (no
existence oracle) rather than a distinct denial.
"""

#: Actions that require more than read access.
_WRITE_ACTIONS: Final = frozenset({"claim", "write"})


class AgentSurfaceError(RuntimeError):
    """The requested work action is not authorized or not currently possible."""


@dataclass(frozen=True)
class Selection:
    """The item an agent should work on next, and why."""

    item: BacklogItem
    reason: str


def _readable(role: Role | None) -> bool:
    return role in ("viewer", "editor", "owner")


def _writable(role: Role | None) -> bool:
    return role in ("editor", "owner")


class AgentBacklogSurface:
    """One agent's fail-closed work loop over one :class:`BacklogStore`."""

    def __init__(self, store: BacklogStore, authorize: Authorize) -> None:
        self._store = store
        self._authorize = authorize

    async def list_items(
        self,
        *,
        actor: str,
        workspace_id: str,
        status: str | None = None,
    ) -> list[BacklogItem]:
        """Items the actor may see in the workspace."""
        await self._require(actor, workspace_id, "read")
        items = await self._store.list_items(workspace_id, status=status)
        return [item for item in items if not status_is_terminal(item.status)]

    async def select(
        self,
        *,
        actor: str,
        workspace_id: str,
        at: datetime | None = None,
    ) -> Selection | None:
        """The highest-priority open item the actor could claim, or ``None``.

        Priority is the item's explicit human ``priority`` (1 highest, per the
        SPEC-092626-1831 vocabulary), then rank, then age — deterministic, so
        two agents asking the same question get the same answer and can fight
        it out on the claim instead of on interpretation.
        """
        candidates = await self.list_items(actor=actor, workspace_id=workspace_id)
        claimable = await self._claimable(
            [item for item in candidates if item.status == BacklogItemStatus.OPEN], at=at
        )
        if not claimable:
            return None
        best = min(
            claimable,
            key=lambda item: (item.priority, item.rank, item.created_at, item.item_id),
        )
        unresolved = await self._unresolved_dependencies(best)
        reason = "highest-priority open item"
        if unresolved:
            reason = (
                "highest-priority open item (dependencies unresolved: "
                + ", ".join(unresolved)
                + ")"
            )
        return Selection(item=best, reason=reason)

    async def _claimable(
        self, items: list[BacklogItem], *, at: datetime | None
    ) -> list[BacklogItem]:
        """The given open items that hold no active claim, in the same order."""
        claimable: list[BacklogItem] = []
        for item in items:
            if await self._store.active_claim(item.item_id, at=at) is None:
                claimable.append(item)
        return claimable

    async def _unresolved_dependencies(self, item: BacklogItem) -> list[str]:
        """Dependencies of ``item`` that are defined and still open.

        An unresolved dependency is reported in the selection reason rather
        than silently selecting a blocked item as if it were ready.
        """
        unresolved: list[str] = []
        for dep in item.dependencies:
            dep_item = await self._store.get_item(dep)
            if dep_item is not None and not status_is_terminal(dep_item.status):
                unresolved.append(dep)
        return unresolved

    async def claim(
        self,
        item_id: str,
        *,
        actor: str,
        lease_seconds: float = DEFAULT_LEASE_SECONDS,
        at: datetime | None = None,
    ) -> BacklogClaim:
        """Lease the right to progress one item.

        The actor must have write access to the item's workspace, and the item
        must not already hold an active claim. The store raises
        :class:`BacklogClaimError` with the live claim attached when it does.
        """
        item = await self._require_item(item_id)
        await self._require(actor, item.workspace_id, "claim")
        try:
            return await self._store.claim_item(
                item_id, claimed_by=actor, lease_seconds=lease_seconds, at=at
            )
        except BacklogClaimError as exc:
            raise AgentSurfaceError(str(exc)) from exc

    async def write(
        self,
        item_id: str,
        *,
        actor: str,
        expected_version: int,
        claim_id: str | None = None,
        at: datetime | None = None,
        **changes: object,
    ) -> BacklogItem:
        """An attributed edit; a live claim must belong to the writer.

        If the item holds an active claim, ``actor`` must be its holder (and
        ``claim_id`` must match when given) — claiming coordinates who may
        progress the item, so a bystander cannot ride in on someone else's
        lease. With no live claim, ordinary editor rights suffice.
        """
        item = await self._require_item(item_id)
        await self._require(actor, item.workspace_id, "write")
        active = await self._store.active_claim(item_id, at=at)
        if (
            active is not None
            and active.is_active(at=at or datetime.now(UTC))
            and (
                active.claimed_by != actor or (claim_id is not None and active.claim_id != claim_id)
            )
        ):
            raise AgentSurfaceError(
                f"{item_id} is claimed by {active.claimed_by!r} "
                f"(claim {active.claim_id}); acquire the claim to write it"
            )
        return await self._store.update_item(
            item_id,
            expected_version=expected_version,
            actor=actor,
            **changes,  # type: ignore[arg-type]
        )

    async def release(self, item_id: str, *, actor: str, claim_id: str) -> None:
        """Release the actor's own lease."""
        item = await self._require_item(item_id)
        await self._require(actor, item.workspace_id, "write")
        active = await self._store.active_claim(item_id)
        if active is None:
            return
        if active.claimed_by != actor or active.claim_id != claim_id:
            raise AgentSurfaceError(
                f"claim {claim_id} is not {actor!r}'s active claim on {item_id}"
            )
        await self._store.release_claim(item_id, claim_id=claim_id, actor=actor)

    async def _require_item(self, item_id: str) -> BacklogItem:
        item = await self._store.get_item(item_id)
        if item is None:
            # Same answer for a missing id and a stranger's id: the surface
            # is not an existence oracle for other workspaces' items.
            raise AgentSurfaceError(f"no such backlog item: {item_id!r}")
        return item

    async def _require(self, actor: str, workspace_id: str, action: str) -> None:
        role = await self._authorize(actor, workspace_id, action)
        needed = "read" if action not in _WRITE_ACTIONS else "write"
        if role is None or not (_readable(role) if needed == "read" else _writable(role)):
            raise AgentSurfaceError(f"{actor!r} may not {action} workspace {workspace_id!r} items")


__all__ = [
    "AgentBacklogSurface",
    "AgentSurfaceError",
    "Authorize",
    "Selection",
]
