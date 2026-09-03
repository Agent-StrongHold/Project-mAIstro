"""Canonical authority for resolving consumer Bindings at effect time.

A Binding identifier is only a reference. It grants nothing until this store
resolves the immutable Binding against the canonical Workspace, Project, Node,
and Capability of the execution requesting it. That makes a Graph parameter or
Agent declaration unable to authorize itself merely by naming an id.

The in-memory implementation is the process-local M1 authority used by the
composition seam in :mod:`maistro.capabilities.effect_context`. Durable Binding
persistence can implement the same protocol without changing effect consumers.
"""

from __future__ import annotations

import asyncio
from typing import Protocol, runtime_checkable

from maistro.capabilities.binding import Binding


class BindingResolutionError(RuntimeError):
    """A referenced Binding cannot authorize the requested effect."""


class BindingNotFound(BindingResolutionError):
    """The requested Binding identity has no registered definition."""


class BindingScopeDenied(BindingResolutionError):
    """A Binding exists but does not cover the requesting execution scope."""


@runtime_checkable
class BindingStore(Protocol):
    """Canonical Binding definition and scope-resolution contract."""

    async def put(self, binding: Binding) -> Binding: ...

    async def get(self, binding_id: str) -> Binding | None: ...

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding: ...


class InMemoryBindingStore:
    """Concurrency-safe process-local BindingStore.

    Binding identities are immutable. Re-registering the exact same Binding is
    idempotent; trying to change the definition behind an existing id is
    rejected instead of silently widening authority.
    """

    def __init__(self) -> None:
        self._items: dict[str, Binding] = {}
        self._lock = asyncio.Lock()

    async def put(self, binding: Binding) -> Binding:
        async with self._lock:
            existing = self._items.get(binding.binding_id)
            if existing is not None and existing != binding:
                raise ValueError(
                    f"Binding {binding.binding_id!r} is immutable and already registered"
                )
            persisted = binding.model_copy(deep=True)
            self._items[binding.binding_id] = persisted
            return persisted.model_copy(deep=True)

    async def get(self, binding_id: str) -> Binding | None:
        item = self._items.get(binding_id)
        return item.model_copy(deep=True) if item is not None else None

    async def resolve(
        self,
        binding_id: str,
        *,
        workspace_id: str,
        project_id: str,
        node_id: str,
        capability: str,
    ) -> Binding:
        required = {
            "binding_id": binding_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "node_id": node_id,
            "capability": capability,
        }
        for field, value in required.items():
            if not value.strip():
                raise BindingScopeDenied(f"{field} is required to resolve a Binding")

        binding = await self.get(binding_id)
        if binding is None:
            raise BindingNotFound(f"Binding {binding_id!r} is not registered")
        if binding.workspace_id != workspace_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} belongs to Workspace {binding.workspace_id!r}, "
                f"not {workspace_id!r}"
            )
        if binding.project_id != project_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} belongs to Project {binding.project_id!r}, "
                f"not {project_id!r}"
            )
        if binding.node_id and binding.node_id != node_id:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} is restricted to Node {binding.node_id!r}, not {node_id!r}"
            )
        if binding.capability != capability:
            raise BindingScopeDenied(
                f"Binding {binding_id!r} authorizes Capability {binding.capability!r}, "
                f"not {capability!r}"
            )
        return binding


__all__ = [
    "BindingNotFound",
    "BindingResolutionError",
    "BindingScopeDenied",
    "BindingStore",
    "InMemoryBindingStore",
]
