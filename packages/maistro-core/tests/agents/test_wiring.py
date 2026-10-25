"""Agent runtime CONNECT wiring (#2312)."""

from __future__ import annotations

import pytest

from maistro.agents.wiring import (
    get_agent_runtime_extensions,
    wire_agent_implementations,
)


class _CallShapedLLM:
    async def call(
        self,
        system: str,
        user: str,
        *,
        model: str,
        temperature: float,
        max_tokens: int,
        tier: int,
        lane: str,
    ) -> dict[str, object]:
        return {"content": "ok", "model": model}


class _CompleteOnlyLLM:
    async def complete(self, *args: object, **kwargs: object) -> dict[str, object]:
        return {"content": "ok"}


def test_wire_agent_implementations_uses_null_adapter_for_complete_shaped_llm() -> None:
    ext = wire_agent_implementations({}, llm=_CompleteOnlyLLM())
    assert ext.spawner is not None
    assert get_agent_runtime_extensions() is ext
    assert "Spawner" in str(ext.inventory()["spawner"])


def test_wire_agent_implementations_keeps_call_shaped_llm() -> None:
    llm = _CallShapedLLM()
    ext = wire_agent_implementations({}, llm=llm)
    # Spawner holds the same caller when ``call`` is present (line 88 true branch).
    assert ext.spawner._llm is llm


@pytest.mark.asyncio
async def test_wire_agent_implementations_without_llm_still_builds_spawner() -> None:
    ext = wire_agent_implementations({})
    assert ext.tournament is not None
    assert ext.http_tool_executor is not None
    assert ext.auditor_check_names
    out = await ext.spawner._llm.call(
        "sys",
        "user",
        model="m",
        temperature=0.0,
        max_tokens=16,
        tier=1,
        lane="test",
    )
    assert out["content"] == ""
