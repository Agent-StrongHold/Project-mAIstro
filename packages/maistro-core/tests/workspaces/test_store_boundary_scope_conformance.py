"""Store-boundary scope for every store the Workspace consumes (#364, cutover P0.8).

#364's principle is that scope is enforced at the durable store boundary, not
only by whichever route happens to sit in front of it. This suite asks each
store the Workspace reads from -- workspaces, projects, runs, audit -- the
same two questions on every backend: can a principal outside the scope a
record was written in read it by id, and can they mutate it by id?

Most of these stores take no principal at all, so today the honest answer is
often "yes". Those cases are entries in `KNOWN_GAPS` rather than markers: a
gap's body asserts the unscoped behaviour still happens, so the change that
closes one fails here until its entry is deleted.

The harness is one adapter per store (`_ScopeAdapter`): how to write a record
inside a scope, how to read and mutate it as someone else, and how to see
whether the mutation landed. A store joins the suite by adding an adapter and
its gap keys; the backends and the case bodies are shared.

Two things the Workspace needs that are not read/mutate pairs ride along:
`Run.actor_principal_id` must be required and validated when a Run is
admitted, and audit rows must carry and filter by `org_id`.

The PostgreSQL leg runs against a migrated server through the shared
`pg_pool` fixture. It is collected only when `MAISTRO_TEST_PG_DSN` or
`MAISTRO_REQUIRE_PG_LEGS` is set, and with the latter set and no server it
fails rather than passing on two backends: the CI steps that run this
directory (`ci.yml` postgres, `quality.yml` coverage) set both.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Protocol
from uuid import uuid4

import aiosqlite
import pytest
from pydantic import ValidationError

from maistro.graph import Graph, Node
from maistro.persistence.pg_audit import PgAuditLog
from maistro.persistence.sqlite_audit import SqliteAuditLog
from maistro.projects.pg_scope_store import PgProjectScopeStore
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore
from maistro.runs.model import GraphSnapshot, Run, RunStatus
from maistro.runs.pg_store import PgRunStore
from maistro.runs.sqlite_store import SqliteRunStore
from maistro.runs.store import InMemoryRunStore, RunIntegrityError
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.testing.postgres import postgres_dsn
from maistro.types.security import AuditEntry
from maistro.workspaces.pg_store import PgWorkspaceStore
from maistro.workspaces.sqlite_store import SqliteWorkspaceStore
from maistro.workspaces.store import InMemoryWorkspaceStore

#: Each key is `store:backend:case`. Every entry is a case that does not hold
#: today; its body asserts the unscoped behaviour, so closing it fails the
#: test until the entry is deleted.
KNOWN_GAPS: frozenset[str] = frozenset()

#: Every backend a key may name, whether or not this run collects it: the
#: stale-entry check below must see the PostgreSQL keys on a laptop too.
ALL_BACKENDS = ("memory", "sqlite", "postgres")
SCOPE_CASES = ("read", "mutate")
RUN_CHILD_CASES = ("read_node_run", "read_attempt")
ADMISSION_CASES = ("admission_requires_actor", "admission_rejects_blank_actor")
MODEL_KEYS = ("runs:model:actor_required",)

_REQUIRE_PG = bool(os.environ.get("MAISTRO_REQUIRE_PG_LEGS"))
BACKENDS = ("memory", "sqlite") + (("postgres",) if postgres_dsn() or _REQUIRE_PG else ())

#: What a store may raise to refuse an out-of-scope caller. Absence and denial
#: are both refusals; which one a store picks is its own business.
_REFUSALS: tuple[type[BaseException], ...] = (LookupError, PermissionError)

_TRESPASS = "written-by-an-outsider"


def _key(store: str, backend: str, case: str) -> str:
    return f"{store}:{backend}:{case}"


def _settle(key: str, *, holds: bool, gap_evidence: bool, detail: object) -> None:
    """Assert the invariant, or for a known gap that its unscoped shape persists.

    `gap_evidence` is the specific unscoped behaviour the gap entry describes
    (the outsider got the record, the mutation landed), so a gap entry cannot
    survive a store that changed in some third way.
    """
    if key in KNOWN_GAPS:
        assert not holds, f"{key} now holds: delete it from KNOWN_GAPS (#364)"
        assert gap_evidence, f"{key}: neither scoped nor the recorded gap: {detail!r}"
    else:
        assert holds, f"{key}: {detail!r}"


async def _refused(call: Awaitable[Any]) -> tuple[bool, Any]:
    try:
        return False, await call
    except _REFUSALS:
        return True, None


@dataclass(frozen=True)
class Scope:
    """One principal, the Workspace they own, and the org they log under."""

    principal_id: str
    workspace_id: str
    org_id: str


@dataclass
class Stores:
    backend: str
    workspaces: Any
    projects: Any
    runs: Any
    audit: Any

    async def enrol(self, label: str) -> Scope:
        """A principal and a Workspace nothing else has used.

        PostgreSQL keeps rows between tests and runs, so every id is fresh.
        """
        principal = f"principal-{label}-{uuid4().hex}"
        workspace = await self.workspaces.create(creator_user_id=principal, name=f"WS {label}")
        return Scope(
            principal_id=principal,
            workspace_id=workspace.workspace_id,
            org_id=f"org-{label}-{uuid4().hex}",
        )

    async def project_in(self, scope: Scope) -> str:
        root = await self.projects.root_for_workspace(scope.workspace_id)
        project = await self.projects.create(
            workspace_id=scope.workspace_id,
            parent_project_id=root.project_id,
            name="Scoped",
            defaults={"model": "owner-choice"},
        )
        return str(project.project_id)

    async def run_in(self, scope: Scope, *, actor: str | None) -> Run:
        project_id = await self.project_in(scope)
        run: Run = await self.runs.create_run(
            _graph(scope.workspace_id, project_id), actor_principal_id=actor
        )
        return run


def _graph(workspace_id: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="Scoped graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


@pytest.fixture(params=BACKENDS)
async def stores(
    request: pytest.FixtureRequest, pg_pool: Any, tmp_path: Any
) -> AsyncIterator[Stores]:
    if request.param == "memory":
        projects = InMemoryProjectScopeStore()
        workspaces = InMemoryWorkspaceStore(project_store=projects)
        projects.bind_workspace_store(workspaces)
        runs = InMemoryRunStore(project_store=projects, workspace_store=workspaces)
        yield Stores(
            backend="memory",
            workspaces=workspaces,
            projects=projects,
            runs=runs,
            audit=InMemoryAuditLog(),
        )
        return

    if request.param == "sqlite":
        conn = await aiosqlite.connect(tmp_path / "scope.db")
        try:
            sqlite_projects = SqliteProjectScopeStore(conn)
            await sqlite_projects.ensure_schema()
            workspaces = SqliteWorkspaceStore(conn, project_store=sqlite_projects)
            await workspaces.ensure_schema()
            sqlite_projects.bind_workspace_store(workspaces)
            runs = SqliteRunStore(conn, project_store=sqlite_projects, workspace_store=workspaces)
            await runs.ensure_schema()
            audit = SqliteAuditLog(conn)
            await audit.ensure_schema()
            yield Stores("sqlite", workspaces, sqlite_projects, runs, audit)
        finally:
            await conn.close()
        return

    if pg_pool is None:
        msg = (
            "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: the "
            "PostgreSQL store-boundary scope leg cannot run and must not pass on two backends"
        )
        raise RuntimeError(msg)

    pg_projects = PgProjectScopeStore(pg_pool)
    workspaces = PgWorkspaceStore(pg_pool, project_store=pg_projects)
    pg_projects.bind_workspace_store(workspaces)
    yield Stores(
        backend="postgres",
        workspaces=workspaces,
        projects=pg_projects,
        runs=PgRunStore(pg_pool, project_store=pg_projects, workspace_store=workspaces),
        audit=PgAuditLog(pg_pool),
    )


# ── the per-store adapters ─────────────────────────────────────────


class _ScopeAdapter(Protocol):
    store: ClassVar[str]

    async def create_in(self, stores: Stores, scope: Scope) -> str:
        """Write one record inside `scope` and return its id."""
        ...

    async def read_as(self, stores: Stores, record_id: str, outsider: Scope) -> str | None:
        """Read the record by id as `outsider`; the id seen, or None if refused."""
        ...

    async def mutate_as(self, stores: Stores, record_id: str, outsider: Scope) -> None:
        """Attempt one mutation by id as `outsider`; a refusal may raise."""
        ...

    async def mutated(self, stores: Stores, record_id: str) -> bool:
        """Whether the outsider's mutation is visible to the record's owner."""
        ...


class _WorkspaceAdapter:
    store: ClassVar[str] = "workspaces"

    async def create_in(self, stores: Stores, scope: Scope) -> str:
        return scope.workspace_id

    async def read_as(self, stores: Stores, record_id: str, outsider: Scope) -> str | None:
        workspace = await stores.workspaces.get(
            record_id, principal_id=outsider.principal_id
        )
        return None if workspace is None else str(workspace.workspace_id)

    async def mutate_as(self, stores: Stores, record_id: str, outsider: Scope) -> None:
        # `update` takes the whole record, so the outsider builds it from the
        # same scoped read the `read` case measures.
        current = await stores.workspaces.get(record_id, principal_id=outsider.principal_id)
        if current is None:
            return
        await stores.workspaces.update(
            current.model_copy(update={"name": _TRESPASS}),
            principal_id=outsider.principal_id,
        )

    async def mutated(self, stores: Stores, record_id: str) -> bool:
        workspace = await stores.workspaces.get(record_id)
        return workspace is not None and workspace.name == _TRESPASS


class _ProjectAdapter:
    store: ClassVar[str] = "projects"

    async def create_in(self, stores: Stores, scope: Scope) -> str:
        return await stores.project_in(scope)

    async def read_as(self, stores: Stores, record_id: str, outsider: Scope) -> str | None:
        project = await stores.projects.get(record_id, principal_id=outsider.principal_id)
        return None if project is None else str(project.project_id)

    async def mutate_as(self, stores: Stores, record_id: str, outsider: Scope) -> None:
        await stores.projects.update_defaults(
            record_id, defaults={"model": _TRESPASS}, principal_id=outsider.principal_id
        )

    async def mutated(self, stores: Stores, record_id: str) -> bool:
        project = await stores.projects.get(record_id)
        return project is not None and project.defaults.get("model") == _TRESPASS


class _RunAdapter:
    store: ClassVar[str] = "runs"

    async def create_in(self, stores: Stores, scope: Scope) -> str:
        run = await stores.run_in(scope, actor=scope.principal_id)
        return run.run_id

    async def read_as(self, stores: Stores, record_id: str, outsider: Scope) -> str | None:
        run = await stores.runs.get_run(record_id, principal_id=outsider.principal_id)
        return None if run is None else str(run.run_id)

    async def mutate_as(self, stores: Stores, record_id: str, outsider: Scope) -> None:
        await stores.runs.transition_run(
            record_id, RunStatus.CANCELLED, principal_id=outsider.principal_id
        )

    async def mutated(self, stores: Stores, record_id: str) -> bool:
        run = await stores.runs.get_run(record_id)
        return run is not None and run.status is RunStatus.CANCELLED


class _AuditAdapter:
    """The audit log is append-only and scoped by `org_id` on read.

    It has no by-id mutation, so the nearest an outsider gets is an append
    that reuses the owner's correlation id under their own org; the owner's
    view must be unchanged by it. `test_the_audit_log_has_no_by_id_mutation`
    pins the surface that makes that the nearest.
    """

    store: ClassVar[str] = "audit"

    async def create_in(self, stores: Stores, scope: Scope) -> str:
        request_id = f"req-{uuid4().hex}"
        await stores.audit.log(
            AuditEntry(
                boundary="p0.8",
                user_id=scope.principal_id,
                org_id=scope.org_id,
                request_id=request_id,
                detail="owner",
            )
        )
        self._owner_org = scope.org_id
        return request_id

    async def read_as(self, stores: Stores, record_id: str, outsider: Scope) -> str | None:
        entries = await stores.audit.get_entries(org_id=outsider.org_id)
        seen = [entry.request_id for entry in entries if entry.request_id == record_id]
        return seen[0] if seen else None

    async def mutate_as(self, stores: Stores, record_id: str, outsider: Scope) -> None:
        await stores.audit.log(
            AuditEntry(
                boundary="p0.8",
                user_id=outsider.principal_id,
                org_id=outsider.org_id,
                request_id=record_id,
                detail=_TRESPASS,
            )
        )

    async def mutated(self, stores: Stores, record_id: str) -> bool:
        entries = await stores.audit.get_entries(org_id=self._owner_org)
        owned = [entry for entry in entries if entry.request_id == record_id]
        return [(entry.org_id, entry.detail) for entry in owned] != [(self._owner_org, "owner")]


ADAPTERS: tuple[Callable[[], _ScopeAdapter], ...] = (
    _WorkspaceAdapter,
    _ProjectAdapter,
    _RunAdapter,
    _AuditAdapter,
)


def _adapter_id(factory: Callable[[], _ScopeAdapter]) -> str:
    return factory().store


# ── the cases every store answers ──────────────────────────────────


@pytest.mark.parametrize("make_adapter", ADAPTERS, ids=_adapter_id)
async def test_an_outsider_cannot_read_a_record_by_id(
    stores: Stores, make_adapter: Callable[[], _ScopeAdapter]
) -> None:
    adapter = make_adapter()
    owner = await stores.enrol("owner")
    outsider = await stores.enrol("outsider")
    record_id = await adapter.create_in(stores, owner)

    refused, seen = await _refused(adapter.read_as(stores, record_id, outsider))

    _settle(
        _key(adapter.store, stores.backend, "read"),
        holds=refused or seen is None,
        gap_evidence=seen == record_id,
        detail=seen,
    )


@pytest.mark.parametrize("make_adapter", ADAPTERS, ids=_adapter_id)
async def test_an_outsider_cannot_mutate_a_record_by_id(
    stores: Stores, make_adapter: Callable[[], _ScopeAdapter]
) -> None:
    adapter = make_adapter()
    owner = await stores.enrol("owner")
    outsider = await stores.enrol("outsider")
    record_id = await adapter.create_in(stores, owner)

    await _refused(adapter.mutate_as(stores, record_id, outsider))
    landed = await adapter.mutated(stores, record_id)

    _settle(
        _key(adapter.store, stores.backend, "mutate"),
        holds=not landed,
        gap_evidence=landed,
        detail=landed,
    )


# ── runs: the children of a Run, and who admitted it ───────────────


@pytest.mark.parametrize("case", RUN_CHILD_CASES)
async def test_an_outsider_cannot_read_a_runs_children_by_id(stores: Stores, case: str) -> None:
    owner = await stores.enrol("owner")
    run = await stores.run_in(owner, actor=owner.principal_id)
    node_run = await stores.runs.create_node_run(run.run_id, node_id="node-1")
    attempt = await stores.runs.create_attempt(node_run.node_run_id)

    outsider = await stores.enrol("child-outsider")
    if case == "read_node_run":
        record_id = node_run.node_run_id
        refused, found = await _refused(
            stores.runs.get_node_run(record_id, principal_id=outsider.principal_id)
        )
        seen = None if found is None else found.node_run_id
    else:
        record_id = attempt.attempt_id
        refused, found = await _refused(
            stores.runs.get_attempt(record_id, principal_id=outsider.principal_id)
        )
        seen = None if found is None else found.attempt_id

    _settle(
        _key("runs", stores.backend, case),
        holds=refused or seen is None,
        gap_evidence=seen == record_id,
        detail=seen,
    )


_ADMISSION_REFUSALS = (ValueError, RunIntegrityError)


@pytest.mark.parametrize("case", ADMISSION_CASES)
async def test_a_run_is_admitted_only_with_a_valid_actor(stores: Stores, case: str) -> None:
    owner = await stores.enrol("owner")
    actor = None if case == "admission_requires_actor" else "   "

    try:
        run = await stores.run_in(owner, actor=actor)
    except _ADMISSION_REFUSALS as refusal:
        _settle(
            _key("runs", stores.backend, case),
            holds=True,
            gap_evidence=False,
            detail=refusal,
        )
        return

    stored = await stores.runs.get_run(run.run_id)
    _settle(
        _key("runs", stores.backend, case),
        holds=False,
        gap_evidence=stored is not None and stored.actor_principal_id == actor,
        detail=None if stored is None else stored.actor_principal_id,
    )


def test_the_run_model_requires_an_actor() -> None:
    graph = _graph("ws-model", "project-model")
    try:
        run = Run(
            workspace_id="ws-model",
            project_id="project-model",
            graph=GraphSnapshot.from_graph(graph),
        )
    except ValidationError as refusal:
        _settle("runs:model:actor_required", holds=True, gap_evidence=False, detail=refusal)
        return
    _settle(
        "runs:model:actor_required",
        holds=False,
        gap_evidence=run.actor_principal_id is None,
        detail=run.actor_principal_id,
    )


# ── audit: rows carry their org and reads filter by it ─────────────


async def test_audit_rows_carry_and_filter_by_org_id(stores: Stores) -> None:
    alpha = await stores.enrol("alpha")
    beta = await stores.enrol("beta")
    request_id = f"req-{uuid4().hex}"
    await stores.audit.log(
        AuditEntry(
            boundary="p0.8", user_id=alpha.principal_id, org_id=alpha.org_id, request_id=request_id
        )
    )

    def matching(entries: list[AuditEntry]) -> list[AuditEntry]:
        return [entry for entry in entries if entry.request_id == request_id]

    in_alpha = matching(await stores.audit.get_entries(org_id=alpha.org_id))
    in_beta = matching(await stores.audit.get_entries(org_id=beta.org_id))
    # The empty org is the explicit system scope, not an all-org read.
    in_system = matching(await stores.audit.get_entries(org_id=""))

    assert [entry.org_id for entry in in_alpha] == [alpha.org_id]
    assert in_beta == []
    assert in_system == []


def test_the_audit_log_has_no_by_id_mutation() -> None:
    """Why the audit adapter's "mutate" is an append: there is nothing else.

    A by-id update or delete added to an audit store must arrive with its own
    scoped case here rather than inherit the append's answer.
    """
    allowed = {"log", "get_entries", "ensure_schema"}
    for store in (InMemoryAuditLog, SqliteAuditLog, PgAuditLog):
        public = {
            name
            for name in vars(store)
            if not name.startswith("_") and callable(getattr(store, name))
        }
        assert public <= allowed, (store.__name__, public - allowed)


# ── the gap set itself ─────────────────────────────────────────────


def test_every_known_gap_names_a_real_case() -> None:
    """A misspelt or orphaned entry would excuse nothing and hide nothing."""
    universe = {
        _key(factory().store, backend, case)
        for factory in ADAPTERS
        for backend in ALL_BACKENDS
        for case in SCOPE_CASES
    }
    universe |= {
        _key("runs", backend, case)
        for backend in ALL_BACKENDS
        for case in RUN_CHILD_CASES + ADMISSION_CASES
    }
    universe |= set(MODEL_KEYS)

    assert sorted(KNOWN_GAPS - universe) == []
