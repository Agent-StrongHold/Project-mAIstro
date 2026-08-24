"""One suite over both durable Project scope stores (#132).

Was `test_sqlite_scope_store.py`, which held the whole contract and exercised
only SQLite. `PgProjectScopeStore` landed with #132 and nothing but
`create_root` ever ran against it -- so the tree rules, the downward resource
visibility, the cross-Workspace and cycle refusals and the non-empty delete
refusal were all *claimed* for PostgreSQL and checked for SQLite. Two stores
implementing one contract, with one of them tested, is how they come to
disagree.

The bodies below are the SQLite suite's, generalised. "Reopen" becomes "a fresh
store instance on the same durable substrate", which is what the SQLite version
was really asserting: a new `aiosqlite` connection to the same file, or a new
store on the same pool. Both answer the same question -- does this survive the
object that wrote it.

The PostgreSQL leg needs a real server and skips without one, and a skipped leg
is untested rather than passing: that is exactly the state this file was
written to end. `MAISTRO_REQUIRE_PG_LEGS` turns the skip into a failure in the
jobs that own a server.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from maistro.projects.scope import (
    ProjectIntegrityError,
    ProjectMembership,
    ProjectNotEmpty,
    ProjectNotFound,
    ProjectScopeDenied,
    ProjectScopedResource,
)
from maistro.testing.postgres import postgres_dsn


class _SqliteBackend:
    """A file on disk; each `store()` opens its own connection to it."""

    def __init__(self, tmp_path) -> None:
        self._path = tmp_path / "projects.db"
        self._connections: list = []

    async def store(self):
        import aiosqlite

        from maistro.projects.sqlite_scope_store import SqliteProjectScopeStore

        conn = await aiosqlite.connect(self._path)
        self._connections.append(conn)
        store = SqliteProjectScopeStore(conn)
        await store.ensure_schema()
        return store

    async def close(self) -> None:
        for conn in self._connections:
            await conn.close()


class _PostgresBackend:
    """A migrated database; each `store()` is a new object on the same pool.

    One pool rather than one per store on purpose: the pool is the process's,
    and a store that opened its own would be testing a wiring the container
    never uses.
    """

    def __init__(self, pool) -> None:
        self._pool = pool

    async def store(self):
        from maistro.projects.pg_scope_store import PgProjectScopeStore

        return PgProjectScopeStore(self._pool)

    async def close(self) -> None:
        return None


@pytest.fixture(params=["sqlite", "postgres"])
async def backend(request, tmp_path):
    if request.param == "sqlite":
        made = _SqliteBackend(tmp_path)
        yield made
        await made.close()
        return

    dsn = postgres_dsn()
    if not dsn:
        if os.environ.get("MAISTRO_REQUIRE_PG_LEGS"):
            msg = (
                "MAISTRO_REQUIRE_PG_LEGS is set but MAISTRO_TEST_PG_DSN is empty: "
                "the PostgreSQL scope-store leg cannot run and must not be silently skipped"
            )
            raise RuntimeError(msg)
        pytest.skip("set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database")

    asyncpg = pytest.importorskip("asyncpg")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    try:
        yield _PostgresBackend(pool)
    finally:
        await pool.close()


def _workspace(suffix: str = "") -> str:
    """A workspace nothing else in the database has used.

    PostgreSQL keeps its rows between tests and between runs -- that is the
    point of it -- so a fixed id would inherit a tree an earlier run built.
    """
    return f"ws-{suffix}{uuid4().hex}"


async def test_root_tree_and_creation_defaults_survive_a_fresh_store(backend) -> None:
    workspace_id = _workspace()
    first = await backend.store()

    root = await first.create_root(workspace_id)
    parent = await first.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Parent",
        defaults={"model": "root-choice", "temperature": 0.4},
    )
    child = await first.create(
        workspace_id=workspace_id,
        parent_project_id=parent.project_id,
        name="Child",
        defaults={"temperature": 0.2},
    )

    second = await backend.store()
    reloaded_root = await second.create_root(workspace_id)
    lineage = await second.lineage(child.project_id)
    defaults = await second.resolve_creation_defaults(
        child.project_id,
        workspace_defaults={"model": "workspace", "max_tokens": 1000},
        persona_defaults={"voice": "technical", "temperature": 0.7},
    )

    # `create_root` is idempotent: a second call returns the existing Root
    # rather than a second one, which is what makes it safe on every startup.
    assert reloaded_root.project_id == root.project_id
    assert [project.project_id for project in lineage] == [
        root.project_id,
        parent.project_id,
        child.project_id,
    ]
    assert defaults == {
        "model": "root-choice",
        "max_tokens": 1000,
        "voice": "technical",
        "temperature": 0.2,
    }


async def test_memberships_and_resources_survive_with_downward_visibility(backend) -> None:
    workspace_id = _workspace()
    first = await backend.store()

    root = await first.create_root(workspace_id)
    left = await first.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Left"
    )
    leaf = await first.create(
        workspace_id=workspace_id, parent_project_id=left.project_id, name="Leaf"
    )
    right = await first.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Right"
    )
    membership = await first.set_membership(
        ProjectMembership(
            workspace_id=workspace_id,
            project_id=left.project_id,
            principal_id="principal-1",
            grants={"publish"},
            delegable_grants={"publish"},
        )
    )
    for resource_id, project_id, resource_type in (
        ("root-credential", root.project_id, "credential"),
        ("left-binding", left.project_id, "binding"),
        ("leaf-secret", leaf.project_id, "credential"),
    ):
        await first.put_resource(
            ProjectScopedResource(
                # Namespaced per run: resource ids are unique across the whole
                # store, so a fixed one collides with the previous run's row.
                resource_id=f"{workspace_id}-{resource_id}",
                workspace_id=workspace_id,
                project_id=project_id,
                resource_type=resource_type,
            )
        )

    second = await backend.store()
    reloaded = await second.memberships_for(left.project_id, principal_id="principal-1")

    def visible(project_id: str):
        return {
            item.resource_id.removeprefix(f"{workspace_id}-") for item in visible_rows[project_id]
        }

    visible_rows = {
        leaf.project_id: await second.visible_resources(leaf.project_id),
        left.project_id: await second.visible_resources(left.project_id),
        right.project_id: await second.visible_resources(right.project_id),
    }

    assert [item.membership_id for item in reloaded] == [membership.membership_id]
    assert reloaded[0].grants == {"publish"}
    # Downward only: a leaf sees its ancestors' resources, a sibling sees none
    # of them. A resource flowing sideways is a credential leaking between
    # projects that were separated on purpose.
    assert visible(leaf.project_id) == {"root-credential", "left-binding", "leaf-secret"}
    assert visible(left.project_id) == {"root-credential", "left-binding"}
    assert visible(right.project_id) == {"root-credential"}


async def test_the_tree_rejects_cross_workspace_moves_cycles_and_root_mutation(backend) -> None:
    store = await backend.store()
    workspace_a = _workspace("a-")
    workspace_b = _workspace("b-")
    root_a = await store.create_root(workspace_a)
    root_b = await store.create_root(workspace_b)
    parent = await store.create(
        workspace_id=workspace_a, parent_project_id=root_a.project_id, name="Parent"
    )
    child = await store.create(
        workspace_id=workspace_a, parent_project_id=parent.project_id, name="Child"
    )

    with pytest.raises(ProjectIntegrityError, match="Root Project cannot be moved"):
        await store.move_project(root_a.project_id, parent_project_id=parent.project_id)
    with pytest.raises(ProjectIntegrityError, match="across Workspaces"):
        await store.move_project(parent.project_id, parent_project_id=root_b.project_id)
    with pytest.raises(ProjectIntegrityError, match="cycle"):
        await store.move_project(parent.project_id, parent_project_id=child.project_id)
    with pytest.raises(ProjectIntegrityError, match="Root Project cannot be deleted"):
        await store.delete(root_a.project_id)


async def test_delete_requires_an_explicitly_empty_project(backend) -> None:
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    parent = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Parent"
    )
    child = await store.create(
        workspace_id=workspace_id, parent_project_id=parent.project_id, name="Child"
    )

    with pytest.raises(ProjectNotEmpty, match="child Projects"):
        await store.delete(parent.project_id)

    await store.delete(child.project_id)
    await store.delete(parent.project_id)
    assert await store.get(parent.project_id) is None


async def test_a_move_reparents_and_relineages(backend) -> None:
    """`move_project`'s success path, which the refusal test never reaches."""
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    left = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Left"
    )
    right = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Right"
    )
    moved = await store.create(
        workspace_id=workspace_id, parent_project_id=left.project_id, name="Moved"
    )

    await store.move_project(moved.project_id, parent_project_id=right.project_id)

    lineage = await store.lineage(moved.project_id)
    assert [p.project_id for p in lineage] == [root.project_id, right.project_id, moved.project_id]
    assert [p.project_id for p in await store.list_children(left.project_id)] == []
    assert [p.project_id for p in await store.list_children(right.project_id)] == [moved.project_id]


