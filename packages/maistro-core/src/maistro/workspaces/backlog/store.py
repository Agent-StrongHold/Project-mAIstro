"""The BacklogItem store contract and its in-memory reference (#98)."""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Iterable, Mapping
from typing import Any, Protocol, runtime_checkable

from maistro.projects.scope_store import ProjectScopeStore
from maistro.workspaces.backlog.model import (
    BacklogItem,
    BacklogItemAlreadyExists,
    BacklogItemNotFound,
    BacklogItemStatus,
    BacklogRelationError,
    BacklogVersionConflict,
    apply_changes,
    new_item,
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
        self, item_id: str, *, expected_version: int, changes: Mapping[str, Any]
    ) -> BacklogItem:
        """Apply `changes` iff the item is still at `expected_version`."""
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
        self, item_id: str, *, expected_version: int, changes: Mapping[str, Any]
    ) -> BacklogItem:
        async with self._lock:
            current = self._current(item_id, expected_version)
            updated = apply_changes(current, dict(changes))
            if updated.external_key != current.external_key and self._external_key_taken(updated):
                raise BacklogItemAlreadyExists(updated.external_key or item_id)
            if updated.project_id != current.project_id:
                await require_project_in_workspace(
                    self._project_store, updated.project_id, updated.workspace_id
                )
            self._items[item_id] = updated
        return updated.model_copy(deep=True)

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
        ids = self._depends_on.get(item_id, set())
        return _sorted_copies(self._items[i] for i in ids)

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
            current = self._require(item_id)
            if parent_item_id is not None:
                require_not_self(item_id, parent_item_id)
                require_same_workspace(current, self._require(parent_item_id))
                if item_id in self._ancestry(parent_item_id):
                    raise BacklogRelationError(
                        "cycle", f"{parent_item_id} is a descendant of {item_id}"
                    )
            current = self._current(item_id, expected_version)
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


__all__ = ["BacklogItemStore", "InMemoryBacklogItemStore"]
