"""One suite, three GraphTemplate registries (#145).

`Schedule.graph_template_id` has always been the field a firing resolves, and
nothing resolved it because there was nowhere to look it up. The property that
matters most here is not lookup — it is that a registered version cannot be
quietly redefined. A Run's `source_template` records the version *and* the
content hash it instantiated from, so overwriting a version would make every
Run that already cites it cite something else.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.graph.templates import (
    GraphTemplateConflict,
    GraphTemplateNotFound,
    InMemoryGraphTemplateStore,
    require_template,
)

WORKSPACE = "template-workspace"


@pytest.fixture(params=["memory", "sqlite", "postgres"])
async def store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """All three backends `wire_execution_spine` can select.

    SQLite was missing from this list while `SqliteGraphTemplateStore` was
    already wired for a `sqlite:` deployment — an implementation with no test
    at all, which is the same shape as the untested `PgStrikeTracker` that #134
    exists for. A registry whose redefinition refusal has never run is a
    registry that may not have one.
    """
    if request.param == "postgres":
        if pg_pool is None:
            pytest.skip("MAISTRO_TEST_PG_DSN is not set")
        from maistro.graph.pg_templates import PgGraphTemplateStore

        yield PgGraphTemplateStore(pg_pool)
        return
    if request.param == "sqlite":
        import aiosqlite

        from maistro.graph.sqlite_templates import SqliteGraphTemplateStore

        # Closed rather than dropped: aiosqlite runs its connection on a
        # non-daemon thread, and a live one blocks interpreter shutdown — a
        # suite that passes every test and then hangs on exit.
        conn = await aiosqlite.connect(":memory:")
        made = SqliteGraphTemplateStore(conn)
        await made.ensure_schema()
        try:
            yield made
        finally:
            await conn.close()
        return
    yield InMemoryGraphTemplateStore()


def _template(
    *,
    template_id: str,
    version: int = 1,
    node_name: str = "a",
    workspace_id: str = WORKSPACE,
) -> GraphTemplate:
    first = Node(node_id="n1", node_type="agent", name=node_name)
    second = Node(node_id="n2", node_type="agent", name="b")
    return GraphTemplate(
        template_id=template_id,
        workspace_id=workspace_id,
        version=version,
        name="daily status",
        nodes=[first, second],
        edges=[Edge(edge_id="e1", from_node="n1", to_node="n2")],
    )


def _ids(request: pytest.FixtureRequest, suffix: str = "") -> str:
    """A template id unique to this test — PostgreSQL rows outlive the test."""
    return f"tpl-{request.node.name}{suffix}"


# ── registration and lookup ───────────────────────────────────────


async def test_a_registered_template_resolves(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))

    found = await store.get(template_id)

    assert found is not None
    assert found.template_id == template_id
    assert [node.name for node in found.nodes] == ["a", "b"]


async def test_an_unregistered_template_is_none(store: Any) -> None:
    assert await store.get("nothing-registered") is None


async def test_the_edges_survive_the_round_trip(store: Any, request: Any) -> None:
    """A template that came back without its edges would instantiate a Graph
    with no topology — every node an entry point, which is not the same Graph."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))

    found = await store.get(template_id)

    assert found is not None
    assert [(edge.from_node, edge.to_node) for edge in found.edges] == [("n1", "n2")]


async def test_the_content_hash_survives_the_round_trip(store: Any, request: Any) -> None:
    """It is provenance: a Run cites it, and an audit compares against it."""
    template_id = _ids(request)
    original = _template(template_id=template_id)
    await store.put(original)

    found = await store.get(template_id)

    assert found is not None
    assert found.content_hash == original.content_hash


# ── versions ──────────────────────────────────────────────────────


async def test_no_version_resolves_the_latest(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1, node_name="old"))
    await store.put(_template(template_id=template_id, version=3, node_name="new"))
    await store.put(_template(template_id=template_id, version=2, node_name="middle"))

    found = await store.get(template_id)

    assert found is not None
    assert found.version == 3
    assert found.nodes[0].name == "new"