async def test_updated_defaults_reach_a_descendants_resolution(backend) -> None:
    """`update_defaults`, and that resolution reads the stored value rather
    than one cached on the object that wrote it."""
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    parent = await store.create(
        workspace_id=workspace_id,
        parent_project_id=root.project_id,
        name="Parent",
        defaults={"model": "before"},
    )
    child = await store.create(
        workspace_id=workspace_id, parent_project_id=parent.project_id, name="Child"
    )

    await store.update_defaults(parent.project_id, defaults={"model": "after"})

    fresh = await backend.store()
    resolved = await fresh.resolve_creation_defaults(
        child.project_id, workspace_defaults={}, persona_defaults={}
    )
    assert resolved["model"] == "after"


async def test_a_project_owning_runs_cannot_be_deleted(backend) -> None:
    """The rule each backend expresses in its own way.

    SQLite asks the Run store through a registered predicate, because the Run
    tables belong to `runs.sqlite_store` and this store will not join across
    them. PostgreSQL states the same rule as a foreign key. Either way deleting
    the Project would leave Run history citing a Project that is gone -- so the
    store that has a predicate to register must actually consult it, which is
    what goes untested when only the foreign-key backend is exercised.
    """
    store = await backend.store()
    register = getattr(store, "set_run_owner", None)
    if register is None:
        pytest.skip("this backend enforces the rule with a foreign key, not a predicate")

    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    project = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Owns runs"
    )

    async def owns_runs(project_id: str) -> bool:
        return project_id == project.project_id

    register(owns_runs)

    with pytest.raises(ProjectNotEmpty, match="canonical Runs"):
        await store.delete(project.project_id)

    assert await store.get(project.project_id) is not None


