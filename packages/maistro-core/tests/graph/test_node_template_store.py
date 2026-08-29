"""One suite, three NodeTemplate registries (#556).

`GraphTemplate` has had a durable home since #145. `NodeTemplate` had none, so
`SPEC-081226-bb3a` AC-12 — a template and the object instantiated from it
resolve the same provenance after a reopen — could hold for only one of the two
template families. A Node records `source_template` naming a
`(template_id, version)` and a content hash; with nowhere to register the
NodeTemplate, that provenance named something no process could resolve once the
one that made it exited.

The in-memory store is inside this suite rather than beside it: it is the
definition of the contract, so running the same bodies against it and against
the two durable stores makes "the durable ones behave like the reference" a
comparison rather than a claim.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from maistro.graph.definitions import NodeTemplate
from maistro.graph.templates import (
    InMemoryNodeTemplateStore,
    NodeTemplateConflict,
    NodeTemplateNotFound,
    require_node_template,
)

WORKSPACE = "node-template-workspace"


class _Backend:
    """A backend, and the ability to open a SECOND store over the same state.

    `reopen()` is what makes AC-12 checkable. The criterion is about provenance
    surviving a restart, and a test holding one store instance cannot see the
    difference between "persisted" and "still in the object I just put it in" --
    which is exactly what the first version of this suite failed to distinguish
    (Codex, #563). A durable backend hands back a new store over the same
    database; the in-memory reference cannot, and says so.
    """

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.durable = kind != "memory"
        self._pg_pool: Any = None
        self._path: Any = None
        self._connections: list[Any] = []
        self._memory: Any = None

    async def store(self) -> Any:
        if self.kind == "postgres":
            from maistro.graph.pg_templates import PgNodeTemplateStore

            return PgNodeTemplateStore(self._pg_pool)
        if self.kind == "sqlite":
            import aiosqlite

            from maistro.graph.sqlite_templates import SqliteNodeTemplateStore

            conn = await aiosqlite.connect(self._path)
            self._connections.append(conn)
            made = SqliteNodeTemplateStore(conn)
            await made.ensure_schema()
            return made
        return self._memory

    async def close(self) -> None:
        # Closed rather than dropped: aiosqlite runs its connection on a
        # non-daemon thread, and a live one blocks interpreter shutdown.
        for conn in self._connections:
            await conn.close()


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def backend(request: pytest.FixtureRequest, pg_pool: Any, tmp_path: Any) -> Any:
    """All three backends the spine can select.

    The PostgreSQL leg must actually run in CI rather than skip — #135's
    lesson, and the reason `MAISTRO_REQUIRE_PG_LEGS` exists: a skipped leg is
    untested, not passing, and the durable store is the only one where the
    JSONB round trip and the upsert predicate mean anything.

    SQLite is a file rather than `:memory:` so a reopen is a real reopen. A
    `:memory:` database lives inside its connection, so "open a second store"
    would have meant "open an empty one" — which would have made the reload
    test pass for the wrong reason on one backend and fail on the other.
    """
    made = _Backend(request.param)
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        made._pg_pool = pg_pool
    elif request.param == "sqlite":
        made._path = tmp_path / "node_templates.db"
    else:
        made._memory = InMemoryNodeTemplateStore()
    try:
        yield made
    finally:
        await made.close()


@pytest.fixture
async def store(backend: Any) -> Any:
    """The one store most of these tests need."""
    return await backend.store()


def _template(
    *,
    template_id: str,
    version: int = 1,
    name: str = "summariser",
    node_type: str = "agent",
    workspace_id: str = WORKSPACE,
    parameters: dict[str, Any] | None = None,
) -> NodeTemplate:
    return NodeTemplate(
        template_id=template_id,
        workspace_id=workspace_id,
        version=version,
        name=name,
        node_type=node_type,
        parameters=parameters if parameters is not None else {"model": "haiku"},
        metadata={"team": "platform"},
    )


def _ids(request: pytest.FixtureRequest, suffix: str = "") -> str:
    """A template id unique to this test — PostgreSQL rows outlive the test."""
    return f"ntpl-{request.node.name}{suffix}"


# ── registration and lookup ───────────────────────────────────────


async def test_a_registered_template_resolves(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))

    found = await store.get(template_id)

    assert found is not None
    assert found.template_id == template_id
    assert found.node_type == "agent"
    assert found.parameters == {"model": "haiku"}


async def test_an_unregistered_template_is_none(store: Any) -> None:
    assert await store.get("nothing-registered") is None


async def test_the_content_hash_survives_the_round_trip(store: Any, request: Any) -> None:
    """It is provenance: an instantiated Node cites it, and an audit compares
    against it. A hash that changed across a store round trip would make every
    such comparison report tampering."""
    template_id = _ids(request)
    original = _template(template_id=template_id)
    await store.put(original)

    found = await store.get(template_id)

    assert found is not None
    assert found.content_hash == original.content_hash


@pytest.mark.ac("SPEC-081226-bb3a/AC-12")
async def test_provenance_resolves_identically_after_a_reopen(backend: Any, request: Any) -> None:
    """AC-12, through an actual reopen rather than the same store object.

    The first version of this held one store instance and called `get()` on it,
    which proves nothing about a restart: the in-memory leg would lose
    everything, and the SQLite leg kept the same connection open. A marker that
    promotes a criterion to `covered` while the test cannot fail for the reason
    the criterion names is worse than no marker (Codex, #563).

    So: register through one store, drop it, open a second over the same
    database, and require the Node's recorded provenance to still name the
    template exactly — same id, same version, same hash.
    """
    if not backend.durable:
        pytest.skip("the in-memory reference has no restart to survive; that is the point")

    template_id = _ids(request)
    template = _template(template_id=template_id)
    writer = await backend.store()
    await writer.put(template)
    node = template.instantiate()
    del writer

    reader = await backend.store()
    reopened = await reader.get(template_id, version=1)

    assert reopened is not None
    assert node.source_template is not None
    assert node.source_template.template_id == reopened.template_id
    assert node.source_template.template_version == reopened.version
    assert node.source_template.template_hash == reopened.content_hash


async def test_the_reference_keeps_provenance_within_one_process(store: Any, request: Any) -> None:
    """The in-memory leg's half of the same property, unmarked.

    It cannot answer AC-12 — there is no reopen — but the contract it defines
    still has to hold, and leaving it untested because it cannot carry the
    marker would drop the reference out of the comparison the durable stores
    are measured against.
    """
    template_id = _ids(request)
    template = _template(template_id=template_id)
    await store.put(template)
    node = template.instantiate()

    found = await store.get(template_id, version=1)

    assert found is not None
    assert node.source_template is not None
    assert node.source_template.template_hash == found.content_hash


# ── versions ──────────────────────────────────────────────────────


@pytest.mark.ac("SPEC-081226-bb3a/AC-7")
async def test_publishing_a_new_version_leaves_the_old_one_addressable(
    store: Any, request: Any
) -> None:
    """AC-7. The old version is not merely still listed — it still reads back
    with its own content, which is what a Node that cites it needs."""
    template_id = _ids(request)
    first = _template(template_id=template_id, version=1, parameters={"model": "haiku"})
    await store.put(first)
    await store.put(_template(template_id=template_id, version=2, parameters={"model": "opus"}))

    kept = await store.get(template_id, version=1)
    current = await store.get(template_id)

    assert kept is not None and current is not None
    assert kept.parameters == {"model": "haiku"}
    assert kept.content_hash == first.content_hash
    assert current.version == 2
    assert await store.versions(template_id) == [1, 2]


async def test_get_without_a_version_returns_the_latest(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await store.put(_template(template_id=template_id, version=3, parameters={"model": "opus"}))

    found = await store.get(template_id)

    assert found is not None
    assert found.version == 3


async def test_versions_of_an_unknown_template_is_empty(store: Any) -> None:
    assert await store.versions("nothing-registered") == []


# ── redefinition ──────────────────────────────────────────────────


async def test_registering_identical_content_again_is_a_no_op(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))
    await store.put(_template(template_id=template_id))

    assert await store.versions(template_id) == [1]


async def test_redefining_a_version_with_other_content_is_refused(store: Any, request: Any) -> None:
    """The rule AC-7 rests on. A Node's `source_template` records the version
    and the hash, so silently redefining a version would make every object that
    already cites it cite something it never came from."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, parameters={"model": "haiku"}))

    with pytest.raises(NodeTemplateConflict):
        await store.put(_template(template_id=template_id, parameters={"model": "opus"}))


async def test_the_refused_write_leaves_the_stored_version_intact(store: Any, request: Any) -> None:
    """A refusal that had already written half of itself would be worse than
    no refusal: the caller sees an error and the row is changed anyway."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, parameters={"model": "haiku"}))

    with pytest.raises(NodeTemplateConflict):
        await store.put(_template(template_id=template_id, parameters={"model": "opus"}))

    found = await store.get(template_id, version=1)
    assert found is not None
    assert found.parameters == {"model": "haiku"}


async def test_two_concurrent_publishers_cannot_both_win(store: Any, request: Any) -> None:
    """The conflict decision is one statement, not a read then a write.

    `aiosqlite` serialises individual statements, not a read-then-write pair
    spanning an `await`. So two coroutines publishing different content under
    one `(template_id, version)` could both observe no row, and the second
    `INSERT OR REPLACE` would overwrite the first silently — destroying the
    immutable version this store exists to keep, without raising (Codex, #563).

    Exactly one must win, and whichever loses must raise rather than be
    absorbed. Which one wins is not the property; that only one does, is.
    """
    template_id = _ids(request)
    first = _template(template_id=template_id, parameters={"model": "haiku"})
    second = _template(template_id=template_id, parameters={"model": "opus"})

    results = await asyncio.gather(store.put(first), store.put(second), return_exceptions=True)

    refused = [r for r in results if isinstance(r, NodeTemplateConflict)]
    accepted = [r for r in results if not isinstance(r, BaseException)]
    assert len(accepted) == 1, results
    assert len(refused) == 1, results

    stored = await store.get(template_id, version=1)
    assert stored is not None
    assert stored.content_hash == accepted[0].content_hash


async def test_re_registering_under_another_workspace_moves_every_column(
    store: Any, request: Any
) -> None:
    """A promoted column may not disagree with the payload it was promoted from.

    `workspace_id`, `name` and `node_type` are copies of payload fields, lifted
    into columns so a listing is an index scan rather than a scan of JSON. The
    content hash excludes `workspace_id`, so identical content under a
    different Workspace matches the upsert predicate — and PostgreSQL updated
    the payload alone, leaving the column behind. `get` then reported the new
    Workspace while `list_for_workspace` still filed it under the old one, and
    neither SQLite nor the reference agreed with either (Codex, #563).
    """
    template_id = _ids(request)
    old_workspace = f"{WORKSPACE}-{template_id}-old"
    new_workspace = f"{WORKSPACE}-{template_id}-new"
    await store.put(_template(template_id=template_id, workspace_id=old_workspace))

    await store.put(_template(template_id=template_id, workspace_id=new_workspace))

    found = await store.get(template_id, version=1)
    assert found is not None
    assert found.workspace_id == new_workspace
    assert [t.template_id for t in await store.list_for_workspace(new_workspace)] == [template_id]
    assert await store.list_for_workspace(old_workspace) == []


# ── listing ───────────────────────────────────────────────────────


async def test_listing_is_scoped_to_one_workspace(store: Any, request: Any) -> None:
    mine = _ids(request, "-mine")
    theirs = _ids(request, "-theirs")
    await store.put(_template(template_id=mine, workspace_id=f"{WORKSPACE}-{mine}"))
    await store.put(_template(template_id=theirs, workspace_id=f"{WORKSPACE}-{theirs}"))

    found = await store.list_for_workspace(f"{WORKSPACE}-{mine}")

    assert [template.template_id for template in found] == [mine]


# ── resolution errors ─────────────────────────────────────────────


async def test_requiring_an_unregistered_template_says_so(store: Any) -> None:
    with pytest.raises(NodeTemplateNotFound, match="is registered"):
        await require_node_template(store, "nothing-registered")


async def test_requiring_a_missing_version_lists_the_ones_there_are(
    store: Any, request: Any
) -> None:
    """The two failures read differently on purpose: "no such template" is a
    configuration mistake, "no such version" is usually a rollback."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))

    with pytest.raises(NodeTemplateNotFound, match="has no version 7"):
        await require_node_template(store, template_id, version=7)


async def test_requiring_a_registered_template_returns_it(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))

    found = await require_node_template(store, template_id)

    assert found.template_id == template_id
