"""The agent factory's database-load branch must succeed.

Regression test for the defect where ``PgAgentRegistry.list_active()`` returned
dicts while the factory did attribute access (``record.soul`` /
``record.model``), raising ``AttributeError`` that was swallowed -- meaning the
DB-backed agent load could never succeed and always fell back to the filesystem.
"""

from __future__ import annotations

import maistro.agents.factory as factory_mod
from maistro.agents.factory import create_agents
from maistro.types.agent import AgentIdentity


class _FakeRegistry:
    def __init__(self, _engine: object) -> None:
        self._identities = [
            AgentIdentity(name="scribe", model="claude", tools=("write",)),
            AgentIdentity(name="ranger", model="auto", skills=("search",)),
        ]
        self._souls = {"scribe": "You are Scribe.", "ranger": "You are Ranger."}

    async def count(self) -> int:
        return len(self._identities)

    async def list_active(self) -> list[AgentIdentity]:
        return self._identities

    async def souls(self) -> dict[str, str]:
        return self._souls


class _RecordingPromptManager:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, str]] = []

    async def upsert(self, name: str, body: str, label: str = "") -> None:
        self.upserts.append((name, body))


async def test_db_load_branch_builds_agents(monkeypatch):
    # PgAgentRegistry is imported lazily inside create_agents, so patch it on
    # the source module.
    monkeypatch.setattr("maistro.persistence.pg_agents.PgAgentRegistry", _FakeRegistry)

    instantiated: list[AgentIdentity] = []

    def _fake_instantiate(identity: AgentIdentity, **_deps: object) -> object:
        instantiated.append(identity)
        return object()

    monkeypatch.setattr(factory_mod, "_instantiate", _fake_instantiate)

    prompt_manager = _RecordingPromptManager()

    agents = await create_agents(
        agents_dir="/nonexistent",
        prompt_manager=prompt_manager,
        llm=None,
        context_builder=None,
        warden=None,
        sentinel=None,
        learning_store=None,
        learning_extractor=None,
        outcome_store=None,
        session_store=None,
        quota_tracker=None,
        tracer=None,
        sa_engine=object(),  # truthy -> takes the DB branch
    )

    # Both DB agents were loaded (no silent filesystem fallback).
    assert set(agents) == {"scribe", "ranger"}
    assert {i.name for i in instantiated} == {"scribe", "ranger"}

    # Each agent's soul was seeded into the prompt manager from the DB.
    seeded = dict(prompt_manager.upserts)
    assert seeded["agent.scribe.soul"] == "You are Scribe."
    assert seeded["agent.ranger.soul"] == "You are Ranger."
