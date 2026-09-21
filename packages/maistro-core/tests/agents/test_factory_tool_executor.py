"""The factory's tool_executor seam, closed and pinned (#840 Slice 5).

``create_agents`` accepted ``tool_executor`` and dropped it on the floor for
every shipped manifest (all five declare ``tools: []``, so the wiring rule
never fired and the production bridge passed an implicit ``None``): the first
manifest that declares a tool would silently run without it. These tests pin
both halves of the honest contract:

1. an executor passed to ``create_agents`` reaches the agents whose identities
   declare tools (``Agent._run_strategy`` forwards it into the strategy);
2. an agent with declared tools and NO executor REFUSES tool calls through the
   strategy loop -- the refusal string, not an exception and never an
   execution.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from maistro.agents.factory import create_agents, instantiate_agent
from maistro.agents.strategies.react import ReactStrategy
from maistro.testing.faux_provider import FauxProvider, FauxResponse
from maistro.types.agent import AgentIdentity


def _write_tools_agent_dir(base: Path, name: str = "tooler") -> Path:
    """A manifest that actually declares a tool -- the shape no shipped
    manifest has today, which is exactly why the seam stayed latent."""
    agent_dir = base / name
    agent_dir.mkdir()
    manifest = {
        "name": name,
        "description": "declares a tool",
        "tools": ["web_search"],
        "reasoning": {"strategy": "react"},
    }
    (agent_dir / "agent.yaml").write_text(yaml.safe_dump(manifest))
    (agent_dir / "SOUL.md").write_text("Soul body.")
    (base / "PREAMBLE.md").write_text("preamble for {{agent_name}}")
    return base


def _create_kwargs(agents_dir: Path, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "agents_dir": agents_dir,
        "prompt_manager": _PromptManager(),
        "llm": None,
        "context_builder": None,
        "warden": None,
        "sentinel": None,
        "learning_store": None,
        "learning_extractor": None,
        "outcome_store": None,
        "session_store": None,
        "quota_tracker": None,
        "tracer": None,
    }
    values.update(overrides)
    return values


class _PromptManager:
    async def upsert(self, name: str, body: str, label: str = "") -> None:
        del name, body, label


def _tools_for(name: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


async def test_create_agents_threads_a_real_executor_into_the_agent(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    async def executor(tool_name: str, tool_args: dict[str, Any]) -> str:
        calls.append((tool_name, tool_args))
        return f"ran {tool_name}"

    provider = FauxProvider()
    provider.seed_tool_call("web_search", {"query": "latest"})
    provider.seed(FauxResponse(content="answered from the tool"))

    agents = await create_agents(
        **_create_kwargs(_write_tools_agent_dir(tmp_path), llm=provider, tool_executor=executor)
    )

    agent = agents["tooler"]
    # The wiring rule the factory owns: declared tools -> the executor lands
    # on the agent, which is what _run_strategy forwards into the strategy.
    assert agent._tool_executor is executor
    assert agent.identity.tools == ("web_search",)

    # And the forwarding is real: a tool call round-trips through the
    # strategy into the executor and back into the tool history.
    result = await agent._run_strategy(
        [{"role": "user", "content": "search"}],
        "m",
        _tools_for("web_search"),
        {},
        None,
    )

    assert calls == [("web_search", {"query": "latest"})]
    assert result.tool_history[0]["result"] == "ran web_search"
    assert result.response == "answered from the tool"


async def test_declared_tools_without_an_executor_refuse_instead_of_executing(
    tmp_path: Path,
) -> None:
    provider = FauxProvider()
    provider.seed_tool_call("web_search", {"query": "latest"})
    provider.seed(FauxResponse(content="answered without the tool"))

    agents = await create_agents(**_create_kwargs(_write_tools_agent_dir(tmp_path), llm=provider))

    agent = agents["tooler"]
    assert agent._tool_executor is None

    result = await agent._run_strategy(
        [{"role": "user", "content": "search"}],
        "m",
        _tools_for("web_search"),
        {},
        None,
    )

    # The refusal contract of the un-guarded branch: a tool-history RESULT
    # string, not an exception, and nothing was executed.
    assert result.tool_history[0]["result"] == "Tool 'web_search' not available"
    assert result.response == "answered without the tool"
    assert result.done is True


def test_instantiate_agent_builds_a_runtime_agent_from_a_ready_identity() -> None:
    """``instantiate_agent`` (#840 Slice 4) is the factory's single construction
    path for a caller that already holds a definition -- no manifest walk, but
    the strategy registry is seeded and the wiring rule fires exactly as a full
    ``create_agents`` run would. hive-conductor's materialization service calls
    it cross-package, so the construction is pinned here, in maistro-core."""

    async def executor(tool_name: str, tool_args: dict[str, Any]) -> str:
        del tool_name, tool_args
        return "ran"

    identity = AgentIdentity(
        name="tooler",
        description="declares a tool",
        soul_prompt_name="agent.tooler.soul",
        tools=("web_search",),
        reasoning_strategy="react",
    )

    agent = instantiate_agent(
        identity,
        prompt_manager=_PromptManager(),
        llm=None,
        context_builder=None,
        warden=None,
        tool_executor=executor,
    )

    assert agent.identity is identity
    # Strategy resolution through the registry the factory ensures is seeded:
    # "react" resolves to the real strategy, not the direct fallback.
    assert isinstance(agent._strategy, ReactStrategy)
    # The wiring rule: declared tools -> the executor lands on the agent.
    assert agent._tool_executor is executor
