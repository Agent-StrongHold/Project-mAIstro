"""Gap-filling coverage for PgAgentRegistry/module helpers not exercised by
test_pg_agents_roundtrip.py: count(), _as_iterable's str/Sequence branches,
_to_params's AgentIdentity-record and list/tuple-rules branches, and
_decode_json's passthrough/empty/malformed-JSON branches."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from maistro.persistence.pg_agents import (
    PgAgentRegistry,
    _as_iterable,
    _decode_json,
    _to_params,
)
from maistro.types.agent import AgentIdentity

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
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.execute(text(_CREATE_AGENTS_TABLE))
    yield eng
    await eng.dispose()


@pytest.fixture
def registry(engine):
    return PgAgentRegistry(engine)


class TestCount:
    async def test_count_zero_when_empty(self, registry) -> None:
        assert await registry.count() == 0

    async def test_count_excludes_inactive(self, registry) -> None:
        await registry.upsert({"name": "live", "active": True})
        await registry.upsert({"name": "dead", "active": True})
        await registry.delete("dead")

        assert await registry.count() == 1


class TestAsIterable:
    def test_none_returns_empty_list(self) -> None:
        assert _as_iterable(None) == []

    def test_str_wraps_as_single_element_list(self) -> None:
        # A bare string must not be exploded into characters.
        assert _as_iterable("solo") == ["solo"]

    def test_sequence_converts_to_list(self) -> None:
        assert _as_iterable(("a", "b")) == ["a", "b"]

    def test_non_sequence_scalar_wraps_in_list(self) -> None:
        assert _as_iterable(42) == [42]


class TestToParamsAgentIdentity:
    def test_agent_identity_record_builds_params(self) -> None:
        identity = AgentIdentity(
            name="scout",
            version="1.2.0",
            description="finder",
            soul_prompt_name="agent.scout.soul",
            model="claude",
            model_fallbacks=("gpt",),
            model_constraints={"max_tokens": 100},
            tools=("search",),
            skills=("recon",),
            rules=("rule a", "rule b"),
            trust_tier="t3",
            priority_tier="P1",
            max_tool_rounds=5,
            reasoning_strategy="react",
            memory_config={"recall": 3},
            provenance="system",
            active=True,
        )

        params = _to_params(identity)

        assert params["name"] == "scout"
        assert params["version"] == "1.2.0"
        assert params["model"] == "claude"
        assert params["rules"] == "rule a\nrule b"
        assert params["trust_tier"] == "t3"
        assert params["max_tool_rounds"] == 5
        assert params["provenance"] == "system"
        assert params["active"] is True

    def test_mapping_record_with_list_rules_joins_with_newline(self) -> None:
        params = _to_params({"name": "joined", "rules": ["one", "two", "three"]})
        assert params["rules"] == "one\ntwo\nthree"

    def test_mapping_record_with_tuple_rules_joins_with_newline(self) -> None:
        params = _to_params({"name": "tupled", "rules": ("a", "b")})
        assert params["rules"] == "a\nb"


class TestDecodeJson:
    def test_none_returns_default(self) -> None:
        assert _decode_json(None, []) == []

    def test_native_list_passes_through_unchanged(self) -> None:
        value = ["already", "a", "list"]
        assert _decode_json(value, []) is value

    def test_native_dict_passes_through_unchanged(self) -> None:
        value = {"already": "a dict"}
        assert _decode_json(value, {}) is value

    def test_empty_string_returns_default(self) -> None:
        assert _decode_json("", {"fallback": True}) == {"fallback": True}

    def test_valid_json_string_decodes(self) -> None:
        assert _decode_json('["a", "b"]', []) == ["a", "b"]

    def test_malformed_json_string_returns_default(self) -> None:
        assert _decode_json("{not valid json", ["default"]) == ["default"]

    def test_unexpected_type_returns_default(self) -> None:
        assert _decode_json(42, ["default"]) == ["default"]
