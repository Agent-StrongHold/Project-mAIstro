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


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """All three backends the spine can select.

    The PostgreSQL leg must actually run in CI rather than skip — #135's
    lesson, and the reason `MAISTRO_REQUIRE_PG_LEGS` exists: a skipped leg is
    untested, not passing, and the durable store is the only one where the
    JSONB round trip and the upsert predicate mean anything.
    """
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.graph.pg_templates import PgNodeTemplateStore

        yield PgNodeTemplateStore(pg_pool)
        return
    if request.param == "sqlite":
        import aiosqlite

        from maistro.graph.sqlite_templates import SqliteNodeTemplateStore

        # Closed rather than dropped: aiosqlite runs its connection on a
        # non-daemon thread, and a live one blocks interpreter shutdown.
        conn = await aiosqlite.connect(":memory:")
        made = SqliteNodeTemplateStore(conn)
        await made.ensure_schema()
        try:
            yield made
        finally:
            await conn.close()
        return
    yield InMemoryNodeTemplateStore()


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
async def test_provenance_resolves_identically_after_a_reopen(store: Any, request: Any) -> None:
    """AC-12, stated as the round trip it is about.

    The Node is instantiated from the template held in memory; the template is
    then read back out of the store, and the Node's recorded provenance must
    still name it exactly — same id, same version, same hash.
    """
    template_id = _ids(request)
    template = _template(template_id=template_id)
    await store.put(template)
    node = template.instantiate()

    reopened = await store.get(template_id, version=1)

    assert reopened is not None
    assert node.source_template is not None
    assert node.source_template.template_id == reopened.template_id
    assert node.source_template.template_version == reopened.version
    assert node.source_template.template_hash == reopened.content_hash


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


async def test_redefining_a_version_with_other_content_is_refused(
    store: Any, request: Any
) -> None:
    """The rule AC-7 rests on. A Node's `source_template` records the version
    and the hash, so silently redefining a version would make every object that
    already cites it cite something it never came from."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, parameters={"model": "haiku"}))

    with pytest.raises(NodeTemplateConflict):
        await store.put(_template(template_id=template_id, parameters={"model": "opus"}))


async def test_the_refused_write_leaves_the_stored_version_intact(
    store: Any, request: Any
) -> None:
    """A refusal that had already written half of itself would be worse than
    no refusal: the caller sees an error and the row is changed anyway."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, parameters={"model": "haiku"}))

    with pytest.raises(NodeTemplateConflict):
        await store.put(_template(template_id=template_id, parameters={"model": "opus"}))

    found = await store.get(template_id, version=1)
    assert found is not None
    assert found.parameters == {"model": "haiku"}


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
