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
    PromotionApproval,
    promote_audited,
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


# ── candidate lifecycle and promotion (ADR-082926-65bf) ───────────


class _RecordingAudit:
    """A promotion audit sink that remembers, and can be told to fail."""

    def __init__(self, fail_on: str = "") -> None:
        self.entries: list[tuple[str, str, int]] = []
        self._fail_on = fail_on

    async def record(self, event: str, template_id: str, version: int) -> None:
        if event == self._fail_on:
            raise RuntimeError("audit sink unavailable")
        self.entries.append((event, template_id, version))


def _approval() -> PromotionApproval:
    """The policy decision AC-11's third clause requires.

    A required argument rather than a mutable field, so there is no state for
    an idempotent `put` to overwrite and no default that could be permissive.
    """
    return PromotionApproval(approver="release-owner", reason="benchmarks cleared")


async def _improve(store: Any, template_id: str, *, from_version: int) -> NodeTemplate:
    """An improvement path: propose a changed definition as a candidate.

    This stands in for whatever proposes the improvement. It is *not*
    `maistro-evolve` — no file there imports `NodeTemplate` or `GraphTemplate`,
    and that bridge is deliberately out of scope on #588. What AC-11 is proved
    against here is that the template layer can hold a candidate and refuses to
    serve one by default; nobody should read the marker below as evidence that
    Evolve proposes template versions today.
    """
    published = await store.get(template_id, version=from_version)
    assert published is not None
    candidate = published.model_copy(
        deep=True,
        update={
            "version": from_version + 1,
            "lifecycle": "candidate",
            "parameters": {"model": "opus"},
        },
    )
    await store.put(candidate)
    return candidate


@pytest.mark.ac("SPEC-081226-bb3a/AC-11")
async def test_an_improvement_produces_a_candidate_and_leaves_the_published_version_alone(
    store: Any, request: Any
) -> None:
    """R14's three clauses, in the order the scenario states them.

    The clause that needs a real mechanism is the middle one. "The published
    version is unchanged" is trivially true of a store that appends a version;
    what is not trivial is that the published version is still *what everyone
    gets*. A candidate that quietly became the answer to an unversioned lookup
    would satisfy a naive reading of all three clauses and be exactly the
    silent mutation R14 exists to prevent.
    """
    template_id = _ids(request)
    published = _template(template_id=template_id, version=1, parameters={"model": "haiku"})
    await store.put(published)

    candidate = await _improve(store, template_id, from_version=1)

    # "Then a candidate version is produced"
    assert candidate.lifecycle == "candidate"
    assert await store.lifecycle_of(template_id, 2) == "candidate"
    assert await store.versions(template_id) == [1, 2]

    # "And the published version is unchanged" -- both as content and as the
    # answer to an unversioned lookup.
    kept = await store.get(template_id, version=1)
    current = await store.get(template_id)
    assert kept is not None and current is not None
    assert kept.content_hash == published.content_hash
    assert kept.parameters == {"model": "haiku"}
    assert current.version == 1
    assert current.parameters == {"model": "haiku"}

    # A candidate is still addressable by exact version. Being able to inspect
    # one before promoting it is the point of having it.
    inspected = await store.get(template_id, version=2)
    assert inspected is not None
    assert inspected.parameters == {"model": "opus"}

    # "And promotion creates a new explicit version only after the policy gate"
    audit = _RecordingAudit()
    await promote_audited(store, template_id, 2, audit=audit, approval=_approval())

    promoted = await store.get(template_id)
    assert promoted is not None
    assert promoted.version == 2
    assert await store.lifecycle_of(template_id, 2) == "active"
    assert audit.entries == [
        ("template_promotion_attempt", template_id, 2),
        ("template_promotion_committed", template_id, 2),
    ]


