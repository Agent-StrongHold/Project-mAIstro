from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from maistro.classifier.engine import ClassifierEngine
from maistro.container import Container
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.router.selector import RouterEngine
from maistro.sessions.store import InMemorySessionStore
from maistro.testing.faux_provider import FauxProvider, FauxResponse
from maistro.testing.harness import HarnessEnvironment, create_test_environment
from maistro.types.config import AgentConfig


class TestFactoryWiring:
    async def test_factory_returns_fully_wired_environment(self) -> None:
        env = create_test_environment()
        assert isinstance(env, HarnessEnvironment)
        assert isinstance(env.container, Container)
        assert isinstance(env.classifier, ClassifierEngine)
        assert isinstance(env.router, RouterEngine)
        assert isinstance(env.provider, FauxProvider)
        assert env.responses == []

    async def test_factory_has_in_memory_stores(self) -> None:
        env = create_test_environment()
        c = env.container
        assert isinstance(c.learning_store, InMemoryLearningStore)
        assert isinstance(c.outcome_store, InMemoryOutcomeStore)
        assert isinstance(c.session_store, InMemorySessionStore)
        assert isinstance(c.quota_tracker, InMemoryQuotaTracker)
        assert c.warden is not None
        assert c.gate is not None
        assert c.sentinel is not None

    async def test_factory_default_config(self) -> None:
        env = create_test_environment()
        assert env.container.config.router_api_key == "test-key"
        assert env.container.agents == {}


class TestSendPrompt:
    async def test_send_prompt_routes_through_provider(self) -> None:
        env = create_test_environment()
        env.provider.seed(
            FauxResponse(content="hello world", usage_prompt_tokens=5, usage_completion_tokens=10)
        )
        result = await env.send_prompt("write a hello world function")
        assert env.provider.call_count >= 1
        assert len(env.responses) == 1
        assert "choices" in result

    async def test_send_prompt_captures_response(self) -> None:
        env = create_test_environment()
        env.provider.seed(FauxResponse(content="test output"))
        await env.send_prompt("generate something")
        last = env.get_last_response()
        assert last is not None
        assert last["choices"][0]["message"]["content"] == "test output"

    async def test_multiple_send_prompts_accumulate(self) -> None:
        env = create_test_environment()
        env.provider.seed(
            FauxResponse(content="one"),
            FauxResponse(content="two"),
            FauxResponse(content="three"),
        )
        await env.send_prompt("prompt one")
        await env.send_prompt("prompt two")
        await env.send_prompt("prompt three")
        assert len(env.responses) == 3
        assert env.get_last_response()["choices"][0]["message"]["content"] == "three"  # type: ignore[index]


class TestCustomComponents:
    async def test_custom_provider_seeded(self) -> None:
        custom = FauxProvider()
        custom.seed(FauxResponse(content="custom A"), FauxResponse(content="custom B"))
        env = create_test_environment(provider=custom)
        assert (await env.send_prompt("first"))["choices"][0]["message"]["content"] == "custom A"
        assert (await env.send_prompt("second"))["choices"][0]["message"]["content"] == "custom B"

    async def test_custom_agent_config(self) -> None:
        cfg = AgentConfig(router_api_key="custom-key", litellm_url="http://custom:4000")
        env = create_test_environment(config=cfg)
        assert env.container.config is cfg

    async def test_custom_agents_registered(self) -> None:
        agent_a = MagicMock(name="agent_a")
        agent_b = MagicMock(name="agent_b")
        env = create_test_environment(agents={"planner_agent": agent_a, "coder_agent": agent_b})
        assert env.container.agents["planner_agent"] is agent_a
        assert env.container.agents["coder_agent"] is agent_b
        assert (
            env.container.intent_registry.get_agent_for_intent("planner_agent") == "planner_agent"
        )


class TestNoIO:
    def test_no_network_imports(self) -> None:
        import maistro.testing.harness as mod

        source = Path(mod.__file__).read_text()
        for forbidden in ("httpx", "aiohttp", "requests", "asyncpg", "sqlalchemy"):
            assert forbidden not in source

    async def test_all_stores_in_memory(self) -> None:
        env = create_test_environment()
        assert type(env.container.learning_store).__name__ == "InMemoryLearningStore"
        assert type(env.container.outcome_store).__name__ == "InMemoryOutcomeStore"
        assert type(env.container.session_store).__name__ == "InMemorySessionStore"


class TestIsolation:
    async def test_environments_independent(self) -> None:
        env_a = create_test_environment()
        env_b = create_test_environment()
        env_a.provider.seed(FauxResponse(content="response A"))
        env_b.provider.seed(FauxResponse(content="response B"))
        assert (await env_a.send_prompt("prompt"))["choices"][0]["message"][
            "content"
        ] == "response A"
        assert (await env_b.send_prompt("prompt"))["choices"][0]["message"][
            "content"
        ] == "response B"
        assert env_a.responses is not env_b.responses


class TestReset:
    async def test_reset_clears_state(self) -> None:
        env = create_test_environment()
        env.provider.seed(FauxResponse(content="response"))
        await env.send_prompt("hello")
        assert env.responses
        env.reset()
        assert env.responses == []
        assert env.provider.call_count == 0

    async def test_reset_preserves_agents(self) -> None:
        agent = MagicMock(name="agent")
        env = create_test_environment(agents={"a": agent})
        env.reset()
        assert env.container.agents["a"] is agent
