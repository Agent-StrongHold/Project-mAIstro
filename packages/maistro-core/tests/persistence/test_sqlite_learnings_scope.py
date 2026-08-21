"""Scope filtering on the SQLite learning store (review finding H8).

`find_relevant` accepted `org_id` and never used it — the query was
`SELECT * FROM learnings WHERE status = 'active'` — and the table had no
`org_id` column at all, even though `Learning.org_id` and every store method's
signature had carried one for a long time.

That matters more than an ordinary unfiltered read: `find_relevant`'s results
are interpolated into the agent's **system prompt** by `ContextBuilder`, so a
learning is an instruction, not a datum.

ADR-068:82 makes `org` a soft scope axis inside maistro-core (amending the older
"no org_id in core" shorthand, per ADR-068:275), so this completes an axis the
codebase already declared rather than introducing tenancy into core.
"""

from __future__ import annotations

import aiosqlite
import pytest

from maistro.persistence.sqlite_learnings import SqliteLearningStore
from maistro.types.memory import Learning


@pytest.fixture
async def store():
    conn = await aiosqlite.connect(":memory:")
    st = SqliteLearningStore(conn)
    await st.ensure_schema()
    yield st
    await conn.close()


def _learning(**kw) -> Learning:
    base = {
        "learning": "always run the tests",
        "trigger_keys": ["deploy"],
        "tool_name": "bash",
        "category": "general",
    }
    base.update(kw)
    return Learning(**base)


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_find_relevant_does_not_return_another_orgs_learning(store) -> None:
    """The core of H8. Fails without the fix: org-b's row came back to org-a.

    The two learnings deliberately use different `tool_name`s. With the same
    tool and overlapping trigger keys, the *unfixed* dedup path merges the
    second store into the first, so org-b's row never exists and the assertion
    below passes for the wrong reason — the test would report green against the
    very code it is meant to catch. Distinct tools keep both rows real, so the
    only thing that can keep them apart is the scope filter.
    """
    await store.store(
        _learning(learning="org-a secret procedure", org_id="org-a", tool_name="bash")
    )
    await store.store(
        _learning(learning="org-b secret procedure", org_id="org-b", tool_name="python")
    )

    found = await store.find_relevant("deploy now", org_id="org-a")

    texts = [lr.learning for lr in found]
    assert "org-a secret procedure" in texts
    assert "org-b secret procedure" not in texts, (
        "a learning from another org reached this caller — and would have been "
        "interpolated into its system prompt"
    )


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_unowned_learnings_are_not_readable_by_an_org(store) -> None:
    """There is no global bucket — `org_id = ''` is a scope, not a wildcard.

    This assertion is the inverse of the one this test carried when the H8 fix
    first landed, and the reversal is deliberate. The original predicate was
    `(org_id = ? OR org_id = '')`, admitting every unowned row to every caller
    by analogy with the `agent_id = ''` convention. The analogy does not hold:
    `agent_id = ''` widens *within* one org, while `org_id = ''` crosses the
    tenancy boundary that SPEC-216 lists as a non-goal ("cross-org learning
    sharing of any kind").

    It was reachable, not theoretical. `BaseAgent._extract_rca` populated
    `org_id` only on its traced branch, so with tracing disabled every RCA was
    stored unowned — and an RCA derived from one org's tool failures then
    landed in every other org's system prompt.

    Single-tenant deployments are unaffected: they store `""` and read `""`,
    which still matches exactly.
    """
    await store.store(_learning(learning="unowned procedure", org_id=""))

    for who in ("org-a", "org-b"):
        texts = [lr.learning for lr in await store.find_relevant("deploy", org_id=who)]
        assert "unowned procedure" not in texts, (
            f"an unowned learning reached {who!r} and would have been "
            "interpolated into its system prompt"
        )

    own = [lr.learning for lr in await store.find_relevant("deploy", org_id="")]
    assert "unowned procedure" in own, "the unscoped caller must still see its own rows"


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_omitting_org_id_does_not_match_everything(store) -> None:
    """The filter must fail closed.

    A caller that omits `org_id` gets global scope, not a wildcard. Reading the
    default as "match all" would have made every unscoped call — which is most
    of them today — a cross-org read.
    """
    await store.store(_learning(learning="org-a secret", org_id="org-a"))

    texts = [lr.learning for lr in await store.find_relevant("deploy")]

    assert "org-a secret" not in texts


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_store_dedup_does_not_cross_orgs(store) -> None:
    """Dedup probed by tool_name alone, so it matched across scopes.

    A store for org-b would find org-a's row, bump *its* hit_count and return
    org-a's id — a cross-scope write and an id disclosure, not just a lost
    insert.
    """
    # Same tool AND overlapping keys — the exact shape that deduped across
    # scopes before the fix.
    id_a = await store.store(_learning(learning="a's version", org_id="org-a"))
    id_b = await store.store(_learning(learning="b's version", org_id="org-b"))

    assert id_a != id_b, "org-b's store deduped against org-a's row"

    a_rows = await store.list_all(org_id="org-a")
    assert [lr.learning for lr in a_rows] == ["a's version"]


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_list_all_is_scoped(store) -> None:
    await store.store(_learning(learning="a", org_id="org-a"))
    await store.store(_learning(learning="b", org_id="org-b"))

    assert [lr.learning for lr in await store.list_all(org_id="org-b")] == ["b"]


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_mark_outcome_cannot_write_across_scopes(store) -> None:
    """Ids are integers and guessable; the write path needs the filter too."""
    id_a = await store.store(_learning(learning="a", org_id="org-a"))

    await store.mark_outcome([id_a], success=True, org_id="org-b")

    (row,) = await store.list_all(org_id="org-a")
    assert row.success_after_use == 0, "org-b moved a counter on org-a's learning"

    await store.mark_outcome([id_a], success=True, org_id="org-a")
    (row,) = await store.list_all(org_id="org-a")
    assert row.success_after_use == 1, "the legitimate owner must still be able to write"


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_promotion_is_scoped(store) -> None:
    await store.store(_learning(learning="a", org_id="org-a"))
    await store.store(_learning(learning="b", org_id="org-b"))
    await store.mark_used([1, 2])
    for _ in range(6):
        await store.mark_used([1, 2])

    promoted = await store.check_auto_promotions(threshold=5, org_id="org-a")

    assert [lr.learning for lr in promoted] == ["a"]
    assert [lr.learning for lr in await store.get_promoted(org_id="org-b")] == []


