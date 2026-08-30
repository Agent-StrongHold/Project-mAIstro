"""The scope rule means the same thing in Python and in SQL (#710).

`matches_scope` is not a set of equalities. A `global` memory carrying an
`org_id` is visible only to that org, and a `team` match additionally requires
the caller's org — two clauses whose whole job is to stop cross-org reads. A
durable store that re-typed them in SQL would be a second spelling of a
visibility rule, so `scope_predicate` is compiled from the same filter list and
these tests drive both over one corpus.

The predicate is executed, not inspected: a test that asserted on the SQL string
would pass for a predicate no database accepts, and #328 is the record of what
that costs. SQLite is the engine here because it is enough to *run* the
expression; the PostgreSQL side is exercised against a real server in
`tests/persistence/test_episodic_store_conformance.py`.
"""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator
from typing import Any

import pytest

from maistro.memory.scopes import build_scope_filter, matches_scope, scope_predicate
from maistro.types.memory import EpisodicMemory, MemoryScope

pytest.importorskip("aiosqlite")
import aiosqlite

pytestmark = [pytest.mark.contract("behavioral")]


def _memory(memory_id: str, **fields: Any) -> EpisodicMemory:
    return EpisodicMemory(memory_id=memory_id, content=memory_id, **fields)


#: One memory per (scope, ownership) combination that the rule distinguishes,
#: including the two the cross-org clauses exist for.
CORPUS: list[EpisodicMemory] = [
    _memory("global-unowned", scope=MemoryScope.GLOBAL),
    _memory("global-org-a", scope=MemoryScope.GLOBAL, org_id="org-a"),
    _memory("global-org-b", scope=MemoryScope.GLOBAL, org_id="org-b"),
    _memory("org-a", scope=MemoryScope.ORGANIZATION, org_id="org-a"),
    _memory("org-b", scope=MemoryScope.ORGANIZATION, org_id="org-b"),
    _memory("team-a", scope=MemoryScope.TEAM, org_id="org-a", team_id="team-1"),
    _memory("team-b", scope=MemoryScope.TEAM, org_id="org-b", team_id="team-1"),
    _memory("team-other", scope=MemoryScope.TEAM, org_id="org-a", team_id="team-2"),
    _memory("user-1", scope=MemoryScope.USER, org_id="org-a", user_id="u1"),
    _memory("user-2", scope=MemoryScope.USER, org_id="org-a", user_id="u2"),
    _memory("agent-1", scope=MemoryScope.AGENT, org_id="org-a", agent_id="a1"),
    _memory("agent-2", scope=MemoryScope.AGENT, org_id="org-a", agent_id="a2"),
    _memory("session-1", scope=MemoryScope.SESSION, org_id="org-a"),
]

#: Callers whose visible sets the two spellings must agree on. Includes the
#: unscoped caller, whose filter list is the global scope alone.
CALLERS: list[dict[str, str]] = [
    {},
    {"org_id": "org-a"},
    {"org_id": "org-b"},
    {"org_id": "org-a", "team_id": "team-1"},
    {"team_id": "team-1"},
    {"org_id": "org-a", "user_id": "u1"},
    {"org_id": "org-a", "agent_id": "a1"},
    {"org_id": "org-a", "team_id": "team-1", "user_id": "u1", "agent_id": "a1"},
]


