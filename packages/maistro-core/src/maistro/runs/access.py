"""The authorization seam for canonical Run inspection.

The lifecycle stores remain the sole Run/NodeRun/Attempt authority. Product
readers use ``AuthorizedRunStore`` so an opaque child id is resolved only
through its canonical parent Run and the caller's authenticated scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from maistro.projects.authorization import resolve_project_authorization
from maistro.security.sentinel.authz_types import Principal

if TYPE_CHECKING:
    from maistro.graph.definitions import Graph
    from maistro.runs.model import Attempt, NodeRun, Run, RunStatus
    from maistro.runs.store import RunCursor

RUN_READ_ACTION = "runs:read"


@dataclass(frozen=True, slots=True)
class RunAuthorization:
    """Authenticated and, optionally, delegated identity for Run admission.

    ``authenticated_principal`` is the identity that crossed the auth boundary.
    ``acting_principal`` is the identity on whose behalf the execution runs;
    it must be the authenticated identity or an agent owned by it. Keeping both
    facts prevents delegation from being collapsed into a caller-controlled
    ``actor_principal_id`` string.
    """

    workspace_id: str
    project_id: str
    authenticated_principal: Principal
    acting_principal: Principal | None = None

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not self.project_id.strip():
            raise ValueError("Run authorization requires non-empty scope identity")
        acting = self.acting_principal or self.authenticated_principal
        if acting.id != self.authenticated_principal.id and (
            acting.kind != "agent" or acting.owner != self.authenticated_principal.id
        ):
            raise ValueError("acting principal must be authenticated or owned by the authenticator")

    @property
    def initiating_principal_id(self) -> str:
        return self.authenticated_principal.id

    @property
    def acting_principal_id(self) -> str:
        return (self.acting_principal or self.authenticated_principal).id


def admission_identity_fields(
    graph: Graph,
    *,
    authorization: RunAuthorization | None,
    legacy_actor_principal_id: str | None,
) -> dict[str, str | None]:
    """Resolve immutable Run identity facts before a Run can be persisted."""
    if authorization is None:
        if legacy_actor_principal_id is not None and not legacy_actor_principal_id.strip():
            raise ValueError("actor_principal_id must be non-empty when present")
        return {
            "actor_principal_id": legacy_actor_principal_id,
            "initiating_principal_id": legacy_actor_principal_id,
            "acting_principal_id": legacy_actor_principal_id,
        }
    if (
        authorization.workspace_id != graph.workspace_id
        or authorization.project_id != graph.project_id
    ):
        raise ValueError("Run authorization scope must match the Graph scope")
    if (
        legacy_actor_principal_id is not None
        and legacy_actor_principal_id != authorization.acting_principal_id
    ):
        raise ValueError("actor_principal_id does not match the authenticated acting principal")
    return {
        "actor_principal_id": authorization.acting_principal_id,
        "initiating_principal_id": authorization.initiating_principal_id,
        "acting_principal_id": authorization.acting_principal_id,
    }


@dataclass(frozen=True, slots=True)
class RunAccessContext:
    """Canonical Workspace/Project scope plus the authenticated principal."""

    workspace_id: str
    project_id: str
    principal: Principal

    def __post_init__(self) -> None:
        if not self.workspace_id.strip() or not self.project_id.strip():
            raise ValueError("Run access requires non-empty scope identity")


@runtime_checkable
class RunReader(Protocol):
    async def get_run(self, run_id: str) -> Run | None: ...

    async def get_node_run(self, node_run_id: str) -> NodeRun | None: ...

    async def list_node_runs(self, run_id: str) -> list[NodeRun]: ...

    async def get_attempt(self, attempt_id: str) -> Attempt | None: ...

    async def list_attempts(self, node_run_id: str) -> list[Attempt]: ...

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        offset: int = 0,
        project_id: str | None = None,
        workspace_id: str | None = None,
        after: RunCursor | None = None,
    ) -> list[Run]: ...


class AuthorizedRunStore:
    """Fail-closed, read-only product view over the canonical Run store.

    Missing and out-of-scope ids both return the empty answer. The underlying
    store is intentionally not exposed here: callers cannot accidentally turn
    a primary-key helper into a product inspection API without supplying this
    context.
    """

    def __init__(self, store: RunReader, context: RunAccessContext) -> None:
        self._store = store
        self._context = context
        self._project_store = getattr(store, "_project_store", None)

    async def get_run(self, run_id: str) -> Run | None:
        run = await self._store.get_run(run_id)
        return run if await self._can_read(run) else None

    async def get_node_run(self, node_run_id: str) -> NodeRun | None:
        node_run = await self._store.get_node_run(node_run_id)
        if node_run is None:
            return None
        run = await self._store.get_run(node_run.run_id)
        return node_run if await self._can_read(run) else None

    async def list_node_runs(self, run_id: str) -> list[NodeRun]:
        run = await self._store.get_run(run_id)
        if not await self._can_read(run):
            return []
        return await self._store.list_node_runs(run_id)

    async def get_attempt(self, attempt_id: str) -> Attempt | None:
        attempt = await self._store.get_attempt(attempt_id)
        if attempt is None:
            return None
        node_run = await self._store.get_node_run(attempt.node_run_id)
        if node_run is None:
            return None
        run = await self._store.get_run(node_run.run_id)
        return attempt if await self._can_read(run) else None

    async def list_attempts(self, node_run_id: str) -> list[Attempt]:
        node_run = await self._store.get_node_run(node_run_id)
        if node_run is None:
            return []
        run = await self._store.get_run(node_run.run_id)
        if not await self._can_read(run):
            return []
        return await self._store.list_attempts(node_run_id)

    async def list_by_status(
        self,
        status: RunStatus,
        *,
        limit: int = 100,
        offset: int = 0,
        after: RunCursor | None = None,
    ) -> list[Run]:
        if not await self._principal_can_read():
            return []
        return await self._store.list_by_status(
            status,
            limit=limit,
            offset=offset,
            project_id=self._context.project_id,
            workspace_id=self._context.workspace_id,
            after=after,
        )

    async def _can_read(self, run: Run | None) -> bool:
        if run is None:
            return False
        if (
            run.workspace_id != self._context.workspace_id
            or run.project_id != self._context.project_id
        ):
            return False
        return await self._principal_can_read()

    async def _principal_can_read(self) -> bool:
        """Resolve the canonical Project grant; absence is a denial."""
        if self._project_store is None:
            return False
        decision = await resolve_project_authorization(
            self._project_store,
            project_id=self._context.project_id,
            principal_id=self._context.principal.id,
        )
        return decision.allows(RUN_READ_ACTION)


__all__ = [
    "RUN_READ_ACTION",
    "AuthorizedRunStore",
    "RunAccessContext",
    "RunAuthorization",
    "RunReader",
    "admission_identity_fields",
]