# ── the refusals that keep one Workspace out of another ────────────


async def test_a_parent_in_another_workspace_is_refused(backend) -> None:
    store = await backend.store()
    workspace_a, workspace_b = _workspace("a-"), _workspace("b-")
    root_a = await store.create_root(workspace_a)
    await store.create_root(workspace_b)

    with pytest.raises(ProjectIntegrityError, match="same Workspace"):
        await store.create(
            workspace_id=workspace_b, parent_project_id=root_a.project_id, name="Trespass"
        )


async def test_a_membership_must_match_its_projects_workspace(backend) -> None:
    """The membership carries a `workspace_id` of its own, so the two can
    disagree — and a membership filed under the wrong Workspace is a grant
    someone in that Workspace did not make."""
    store = await backend.store()
    workspace_id = _workspace()
    other = _workspace("other-")
    root = await store.create_root(workspace_id)

    with pytest.raises(ProjectIntegrityError, match="Workspace does not match"):
        await store.set_membership(
            ProjectMembership(
                workspace_id=other,
                project_id=root.project_id,
                principal_id="principal-1",
                grants={"publish"},
            )
        )


async def test_a_resource_must_match_its_projects_workspace(backend) -> None:
    store = await backend.store()
    workspace_id = _workspace()
    other = _workspace("other-")
    root = await store.create_root(workspace_id)

    with pytest.raises(ProjectIntegrityError, match="Workspace does not match"):
        await store.put_resource(
            ProjectScopedResource(
                resource_id=f"{workspace_id}-stray",
                workspace_id=other,
                project_id=root.project_id,
                resource_type="credential",
            )
        )


async def test_a_project_cannot_be_its_own_parent(backend) -> None:
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    project = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Solo"
    )

    with pytest.raises(ProjectIntegrityError, match="its own parent"):
        await store.move_project(project.project_id, parent_project_id=project.project_id)


async def test_an_empty_workspace_id_is_refused(backend) -> None:
    """A Root Project for the empty Workspace would be a Root every unscoped
    caller shares."""
    store = await backend.store()

    with pytest.raises(ValueError, match="non-empty"):
        await store.create_root("")


async def test_a_workspace_with_no_root_reports_not_found(backend) -> None:
    store = await backend.store()

    with pytest.raises(ProjectNotFound):
        await store.root_for_workspace(_workspace("never-created-"))


# ── validate_required_resources ────────────────────────────────────


async def test_required_resources_a_project_can_see_are_accepted(backend) -> None:
    """The check a cross-Project move consults before it is allowed."""
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    child = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Child"
    )
    resource_id = f"{workspace_id}-inherited"
    await store.put_resource(
        ProjectScopedResource(
            resource_id=resource_id,
            workspace_id=workspace_id,
            project_id=root.project_id,
            resource_type="credential",
        )
    )

    # Inherited from the ancestor, so visible: no raise.
    await store.validate_required_resources(child.project_id, {resource_id})


async def test_required_resources_a_project_cannot_see_are_denied(backend) -> None:
    """And the refusal names them, because "denied" without which resource
    leaves the caller nothing to act on."""
    store = await backend.store()
    workspace_id = _workspace()
    root = await store.create_root(workspace_id)
    left = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Left"
    )
    right = await store.create(
        workspace_id=workspace_id, parent_project_id=root.project_id, name="Right"
    )
    hidden = f"{workspace_id}-left-only"
    await store.put_resource(
        ProjectScopedResource(
            resource_id=hidden,
            workspace_id=workspace_id,
            project_id=left.project_id,
            resource_type="credential",
        )
    )

    with pytest.raises(ProjectScopeDenied, match=hidden):
        await store.validate_required_resources(right.project_id, {hidden})