@pytest.fixture
async def corpus_db() -> AsyncIterator[Any]:
    """A SQLite table holding `CORPUS`, with the columns the predicate names."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute(
        "CREATE TABLE episodic_memories ("
        " memory_id TEXT, scope TEXT, org_id TEXT, team_id TEXT,"
        " user_id TEXT, agent_id TEXT)"
    )
    await conn.executemany(
        "INSERT INTO episodic_memories VALUES (?, ?, ?, ?, ?, ?)",
        [(m.memory_id, str(m.scope), m.org_id, m.team_id, m.user_id, m.agent_id) for m in CORPUS],
    )
    await conn.commit()
    try:
        yield conn
    finally:
        await conn.close()


async def _sql_visible(conn: Any, caller: dict[str, str]) -> set[str]:
    predicate, params = scope_predicate(build_scope_filter(**caller), itertools.repeat("?"))
    cursor = await conn.execute(
        f"SELECT memory_id FROM episodic_memories WHERE {predicate}", tuple(params)
    )
    return {row[0] for row in await cursor.fetchall()}


def _python_visible(caller: dict[str, str]) -> set[str]:
    filters = build_scope_filter(**caller)
    return {m.memory_id for m in CORPUS if matches_scope(m, filters)}


class TestBothSpellingsAgree:
    @pytest.mark.ac("SPEC-083026-ba26/AC-3")
    @pytest.mark.parametrize("caller", CALLERS, ids=lambda c: "+".join(sorted(c)) or "unscoped")
    async def test_the_same_memories_are_visible(
        self, corpus_db: Any, caller: dict[str, str]
    ) -> None:
        assert await _sql_visible(corpus_db, caller) == _python_visible(caller)

    @pytest.mark.ac("SPEC-083026-ba26/AC-3")
    async def test_a_global_memory_of_another_org_is_refused_by_both(self, corpus_db: Any) -> None:
        """The first cross-org clause. Without it a global memory written under
        one org is readable by every other, which is the leak the rule exists
        for — and the clause a SQL rewrite is most likely to drop."""
        caller = {"org_id": "org-a"}
        assert "global-org-b" not in _python_visible(caller)
        assert "global-org-b" not in await _sql_visible(corpus_db, caller)
        assert "global-org-a" in _python_visible(caller)
        assert "global-org-a" in await _sql_visible(corpus_db, caller)

    @pytest.mark.ac("SPEC-083026-ba26/AC-3")
    async def test_a_team_in_another_org_is_refused_by_both(self, corpus_db: Any) -> None:
        """The second: team ids are not globally unique, so `team-1` names a
        different team in each org and matching on it alone crosses orgs."""
        caller = {"org_id": "org-a", "team_id": "team-1"}
        assert "team-b" not in _python_visible(caller)
        assert "team-b" not in await _sql_visible(corpus_db, caller)
        assert "team-a" in await _sql_visible(corpus_db, caller)

    async def test_a_team_caller_with_no_org_sees_no_team_memory(self, corpus_db: Any) -> None:
        """`matches_scope` requires `mem.org_id == caller_org`, and an absent
        caller org is `''`, which no stored team memory carries. Both spellings
        must reach that same nothing rather than one of them treating the
        missing org as a wildcard."""
        caller = {"team_id": "team-1"}
        assert not {m for m in _python_visible(caller) if m.startswith("team")}
        assert not {m for m in await _sql_visible(corpus_db, caller) if m.startswith("team")}

    async def test_a_scope_neither_spelling_can_express_is_visible_to_neither(
        self, corpus_db: Any
    ) -> None:
        """`session` has no branch in `matches_scope`, so it matches nothing.
        The predicate must contribute no clause for it rather than raise — a
        store whose read crashes on a row it cannot classify is worse than one
        that does not return it."""
        for caller in CALLERS:
            assert "session-1" not in _python_visible(caller)
            assert "session-1" not in await _sql_visible(corpus_db, caller)


class TestThePredicateIsParameterised:
    async def test_no_caller_value_reaches_the_sql_text(self) -> None:
        """Every value is bound, so a scope id is data and never statement text."""
        predicate, params = scope_predicate(
            build_scope_filter(org_id="o'; DROP TABLE episodic_memories; --", agent_id="a1"),
            itertools.repeat("?"),
        )
        assert "DROP TABLE" not in predicate
        assert "o'; DROP TABLE episodic_memories; --" in params

    async def test_a_bound_value_is_matched_literally(self, corpus_db: Any) -> None:
        """And the binding is real: a value that would be SQL if interpolated
        selects nothing rather than executing."""
        assert await _sql_visible(corpus_db, {"org_id": "org-a' OR '1'='1"}) == {"global-unowned"}

    async def test_the_placeholders_are_drawn_in_parameter_order(self) -> None:
        """The numeric markers asyncpg needs are positional, so a predicate that
        drew them out of step with `params` would bind the org id to the team
        clause. Asserted on the compiled text because the mismatch is invisible
        in SQLite, where every marker is `?`."""
        predicate, params = scope_predicate(
            build_scope_filter(org_id="org-a", team_id="team-1"),
            (f"${index}" for index in itertools.count(1)),
        )
        assert params == ["org-a", "org-a", "team-1", "org-a"]
        assert "team_id = $3 AND org_id = $4" in predicate
