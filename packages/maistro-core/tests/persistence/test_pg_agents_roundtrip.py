"""Round-trip tests for PgAgentRegistry.

These pin the contract that:

* ``list_active()`` / ``get()`` return ``AgentIdentity`` objects (matching the
  annotation and the agent factory's expectations), not raw dicts.
* ``upsert`` persists the full set of fields it later reads back, so an agent
  round-trips through the database without losing tools / skills / config /
  model / rules / soul / etc.

A real PostgreSQL instance is not available in CI, so the tests run against an
in-memory SQLite async engine that mirrors the ``agents`` table the production
code reads and writes.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("aiosqlite")

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from maistro.persistence.pg_agents import PgAgentRegistry
from maistro.types.agent import AgentIdentity

# Columns PgAgentRegistry reads in _coerce_row and writes in upsert. SQLite has
# no JSONB/array types, so the list/dict columns are TEXT and the production
# code is responsible for (de)serializing them as JSON.
_CREATE_AGENTS_TABLE = """
CREATE TABLE agents (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT '1.0.0',
    description TEXT NOT NULL DEFAULT '',
    soul TEXT NOT NULL DEFAULT '',
    rules TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT 'auto',
    model_fallbacks TEXT,
    model_constraints TEXT,
    tools TEXT,
    skills TEXT,
    trust_tier TEXT NOT NULL DEFAULT 't4',
    priority_tier TEXT NOT NULL DEFAULT 'P2',
    max_tool_rounds INTEGER NOT NULL DEFAULT 3,
    reasoning_strategy TEXT NOT NULL DEFAULT 'direct',
    memory_config TEXT,
    provenance TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT,
    updated_at TEXT
)
"""


@pytest.fixture
def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")

    async def initialize() -> None:
        async with eng.begin() as conn:
            await conn.execute(text(_CREATE_AGENTS_TABLE))

    asyncio.run(initialize())
    yield eng
    asyncio.run(eng.dispose())


@pytest.fixture
def registry(engine):
    return PgAgentRegistry(engine)


async def _count_rows(engine) -> int:
    async with AsyncSession(engine) as session:
        result = await session.execute(text("SELECT COUNT(*) FROM agents"))
        row = result.first()
        return int(row[0]) if row else 0


async def test_list_active_returns_agent_identity(registry):
    """list_active must yield AgentIdentity objects, not dicts."""
    await registry.upsert(
        {
            "name": "scribe",
            "version": "2.1.0",
            "description": "writer",
            "model": "claude",
            "tools": ["search", "write"],
            "skills": ["prose"],
            "model_fallbacks": ["gpt"],
            "model_constraints": {"max_tokens": 4096},
            "memory_config": {"recall": 5},
            "rules": "be terse\nbe kind",
            "trust_tier": "t2",
            "priority_tier": "P1",
            "max_tool_rounds": 7,
            "reasoning_strategy": "react",
            "active": True,
        }
    )

    agents = await registry.list_active()

    assert len(agents) == 1
    agent = agents[0]
    assert isinstance(agent, AgentIdentity)
    assert agent.name == "scribe"


async def test_full_field_roundtrip(registry):
    """Every meaningful field must survive a write then read."""
    await registry.upsert(
        {
            "name": "artificer",
            "version": "3.0.0",
            "description": "the maker",
            "model": "claude-opus",
            "tools": ["bash", "edit", "read"],
            "skills": ["code", "review"],
            "model_fallbacks": ["sonnet", "haiku"],
            "model_constraints": {"temperature": 0.2, "max_tokens": 8000},
            "memory_config": {"recall": 12, "decay": True},
            "rules": "rule one\nrule two\nrule three",
            "trust_tier": "t1",
            "priority_tier": "P0",
            "max_tool_rounds": 9,
            "reasoning_strategy": "plan_execute",
            "active": True,
        }
    )

    agent = await registry.get("artificer")

    assert isinstance(agent, AgentIdentity)
    assert agent.name == "artificer"
    assert agent.version == "3.0.0"
    assert agent.description == "the maker"
    assert agent.model == "claude-opus"
    assert agent.tools == ("bash", "edit", "read")
    assert agent.skills == ("code", "review")
    assert agent.model_fallbacks == ("sonnet", "haiku")
    assert agent.model_constraints == {"temperature": 0.2, "max_tokens": 8000}
    assert agent.memory_config == {"recall": 12, "decay": True}
    assert agent.rules == ("rule one", "rule two", "rule three")
    assert agent.trust_tier == "t1"
    assert agent.priority_tier == "P0"
    assert agent.max_tool_rounds == 9
    assert agent.reasoning_strategy == "plan_execute"


async def test_upsert_updates_existing_without_duplicating(registry, engine):
    """A second upsert of the same name updates in place (no duplicate row)."""
    await registry.upsert({"name": "ranger", "description": "first", "tools": ["a"]})
    await registry.upsert({"name": "ranger", "description": "second", "tools": ["a", "b", "c"]})

    assert await _count_rows(engine) == 1
    agent = await registry.get("ranger")
    assert agent is not None
    assert agent.description == "second"
    assert agent.tools == ("a", "b", "c")


async def test_empty_collection_fields_default_safely(registry):
    """Missing/NULL list & dict columns coerce to empty, not None."""
    await registry.upsert({"name": "bare"})

    agent = await registry.get("bare")

    assert isinstance(agent, AgentIdentity)
    assert agent.tools == ()
    assert agent.skills == ()
    assert agent.model_fallbacks == ()
    assert agent.model_constraints == {}
    assert agent.memory_config == {}
    assert agent.rules == ()


async def test_list_active_excludes_inactive(registry):
    await registry.upsert({"name": "live", "active": True})
    await registry.upsert({"name": "dead", "active": True})
    await registry.delete("dead")

    names = {a.name for a in await registry.list_active()}
    assert names == {"live"}


async def test_get_missing_returns_none(registry):
    assert await registry.get("nope") is None


async def test_souls_returns_soul_text_by_name(registry):
    """souls() exposes the stored soul prompt separately from AgentIdentity."""
    await registry.upsert({"name": "scribe", "soul": "You are Scribe.", "active": True})
    await registry.upsert({"name": "ranger", "soul": "You are Ranger.", "active": True})
    await registry.upsert({"name": "ghost", "soul": "hidden", "active": True})
    await registry.delete("ghost")

    souls = await registry.souls()

    assert souls == {"scribe": "You are Scribe.", "ranger": "You are Ranger."}