async def test_promotion_does_not_change_the_content_hash(store: Any, request: Any) -> None:
    """ADR-082926-65bf's load-bearing exclusion.

    Every object instantiated from a version while it was a candidate cites
    that version's `content_hash` in `source_template`. If `lifecycle` reached
    the hash, promoting would retroactively falsify their provenance -- an
    audit comparing against the stored hash would report tampering that never
    happened.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    candidate = await _improve(store, template_id, from_version=1)
    node = candidate.instantiate(node_id="node-1")

    await promote_audited(store, template_id, 2, audit=_RecordingAudit(), approval=_approval())

    promoted = await store.get(template_id, version=2)
    assert promoted is not None
    assert promoted.content_hash == candidate.content_hash
    assert node.source_template is not None
    assert node.source_template.template_hash == promoted.content_hash


async def test_a_promotion_whose_commit_cannot_be_recorded_is_undone(
    store: Any, request: Any
) -> None:
    """The guarantee `promote_audited` borrows from its genome counterpart.

    A version must never observably become active without a matching committed
    entry. The attempt entry is recorded first, so a sink that is down blocks
    the promotion outright; a sink that fails on the *commit* has already let
    the mutation happen, so the mutation is undone before the error escapes.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await _improve(store, template_id, from_version=1)

    audit = _RecordingAudit(fail_on="template_promotion_committed")
    with pytest.raises(RuntimeError, match="audit sink unavailable"):
        await promote_audited(store, template_id, 2, audit=audit, approval=_approval())

    assert await store.lifecycle_of(template_id, 2) == "candidate"
    current = await store.get(template_id)
    assert current is not None
    assert current.version == 1


async def test_a_sink_that_is_down_blocks_the_promotion_entirely(store: Any, request: Any) -> None:
    """Fail-closed: no attempt entry, no state change."""
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await _improve(store, template_id, from_version=1)

    audit = _RecordingAudit(fail_on="template_promotion_attempt")
    with pytest.raises(RuntimeError, match="audit sink unavailable"):
        await promote_audited(store, template_id, 2, audit=audit, approval=_approval())

    assert await store.lifecycle_of(template_id, 2) == "candidate"
    assert audit.entries == []


async def test_promoting_a_version_that_does_not_exist_says_so(store: Any, request: Any) -> None:
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))

    with pytest.raises(NodeTemplateNotFound):
        await promote_audited(store, template_id, 9, audit=_RecordingAudit(), approval=_approval())


async def test_a_template_whose_every_version_is_a_candidate_resolves_to_nothing(
    store: Any, request: Any
) -> None:
    """Not an oversight -- the alternative is worse.

    Falling back to a candidate when no active version exists would mean the
    first improvement to a never-published template silently becomes the
    published one, which is the failure this lifecycle exists to prevent. The
    caller that wants it can name its version.
    """
    template_id = _ids(request)
    await store.put(
        _template(template_id=template_id, version=1).model_copy(update={"lifecycle": "candidate"})
    )

    assert await store.get(template_id) is None
    assert await store.get(template_id, version=1) is not None
    assert await store.versions(template_id) == [1]


# ── the promotion gate's own failure modes (Codex, #589) ──────────


