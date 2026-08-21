from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from maistro.classifier.engine import ClassifierEngine
from maistro.container import Container
from maistro.graph.phases import GraphPhase
from maistro.graph.types import (
    AgentRole,
    GraphConfig,
    GraphEdge,
    HyperagentOutput,
)
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.quota.tracker import InMemoryQuotaTracker
from maistro.router.selector import RouterEngine
from maistro.sessions.store import InMemorySessionStore
from maistro.testing.faux_provider import (
    FauxProvider,
    FauxResponse,
    code_output,
    plan_output,
    review_output,
)
from maistro.testing.harness import HarnessEnvironment, create_test_environment
from maistro.types.config import AgentConfig


class TestFactoryWiring:
    async def test_factory_returns_fully_wired_environment(self):
        env = create_test_environment()
        assert isinstance(env, HarnessEnvironment)
        assert isinstance(env.container, Container)
        assert isinstance(env.classifier, ClassifierEngine)
        assert isinstance(env.router, RouterEngine)
        assert isinstance(env.provider, FauxProvider)
        assert env.events == []
        assert env.responses == []

    async def test_factory_has_in_memory_stores(self):
        env = create_test_environment()
        c = env.container
        assert isinstance(c.learning_store, InMemoryLearningStore)
        assert isinstance(c.outcome_store, InMemoryOutcomeStore)
        assert isinstance(c.session_store, InMemorySessionStore)
        assert isinstance(c.quota_tracker, InMemoryQuotaTracker)
        assert c.warden is not None
        assert c.gate is not None
        assert c.sentinel is not None

    async def test_factory_default_config(self):
        env = create_test_environment()
        assert env.container.config.router_api_key == "test-key"
        assert env.container.agents == {}


class TestSendPrompt:
    async def test_send_prompt_routes_through_provider(self):
        env = create_test_environment()
        env.provider.seed(
            FauxResponse(content="hello world", usage_prompt_tokens=5, usage_completion_tokens=10)
        )
        result = await env.send_prompt("write a hello world function")
        assert env.provider.call_count >= 1
        assert len(env.responses) == 1
        assert "choices" in result

    async def test_send_prompt_captures_response(self):
        env = create_test_environment()
        env.provider.seed(
            FauxResponse(content="test output", usage_prompt_tokens=5, usage_completion_tokens=10)
        )
        await env.send_prompt("generate something")
        last = env.get_last_response()
        assert last is not None
        assert "choices" in last
        assert last["choices"][0]["message"]["content"] == "test output"

    async def test_multiple_send_prompts_accumulate(self):
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
        last = env.get_last_response()
        assert last is not None
        assert last["choices"][0]["message"]["content"] == "three"


class TestGraphEvents:
    async def test_run_graph_captures_events(self):
        env = create_test_environment()
        env.provider.seed(plan_output(), code_output(), review_output())
        await env.run_graph(task_description="implement hello world")
        assert len(env.events) > 0
        types_seen = {e.type for e in env.events}
        assert "graph_started" in types_seen
        assert "graph_completed" in types_seen
        run_id = env.graph_run.run_id
        assert all(e.run_id == run_id for e in env.events)

    async def test_node_events_in_order(self):
        env = create_test_environment()
        env.provider.seed(plan_output(), code_output(), review_output())
        await env.run_graph(task_description="implement feature")
        node_started = [e for e in env.events if e.type == "node_started"]
        node_completed = [e for e in env.events if e.type == "node_completed"]
        assert len(node_started) >= 2
        assert len(node_completed) >= 2
        started_roles = [e.role for e in node_started]
        completed_roles = [e.role for e in node_completed]
        assert "planner" in started_roles
        assert "coder" in started_roles
        planner_start_idx = next(i for i, r in enumerate(started_roles) if r == "planner")
        planner_complete_idx = next(i for i, r in enumerate(completed_roles) if r == "planner")
        assert planner_start_idx <= planner_complete_idx

    async def test_get_events_filters_by_type(self):
        env = create_test_environment()
        env.provider.seed(plan_output(), code_output(), review_output())
        await env.run_graph(task_description="test task")
        all_events_count = len(env.events)
        node_completed = env.get_events("node_completed")
        assert all(e.type == "node_completed" for e in node_completed)
        assert len(env.events) == all_events_count

    async def test_assert_event_type_raises_on_mismatch(self):
        env = create_test_environment()
        env.provider.seed(plan_output(), code_output(), review_output())
        await env.run_graph(task_description="test task")
        actual_count = len(env.get_events("node_completed"))
        with pytest.raises(AssertionError, match=r"Expected \d+ events.*got \d+"):
            env.assert_event_type("node_completed", actual_count + 5)


