"""CONNECT proof: agent factory roots maistro.prompts.diff (ADR-060-shaped)."""

from __future__ import annotations

from maistro.agents.factory import _upsert_agent_soul
from maistro.prompts.diff import DiffLine
from maistro.prompts.store import InMemoryPromptManager


class TestPromptsDiffConnect:
    async def test_first_upsert_has_no_diff(self) -> None:
        prompts = InMemoryPromptManager()
        diff = await _upsert_agent_soul(prompts, "agent.demo.soul", "hello\n")
        assert diff is None
        assert await prompts.get("agent.demo.soul") == "hello\n"

    async def test_changed_soul_records_structured_diff(self) -> None:
        prompts = InMemoryPromptManager()
        await _upsert_agent_soul(prompts, "agent.demo.soul", "alpha\n")
        diff = await _upsert_agent_soul(prompts, "agent.demo.soul", "beta\n")
        assert diff is not None
        assert all(isinstance(line, DiffLine) for line in diff)
        assert any(line.op == "remove" and "alpha" in line.content for line in diff)
        assert any(line.op == "add" and "beta" in line.content for line in diff)
        assert await prompts.get("agent.demo.soul") == "beta\n"

    async def test_identical_soul_skips_diff(self) -> None:
        prompts = InMemoryPromptManager()
        await _upsert_agent_soul(prompts, "agent.demo.soul", "same\n")
        diff = await _upsert_agent_soul(prompts, "agent.demo.soul", "same\n")
        assert diff is None
