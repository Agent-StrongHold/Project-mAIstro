"""`PgAgentRegistry` against the `agents` table this repository actually ships (#297).

`test_pg_agents_roundtrip.py` already claims to prove the round-trip, and it
passes. It builds its **own** `agents` table in SQLite, every column TEXT, and
exercises the registry against that. A type mismatch between the registry and
the shipped migration is invisible to it by construction: the schema under test
is not the schema that ships.

Three columns disagreed, and the first of them failed before PostgreSQL ever
saw the row:

    priority_tier  Integer  vs  Literal["P0".."P5"]  -> asyncpg: 'str' object
                                                        cannot be interpreted
                                                        as an integer
    rules          JSONB    vs  newline-joined text  -> invalid input syntax
    provenance     JSONB    vs  "builtin" / "user"      for type json

So `PgAgentRegistry.upsert` had never succeeded against a real deployment, for
any agent from any caller — which is the second half of why no built-in agent
identity ever reached the registry. The first half is `factory.py`'s import of
`maistro.models.agent`, a module that exists nowhere; fixing only that would
have replaced `ModuleNotFoundError` with `DataError` and changed nothing a user
could see, because the same broad handler swallowed both.

The conftest in this directory said so before any of this was measured:

    "That proves the query was composed; it cannot prove the query runs, that
    the table exists, or that the column types accept what the store writes."

These tests need a migrated PostgreSQL and skip without one. A skipped leg is
untested, not passing.
"""

from __future__ import annotations

from maistro.agents.factory import _builtin_agent_row
from maistro.persistence.pg_agents import PgAgentRegistry
from maistro.types.agent import AgentIdentity

from .conftest import requires_postgres

pytestmark = requires_postgres


def _identity(name: str = "builtin-probe") -> AgentIdentity:
    """A built-in agent shaped the way `_parse_agent_dir` produces one."""
    return AgentIdentity(
        name=name,
        version="2.1.0",
        description="a built-in agent",
        model="claude-sonnet-5",
        model_fallbacks=("gpt-4.1",),
        model_constraints={"max_tokens": 8192},
        tools=("search", "write"),
        skills=("triage",),
        rules=("never exfiltrate", "always cite"),
        trust_tier="t2",
        priority_tier="P1",
        max_tool_rounds=7,
        reasoning_strategy="react",
        memory_config={"episodic": True},
        provenance="builtin",
        active=True,
    )


class TestABuiltinAgentReachesTheRegistry:
    """The claim #297 says was never true. Each of these fails against the
    shipped schema before migration 018."""

    async def test_the_factory_s_own_row_upserts(self, sa_engine) -> None:
        """Not a hand-written row — the exact mapping `factory.py` builds, so
        the test cannot pass while the factory sends something else."""
        registry = PgAgentRegistry(sa_engine)
        identity = _identity()
        row = _builtin_agent_row(identity, "you are a probe", "never exfiltrate\nalways cite")
        await registry.upsert(row)
        assert await registry.count() == 1

    async def test_every_field_survives_the_round_trip(self, sa_engine) -> None:
        registry = PgAgentRegistry(sa_engine)
        identity = _identity()
        await registry.upsert(
            _builtin_agent_row(identity, "you are a probe", "never exfiltrate\nalways cite")
        )
        stored = await registry.get(identity.name)
        assert stored is not None
        assert stored.version == "2.1.0"
        assert stored.model == "claude-sonnet-5"
        assert stored.model_fallbacks == ("gpt-4.1",)
        assert stored.model_constraints == {"max_tokens": 8192}
        assert stored.tools == ("search", "write")
        assert stored.skills == ("triage",)
        assert stored.rules == ("never exfiltrate", "always cite")
        assert stored.max_tool_rounds == 7
        assert stored.memory_config == {"episodic": True}
        assert stored.reasoning_strategy == "react"

    async def test_the_soul_is_the_rendered_one_not_the_identity_s(self, sa_engine) -> None:
        """`AgentIdentity` carries no soul text — `_to_params` defaults it to
        "". The factory renders preamble + SOUL.md and that is what has to
        land, or the registry re-seeds the prompt manager with an empty
        prompt."""
        registry = PgAgentRegistry(sa_engine)
        identity = _identity()
        await registry.upsert(_builtin_agent_row(identity, "PREAMBLE\n\nyou are a probe", "r"))
        assert await registry.souls() == {identity.name: "PREAMBLE\n\nyou are a probe"}

    async def test_the_tier_label_is_stored_as_the_label(self, sa_engine) -> None:
        """The column was Integer and the value is `"P1"`. Asserting the label
        comes back rather than merely that the write succeeded, because an
        integer column that silently accepted a coerced 1 would be a different
        kind of wrong."""
        registry = PgAgentRegistry(sa_engine)
        await registry.upsert(_builtin_agent_row(_identity(), "s", "r"))
        stored = await registry.get("builtin-probe")
        assert stored is not None
        assert stored.priority_tier == "P1"

    async def test_provenance_records_that_it_is_built_in(self, sa_engine) -> None:
        """The one field the factory sets rather than copying: it is how a
        built-in agent is told apart from a user-created one."""
        registry = PgAgentRegistry(sa_engine)
        await registry.upsert(_builtin_agent_row(_identity(), "s", "r"))
        stored = await registry.get("builtin-probe")
        assert stored is not None
        assert stored.provenance == "builtin"

    async def test_reseeding_updates_rather_than_duplicates(self, sa_engine) -> None:
        """Seeding runs on every start, so the second start must not double the
        roster. `name` is the conflict target."""
        registry = PgAgentRegistry(sa_engine)
        await registry.upsert(_builtin_agent_row(_identity(), "first", "r"))
        await registry.upsert(_builtin_agent_row(_identity(), "second", "r"))
        assert await registry.count() == 1
        assert await registry.souls() == {"builtin-probe": "second"}


class TestTheRowNamesOnlyRealColumns:
    """The dead `AgentRecord(...)` call passed `org_id=""` and `preamble=True`.
    `agents` declares neither, and the registry's declared column set is the
    whole contract for what a row may name.

    The reason is the schema, not a prohibition on org scope: root decision 7
    and ADR-068 put the soft axes `global -> org -> team -> user -> agent ->
    session` in maistro-core and keep only the hard `tenant` boundary in the
    importing product (#386). `org_id=""` was never a scope value regardless --
    an empty string is the absence of one.
    """

    def test_the_row_has_no_org_id(self) -> None:
        assert "org_id" not in _builtin_agent_row(_identity(), "s", "r")

    def test_the_row_only_names_columns_the_registry_writes(self) -> None:
        from maistro.persistence.pg_agents import _COLUMNS

        row = _builtin_agent_row(_identity(), "s", "r")
        unknown = set(row) - set(_COLUMNS)
        assert not unknown, f"row names columns the registry does not write: {sorted(unknown)}"