async def test_an_explicit_version_resolves_that_version(store: Any, request: Any) -> None:
    """A schedule pinned to a version must keep getting that version after a
    newer one lands — otherwise pinning means nothing."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1, node_name="old"))
    await store.put(_template(template_id=template_id, version=2, node_name="new"))

    found = await store.get(template_id, version=1)

    assert found is not None
    assert found.nodes[0].name == "old"


async def test_versions_are_listed_in_order(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=3))
    await store.put(_template(template_id=template_id, version=1))

    assert await store.versions(template_id) == [1, 3]


async def test_versions_of_an_unknown_template_are_empty(store: Any) -> None:
    assert await store.versions("nothing-registered") == []


# ── a version is immutable once registered ────────────────────────


async def test_registering_identical_content_again_is_a_no_op(store: Any, request: Any) -> None:
    """Idempotent, so a startup that re-registers its templates is not an
    error the second time the process boots."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))
    await store.put(_template(template_id=template_id))

    assert await store.versions(template_id) == [1]


async def test_redefining_a_version_is_refused(store: Any, request: Any) -> None:
    """The property the whole registry exists to hold. Silently overwriting
    would make every Run that already cited this version cite something else."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, node_name="original"))

    with pytest.raises(GraphTemplateConflict):
        await store.put(_template(template_id=template_id, node_name="different"))


async def test_a_refused_redefinition_leaves_the_original(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, node_name="original"))

    with pytest.raises(GraphTemplateConflict):
        await store.put(_template(template_id=template_id, node_name="different"))

    found = await store.get(template_id)
    assert found is not None
    assert found.nodes[0].name == "original"


# ── scope ─────────────────────────────────────────────────────────


async def test_listing_is_scoped_to_one_workspace(store: Any, request: Any) -> None:
    mine = _ids(request, "-mine")
    theirs = _ids(request, "-theirs")
    workspace = f"{WORKSPACE}-{request.node.name}"
    await store.put(_template(template_id=mine, workspace_id=workspace))
    await store.put(_template(template_id=theirs, workspace_id="somebody-else"))

    listed = await store.list_for_workspace(workspace)

    assert [template.template_id for template in listed] == [mine]


# ── the resolver refuses precisely ────────────────────────────────


async def test_require_template_names_a_missing_template(store: Any) -> None:
    with pytest.raises(GraphTemplateNotFound, match="is registered"):
        await require_template(store, "nothing-registered")


async def test_require_template_distinguishes_a_missing_version(store: Any, request: Any) -> None:
    """ "No such template" is a configuration mistake; "no such version" is
    usually a rollback. A caller reading the message should be able to tell."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))

    with pytest.raises(GraphTemplateNotFound, match="registered versions: 1"):
        await require_template(store, template_id, version=7)


async def test_require_template_returns_what_it_found(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id))

    assert (await require_template(store, template_id)).template_id == template_id


class TestContentIsValidatedWhereItBecomesARecord:
    """A template validated at construction can be edited into an invalid one.

    Found by review of #555 and carried to #556. Every content field is a
    mutable `dict` or `list`, and pydantic validators run when the model is
    built — so the object a store is handed is not necessarily the object that
    was checked:

        template = GraphTemplate(nodes=[a, b], edges=[a_to_b])   # validated
        template.nodes.pop()                                     # nothing runs
        await store.put(template)                                # persisted

    `validate_assignment` does not close it: it fires on rebinding a field, not
    on mutating what the field points at. The boundary that can is the one
    where content stops being a local object and becomes a record, so `put`
    revalidates on every backend.

    The rule exercised here is the one the model carries today — an edge whose
    endpoints are not in the graph. `revalidated` re-runs the *model's*
    validators rather than any named rule, so R12's refusal of live execution
    state in template content (#555) is enforced here too the moment it lands,
    without this seam learning about it.
    """

    async def test_a_template_mutated_into_an_invalid_one_is_refused(
        self, store: Any, request: Any
    ) -> None:
        template = _template(template_id=_ids(request))
        template.nodes.pop()  # the edge now names a node the graph lacks

        with pytest.raises(ValidationError, match="outside graph template"):
            await store.put(template)

    async def test_the_refused_template_did_not_reach_the_store(
        self, store: Any, request: Any
    ) -> None:
        """Refusing after writing would be worse than not refusing."""
        template_id = _ids(request)
        template = _template(template_id=template_id)
        template.nodes.pop()

        with pytest.raises(ValidationError):
            await store.put(template)

        assert await store.get(template_id) is None

    async def test_an_unmutated_template_still_stores(self, store: Any, request: Any) -> None:
        """The guard must not cost the ordinary path anything."""
        template_id = _ids(request)
        await store.put(_template(template_id=template_id))

        assert await store.get(template_id) is not None