@pytest.mark.contract("scope-isolation")
@pytest.mark.scope("unit")
async def test_ensure_schema_upgrades_a_pre_org_id_database() -> None:
    """A database written by the previous version must keep working.

    `org_id` is a new column on an existing table, so the store has to add it
    rather than assume `CREATE TABLE IF NOT EXISTS` will. Without the ALTER,
    every query naming `org_id` raises OperationalError against an old file and
    the store is simply broken after upgrade.
    """
    conn = await aiosqlite.connect(":memory:")
    try:
        # The pre-fix schema, verbatim in the parts that matter.
        await conn.execute(
            "CREATE TABLE learnings ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT 'general',"
            "trigger_keys TEXT NOT NULL DEFAULT '[]', learning TEXT NOT NULL DEFAULT '',"
            "tool_name TEXT NOT NULL DEFAULT '', agent_id TEXT NOT NULL DEFAULT '',"
            "user_id TEXT, scope TEXT NOT NULL DEFAULT 'agent',"
            "hit_count INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',"
            "rca_category TEXT, rca_prevention TEXT NOT NULL DEFAULT '',"
            "success_after_use INTEGER NOT NULL DEFAULT 0,"
            "failure_after_use INTEGER NOT NULL DEFAULT 0)"
        )
        await conn.execute(
            "INSERT INTO learnings (learning, trigger_keys, tool_name) "
            "VALUES ('legacy row', '[\"deploy\"]', 'bash')"
        )
        await conn.commit()

        store = SqliteLearningStore(conn)
        await store.ensure_schema()

        # The pre-existing row must survive the migration and stay readable by
        # the scope it actually belongs to. A row written before `org_id`
        # existed carries no provenance, so it backfills to `""` — which means
        # a single-tenant deployment (the only kind that can have written it)
        # keeps reading it exactly as before.
        texts = [lr.learning for lr in await store.find_relevant("deploy", org_id="")]
        assert "legacy row" in texts

        # It must NOT become readable by an org. Unknown provenance is the
        # reason to withhold it, not a reason to publish it to everyone.
        scoped = [lr.learning for lr in await store.find_relevant("deploy", org_id="org-a")]
        assert "legacy row" not in scoped

        # And ensure_schema must be safe to run again.
        await store.ensure_schema()
    finally:
        await conn.close()