class TestCustomComponents:
    async def test_custom_provider_seeded(self):
        custom = FauxProvider()
        custom.seed(FauxResponse(content="custom A"), FauxResponse(content="custom B"))
        env = create_test_environment(provider=custom)
        assert env.provider is custom
        r1 = await env.send_prompt("first")
        r2 = await env.send_prompt("second")
        assert r1["choices"][0]["message"]["content"] == "custom A"
        assert r2["choices"][0]["message"]["content"] == "custom B"

    async def test_custom_agent_config(self):
        cfg = AgentConfig(router_api_key="custom-key", litellm_url="http://custom:4000")
        env = create_test_environment(config=cfg)
        assert env.container.config is cfg
        assert env.container.config.router_api_key == "custom-key"
        assert env.container.config.litellm_url == "http://custom:4000"

    async def test_custom_agents_registered(self):
        agent_a = MagicMock(name="agent_a")
        agent_b = MagicMock(name="agent_b")
        env = create_test_environment(agents={"planner_agent": agent_a, "coder_agent": agent_b})
        assert "planner_agent" in env.container.agents
        assert "coder_agent" in env.container.agents
        assert env.container.agents["planner_agent"] is agent_a
        assert env.container.agents["coder_agent"] is agent_b
        assert (
            env.container.intent_registry.get_agent_for_intent("planner_agent") == "planner_agent"
        )

    async def test_custom_graph_config(self):
        cfg = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.CODER],
            edges=[GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER)],
        )
        env = create_test_environment(graph_config=cfg)
        env.provider.seed(plan_output(), code_output())
        await env.run_graph(task_description="implement hello world")
        roles = [e.role for e in env.get_events("node_started")]
        assert "planner" in roles
        assert "coder" in roles
        assert "reviewer" not in roles


class TestNoIO:
    def test_no_network_imports(self):
        import maistro.testing.harness as mod

        with open(mod.__file__) as fh:
            source = fh.read()
        for forbidden in ("httpx", "aiohttp", "requests", "asyncpg", "sqlalchemy"):
            assert forbidden not in source

    async def test_all_stores_in_memory(self):
        env = create_test_environment()
        assert type(env.container.learning_store).__name__ == "InMemoryLearningStore"
        assert type(env.container.outcome_store).__name__ == "InMemoryOutcomeStore"
        assert type(env.container.session_store).__name__ == "InMemorySessionStore"


class TestIsolation:
    async def test_environments_independent(self):
        env_a = create_test_environment()
        env_b = create_test_environment()
        env_a.provider.seed(FauxResponse(content="response A"))
        env_b.provider.seed(FauxResponse(content="response B"))
        ra = await env_a.send_prompt("prompt")
        rb = await env_b.send_prompt("prompt")
        assert ra["choices"][0]["message"]["content"] == "response A"
        assert rb["choices"][0]["message"]["content"] == "response B"
        assert env_a.events is not env_b.events
        assert env_a.responses is not env_b.responses

    async def test_data_isolation_between_environments(self):
        env1 = create_test_environment()
        env1.provider.seed(FauxResponse(content="first env"))
        await env1.send_prompt("remember this")
        env2 = create_test_environment()
        assert len(env2.responses) == 0
        assert len(env2.events) == 0


class TestReset:
    async def test_reset_clears_state(self):
        env = create_test_environment()
        env.provider.seed(
            plan_output(),
            code_output(),
            review_output(),
        )
        await env.run_graph(task_description="test")
        await env.send_prompt("hello")
        assert len(env.events) > 0
        assert len(env.responses) > 0
        env.reset()
        assert env.events == []
        assert env.responses == []
        assert env.provider.call_count == 0

    async def test_reset_allows_reuse(self):
        env = create_test_environment()
        env.provider.seed(FauxResponse(content="first"))
        await env.send_prompt("first prompt")
        env.reset()
        env.provider.seed(FauxResponse(content="second"))
        await env.send_prompt("second prompt")
        assert len(env.responses) == 1
        assert env.responses[0]["choices"][0]["message"]["content"] == "second"

    async def test_reset_preserves_agents(self):
        agent_a = MagicMock(name="agent_a")
        agent_b = MagicMock(name="agent_b")
        env = create_test_environment(agents={"a": agent_a, "b": agent_b})
        env.reset()
        assert "a" in env.container.agents
        assert "b" in env.container.agents
        assert env.container.agents["a"] is agent_a
        assert env.container.agents["b"] is agent_b


class TestEventFilter:
    async def test_event_filter_limits_types(self):
        env = create_test_environment(
            event_filter={"node_completed", "graph_completed"},
        )
        env.provider.seed(plan_output(), code_output(), review_output())
        await env.run_graph(task_description="test task")
        for e in env.events:
            assert e.type in ("node_completed", "graph_completed")
        assert env.get_events("node_started") == []


class TestErrorHandling:
    async def test_error_propagates_graph_failed(self):
        env = create_test_environment()
        env.provider.seed_error(RuntimeError("test error"))
        await env.run_graph(task_description="failing task")
        types_seen = {e.type for e in env.events}
        assert "graph_failed" in types_seen
        assert env.graph_run.phase == GraphPhase.FAILED


class TestRunGraphOutput:
    async def test_run_graph_returns_hyperagent_output(self):
        env = create_test_environment()
        env.provider.seed(plan_output(), code_output(), review_output())
        result = await env.run_graph(task_description="implement hello world")
        assert isinstance(result, HyperagentOutput)
        assert env.graph_run.phase == GraphPhase.COMPLETED
        assert len(env.graph_run.node_runs) > 0
        assert all(nr.phase.value == "succeeded" for nr in env.graph_run.node_runs)