async def test_re_registering_a_candidate_does_not_activate_it(store: Any, request: Any) -> None:
    """The way a promotion could happen with no approval and no audit.

    The content hash excludes `lifecycle`, so a caller that rebuilds the same
    template without knowing about the field -- which is every caller written
    before it existed -- submits identical content carrying the default
    `"active"`. `put` sees a matching hash, treats it as idempotent, and used
    to write the whole payload through. The stored lifecycle must survive.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    candidate = await _improve(store, template_id, from_version=1)

    reconstructed = candidate.model_copy(update={"lifecycle": "active"})
    assert reconstructed.content_hash == candidate.content_hash
    await store.put(reconstructed)

    assert await store.lifecycle_of(template_id, 2) == "candidate"
    current = await store.get(template_id)
    assert current is not None
    assert current.version == 1


async def test_re_registering_an_active_version_does_not_demote_it(
    store: Any, request: Any
) -> None:
    """The same hole in the other direction."""
    template_id = _ids(request)
    original = _template(template_id=template_id, version=1)
    await store.put(original)

    await store.put(original.model_copy(update={"lifecycle": "candidate"}))

    assert await store.lifecycle_of(template_id, 1) == "active"
    assert await store.get(template_id) is not None


async def test_a_promotion_is_not_observable_until_its_commit_is_recorded(
    store: Any, request: Any
) -> None:
    """The claim the first version of this made and did not keep.

    The durable stores commit `set_lifecycle` before the audit sink is asked
    for the committed entry. Without a non-resolvable middle state, a
    concurrent reader could resolve and instantiate a version that the audit
    failure then rolls back. This asserts from the reader's side, at the
    moment the sink is being called.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await _improve(store, template_id, from_version=1)

    seen: list[Any] = []

    class _WatchingAudit:
        def __init__(self) -> None:
            self.entries: list[tuple[str, str, int]] = []

        async def record(self, event: str, tid: str, ver: int) -> None:
            if event == "template_promotion_committed":
                # What any other task would see right now.
                seen.append(await store.get(template_id))
                seen.append(await store.lifecycle_of(template_id, 2))
            self.entries.append((event, tid, ver))

    await promote_audited(store, template_id, 2, audit=_WatchingAudit(), approval=_approval())

    resolved, lifecycle = seen
    assert lifecycle == "promoting"
    assert resolved is not None
    assert resolved.version == 1, "a mid-promotion version must not be what callers get"

    # ...and it does become active once the entry is in.
    assert await store.lifecycle_of(template_id, 2) == "active"


async def test_a_cancelled_promotion_is_rolled_back(store: Any, request: Any) -> None:
    """`asyncio.CancelledError` inherits from BaseException.

    A task cancelled at a request timeout or a service shutdown would skip an
    `except Exception` rollback and leave the version mid-promotion.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await _improve(store, template_id, from_version=1)

    class _CancellingAudit:
        async def record(self, event: str, tid: str, ver: int) -> None:
            if event == "template_promotion_committed":
                raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await promote_audited(store, template_id, 2, audit=_CancellingAudit(), approval=_approval())

    assert await store.lifecycle_of(template_id, 2) == "candidate"


async def test_execution_refuses_a_candidate_even_when_its_version_is_named(
    store: Any, request: Any
) -> None:
    """A Schedule pinning `template_version` to a candidate must not run it.

    Exact-version access is the inspection door; `require_node_template` is
    the execution door and answers for what may run.
    """
    template_id = _ids(request)
    await store.put(_template(template_id=template_id, version=1))
    await _improve(store, template_id, from_version=1)

    with pytest.raises(NodeTemplateNotFound, match="is candidate, not active"):
        await require_node_template(store, template_id, version=2)

    # Inspection still works, through the store rather than the execution door.
    assert await store.get(template_id, version=2) is not None


async def test_a_candidate_only_template_is_not_reported_as_unregistered(
    store: Any, request: Any
) -> None:
    """ "Not registered" sent the admission path to diagnose the wrong thing.

    The template and its versions exist; what is missing is a promotion, and
    the message has to say so or the operator goes looking for a typo.
    """
    template_id = _ids(request)
    await store.put(
        _template(template_id=template_id, version=1).model_copy(update={"lifecycle": "candidate"})
    )

    with pytest.raises(NodeTemplateNotFound, match="has no active version"):
        await require_node_template(store, template_id)


async def test_an_approval_must_name_an_approver_and_a_reason(store: Any) -> None:
    """Fail-closed at construction, so there is no unowned approval to pass."""
    with pytest.raises(ValueError, match="approver"):
        PromotionApproval(approver="  ", reason="benchmarks cleared")
    with pytest.raises(ValueError, match="reason"):
        PromotionApproval(approver="release-owner", reason="")
