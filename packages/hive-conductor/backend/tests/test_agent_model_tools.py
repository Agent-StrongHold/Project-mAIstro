"""Boot Agent tools use persisted admission and preserve logical effect identity."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from adapters.maistro_core import _construct_runtime
from config import Settings

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.invocation import InvocationStatus, UnsafeEffectRetry
from maistro.container import Container, create_container
from maistro.graph.definitions import Graph, Node
from maistro.http import set_test_transport
from maistro.observability.correlation import bind_execution_context
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.security._types import AuthContext
from maistro.types.config import AgentConfig, SecurityConfig

_WORKSPACE = "agent-tools-workspace"
_ACTOR = "agent-tools-operator"
_BINDING = "agent-tools-binding"
_MODEL = "agent-tools-model"
_TOOLS = ("clarify", "web_search", "browse_url")


@dataclass
class ToolRuntime:
    owner: Container
    agent: Any
    identity: tuple[str, str, str]
    project_id: str
    sent: list[httpx.Request]

    def context(self):
        return bind_execution_context(
            workspace_id=_WORKSPACE,
            project_id=self.project_id,
            run_id=self.identity[0],
            node_run_id=self.identity[1],
            attempt_id=self.identity[2],
        )

    def executor(self, *, depth: int = 0, authorized: bool = True):
        return self.agent._governed_tool_executor(
            None,
            {
                "auth": AuthContext(
                    user_id=_ACTOR,
                    roles=frozenset({"operator"}) if authorized else frozenset(),
                ),
            },
            **({"delegation_depth": depth} if depth else {}),
        )

    async def invoke(
        self,
        tool: str = "clarify",
        args: dict[str, Any] | None = None,
        *,
        call_id: str = "tool-call-1",
        depth: int = 0,
        round_num: int | None = None,
        authorized: bool = True,
    ):
        with self.context():
            _, result = await self.agent._strategy._execute_one_tool_call(
                {
                    "id": call_id,
                    "function": {
                        "name": tool,
                        "arguments": json.dumps(
                            args
                            if args is not None
                            else {
                                "questions": ["Which audience?"],
                                "context": {"input": "Build a project"},
                            }
                        ),
                    },
                },
                tools=None,
                tool_executor=self.executor(depth=depth, authorized=authorized),
                trace=None,
                warden=None,
                sentinel=None,
                auth=None,
                security_pipeline=True,
                **({"tool_round": round_num} if round_num is not None else {}),
            )
            return result

    async def history(self, *, call_id="tool-call-1", depth=0, round_num=0, tool="clarify"):
        key = json.dumps(
            [self.agent.identity.name, depth, round_num, call_id, tool], separators=(",", ":")
        )
        return await self.owner.capability_effects.invocation_store.list_effect(
            run_id=self.identity[0],
            node_run_id=self.identity[1],
            binding_id=_BINDING,
            effect_key=f"agent-tool:{key}",
        )


@pytest.fixture
async def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request):
    """Real SQLite Container, admission records, factory, Agent and security."""
    database_url = f"sqlite:///{tmp_path / 'runtime.sqlite3'}"
    initial = await create_container(
        AgentConfig(router_api_key="fixture-router-key", database_url=database_url)
    )
    await initial.workspace_store.create(
        name="Tools", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    condition = getattr(request, "param", "valid")
    providers = tmp_path / "providers.yaml"
    providers.write_text(
        f"models:\n  - name: {_MODEL}\n    provider: openai\n"
        "    cost_input: 1.0\n    cost_output: 2.0\n    latency_p50_ms: 1\n"
    )
    declarations = (
        []
        if condition == "absent"
        else [
            {
                "binding_id": _BINDING,
                "project_id": "foreign-project" if condition == "foreign" else project.project_id,
                "provider_name": _MODEL,
                "disabled": condition == "disabled",
            }
        ]
    )
    owner = await create_container(
        AgentConfig(
            router_api_key="fixture-router-key",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            litellm_key="operator-scoped-fixture-key",
            provider_config_path=str(providers),
            model_bindings=declarations,
            security=SecurityConfig(permissions={tool: ["operator"] for tool in _TOOLS}),
        )
    )
    agents = tmp_path / "agents"
    agent_dir = agents / "researcher"
    agent_dir.mkdir(parents=True)
    (agents / "PREAMBLE.md").write_text("Preamble for {{agent_name}}")
    declared_tools = ["web_search", "browse_url"] if condition == "unlisted-tool" else list(_TOOLS)
    (agent_dir / "agent.yaml").write_text(
        "name: researcher\ndescription: research tool agent\n"
        f"tools: {json.dumps(declared_tools)}\nreasoning:\n  strategy: react\n"
    )
    (agent_dir / "SOUL.md").write_text("Research the user's question.")

    async def existing_container(config):
        return owner

    monkeypatch.setattr("maistro.container.create_container", existing_container)
    monkeypatch.setattr(
        "services.secrets.maistro_llm_api_key", lambda settings: "unused-endpoint-key"
    )
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "request-alias")
    for key in ("BRAVE_SEARCH_API_KEY", "SERPER_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    class UnavailableBrowser:
        async def search_web(self, *args, **kwargs):
            raise RuntimeError("hermetic browser unavailable")

    monkeypatch.setattr("maistro.tools.browser.BrowserClient", UnavailableBrowser)
    sent = []

    def transport(req):
        assert req.url.host == "gateway.fixture", req.url
        sent.append(req)
        payload = json.loads(req.content)
        content = (
            {"answers": {"1": "Developers"}}
            if "clarify requirements" in str(payload["messages"])
            else {"summary": "Useful research", "citations": [{"url": "https://example.test"}]}
        )
        return httpx.Response(
            200,
            json={
                "model": f"{_MODEL}-version",
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
            },
        )

    set_test_transport(httpx.MockTransport(transport))
    try:
        embedded = await _construct_runtime(
            Settings(
                maistro_agents_dir=str(agents),
                litellm_api_base="https://gateway.fixture/custom/provider/api/",
                hive_default_workspace_id=_WORKSPACE,
                maistro_model_bindings=declarations,
            )
        )
        graph = Graph(
            name="Agent tool execution",
            workspace_id=_WORKSPACE,
            project_id=project.project_id,
            nodes=[Node(node_id="agent-node", node_type="agent", name="researcher")],
        )
        run = await owner.run_store.create_run(
            graph, actor_principal_id=_ACTOR, initial_status=RunStatus.QUEUED
        )
        await owner.run_store.transition_run(run.run_id, RunStatus.RUNNING)
        node = await owner.run_store.create_node_run(run.run_id, node_id="agent-node")
        for status in transition_path(node.status, RunStatus.RUNNING):
            node = await owner.run_store.transition_node_run(node.node_run_id, status)
        attempt = await owner.run_store.create_attempt(
            node.node_run_id,
            deadline_at=(
                datetime.now(UTC) + timedelta(seconds=20 if condition == "short-deadline" else -5)
                if condition in {"short-deadline", "expired-deadline"}
                else None
            ),
            lease_holder=None if condition == "unleased" else "agent-tool-worker",
            lease_ttl=timedelta(minutes=30),
        )
        await owner.run_store.transition_attempt(
            attempt.attempt_id,
            AttemptStatus.RUNNING,
            fencing_token=attempt.execution_lease.fencing_token
            if attempt.execution_lease
            else None,
        )
        yield ToolRuntime(
            owner,
            embedded.agents["researcher"],
            (run.run_id, node.node_run_id, attempt.attempt_id),
            project.project_id,
            sent,
        )
    finally:
        set_test_transport(None)
        await owner.aclose()


@pytest.mark.parametrize(
    "tool,args,expected",
    [
        (
            "clarify",
            {"questions": ["Which audience?"], "context": {"input": "Build a project"}},
            "Developers",
        ),
        ("web_search", {"query": "Useful research", "max_results": 1}, "Useful research"),
    ],
)
async def test_boot_agent_model_tool_uses_persisted_authority(runtime, tool, args, expected):
    assert expected in await runtime.invoke(tool, args)
    (row,) = await runtime.history(tool=tool)
    assert row.status is InvocationStatus.COMPLETED
    assert (row.workspace_id, row.project_id, row.actor_id) == (
        _WORKSPACE,
        runtime.project_id,
        _ACTOR,
    )
    assert (row.run_id, row.node_run_id, row.attempt_id) == runtime.identity
    assert row.binding.binding_id == _BINDING
    assert row.usage.input_units == 1000
    (sent,) = runtime.sent
    assert str(sent.url) == "https://gateway.fixture/custom/provider/api/chat/completions"
    assert sent.headers["Authorization"] == "Bearer operator-scoped-fixture-key"
    payload = json.loads(sent.content)
    assert payload["model"] == _MODEL
    assert payload["response_format"] == {"type": "json_object"}
    assert "temperature" not in payload
    assert sent.extensions["timeout"]["read"] == 30.0


@pytest.mark.parametrize(
    "runtime", ["absent", "foreign", "disabled", "unleased", "expired-deadline"], indirect=True
)
async def test_boot_tool_refuses_invalid_admission(runtime):
    with pytest.raises((BindingResolutionError, RunIntegrityError)):
        await runtime.invoke()
    assert runtime.sent == []


async def test_revocation_is_checked_before_completed_replay(runtime):
    first = await runtime.invoke()
    assert await runtime.invoke() == first
    assert len(runtime.sent) == 1
    await runtime.owner.capability_effects.bindings.revoke(_BINDING)
    with pytest.raises(BindingResolutionError):
        await runtime.invoke()
    assert len(runtime.sent) == 1


@pytest.mark.parametrize("call_id", ["", " "])
async def test_missing_tool_identity_refuses_model_dispatch(runtime, call_id):
    with pytest.raises(RunIntegrityError, match="ToolCall"):
        await runtime.invoke(call_id=call_id)
    assert runtime.sent == []


async def test_sentinel_denial_precedes_model_dispatch(runtime):
    assert "denied" in (await runtime.invoke(authorized=False)).lower()
    assert runtime.sent == []


@pytest.mark.parametrize("which", ["id", "agent", "depth", "round"])
async def test_distinct_logical_calls_and_replay(runtime, which):
    from dataclasses import replace

    first = await runtime.invoke()
    options = {}
    if which == "id":
        options["call_id"] = "second-id"
    elif which == "agent":
        runtime.agent.identity = replace(runtime.agent.identity, name="second-agent")
    elif which == "depth":
        options["depth"] = 1
    else:
        options["round_num"] = 1
    assert await runtime.invoke(**options) == first
    assert await runtime.invoke(**options) == first
    assert len(runtime.sent) == 2


@pytest.mark.parametrize("runtime", ["short-deadline"], indirect=True)
async def test_tool_timeout_is_narrowed_by_attempt_deadline(runtime):
    await runtime.invoke()
    assert 0 < runtime.sent[0].extensions["timeout"]["read"] < 30


@pytest.mark.parametrize("strategy", ["react", "artificer"])
@pytest.mark.parametrize("failure", ["timeout", "invalid-json"])
async def test_unknown_stops_real_strategy_before_fresh_tool_or_round(runtime, strategy, failure):
    from maistro.agents.artificer.strategy import ArtificerStrategy
    from maistro.agents.strategies.react import ReactStrategy

    class OuterModel:
        count = 0

        async def complete(self, *args, **kwargs):
            self.count += 1
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "tool-call-1",
                                    "function": {
                                        "name": "clarify",
                                        "arguments": '{"questions":["Audience?"]}',
                                    },
                                },
                                {
                                    "id": "fresh-id",
                                    "function": {
                                        "name": "clarify",
                                        "arguments": '{"questions":["Audience?"]}',
                                    },
                                },
                            ]
                        }
                    }
                ]
            }

    model_calls_at_dispatch = []

    def transport(req):
        model_calls_at_dispatch.append(outer.count)
        runtime.sent.append(req)
        if failure == "timeout":
            raise httpx.ReadTimeout("ambiguous effect")
        return httpx.Response(200, text="not JSON")

    set_test_transport(httpx.MockTransport(transport))
    engine = ReactStrategy() if strategy == "react" else ArtificerStrategy()
    outer = OuterModel()
    with runtime.context(), pytest.raises((httpx.ReadTimeout, ValueError)):
        await engine.reason(
            messages=[{"role": "user", "content": "Clarify the audience"}],
            model="fixture",
            llm=outer,
            tool_executor=runtime.executor(),
            security_pipeline=True,
        )
    assert len(runtime.sent) == 1
    assert outer.count == model_calls_at_dispatch[0]
    (row,) = await runtime.history()
    assert row.status is InvocationStatus.UNKNOWN
    assert await runtime.history(call_id="fresh-id") == []
    with pytest.raises(UnsafeEffectRetry):
        await runtime.invoke()
    assert len(runtime.sent) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"choices": []},
        {"choices": [None]},
        {"choices": [{}]},
        {"choices": [{"message": None}]},
        {"choices": [{"message": {"content": 42}}]},
        {"choices": {"message": {"content": "ignored"}}},
        {"choices": [{"message": {"content": "{}"}}]},
        {"choices": [{"message": {"content": "not JSON"}}]},
    ],
)
async def test_malformed_model_answer_is_not_an_argument_error_result(runtime, body):
    def transport(req):
        runtime.sent.append(req)
        return httpx.Response(200, json=body)

    set_test_transport(httpx.MockTransport(transport))
    with pytest.raises((RuntimeError, ValueError)):
        await runtime.invoke()
    assert len(runtime.sent) == 1


@pytest.mark.parametrize("provider", ["brave", "serper", "tavily", "browser"])
async def test_search_nonmodel_paths_retain_lazy_model_callback(runtime, monkeypatch, provider):
    from types import SimpleNamespace

    from services import tool_executor

    seen = []
    expected = {
        "query": "Research",
        "summary": "Direct search",
        "citations": [],
        "source": provider,
    }

    async def search(query, count, key):
        seen.append((query, count, key))
        return expected

    if provider != "browser":
        env = {
            "brave": "BRAVE_SEARCH_API_KEY",
            "serper": "SERPER_API_KEY",
            "tavily": "TAVILY_API_KEY",
        }[provider]
        monkeypatch.setenv(env, "search-fixture")
        monkeypatch.setattr(tool_executor, f"_{provider}_search", search)
    else:

        class Browser:
            async def search_web(self, query, max_results):
                seen.append((query, max_results))
                return SimpleNamespace(summary="Direct search", citations=[], source="browser")

            async def aclose(self):
                seen.append("closed")

        monkeypatch.setattr("maistro.tools.browser.BrowserClient", Browser)
    await runtime.owner.capability_effects.bindings.revoke(_BINDING)
    result = await runtime.invoke("web_search", {"query": "Research", "max_results": 2})
    assert "Direct search" in result
    assert seen
    assert runtime.sent == []


@pytest.mark.parametrize("strategy", ["react", "artificer"])
async def test_real_rounds_with_reused_ids_make_distinct_effects_and_replay(runtime, strategy):
    from maistro.agents.artificer.strategy import ArtificerStrategy
    from maistro.agents.strategies.react import ReactStrategy

    class Outer:
        count = 0

        async def complete(self, *args, **kwargs):
            self.count += 1
            turn = self.count - (1 if strategy == "artificer" else 0)
            if turn <= 0:
                message = {"content": "Clarify in two rounds."}
            elif turn <= 2:
                message = {
                    "tool_calls": [
                        {
                            "id": "same-id",
                            "function": {
                                "name": "clarify",
                                "arguments": '{"questions":["Audience?"]}',
                            },
                        }
                    ]
                }
            else:
                message = {"content": "Finished"}
            return {"choices": [{"message": message}]}

    for _ in range(2):
        engine = ReactStrategy() if strategy == "react" else ArtificerStrategy()
        with runtime.context():
            result = await engine.reason(
                messages=[{"role": "user", "content": "Clarify"}],
                model="fixture",
                llm=Outer(),
                tool_executor=runtime.executor(),
                security_pipeline=True,
            )
        assert "Finished" in result.response
    assert len(runtime.sent) == 2
    for round_num in (0, 1):
        (row,) = await runtime.history(call_id="same-id", round_num=round_num)
        assert row.status is InvocationStatus.COMPLETED


@pytest.mark.parametrize("runtime", ["unlisted-tool"], indirect=True)
@pytest.mark.parametrize("strategy", ["react", "artificer", "builders_learning"])
async def test_boot_agent_denies_unlisted_model_tool_before_provider(
    runtime, strategy, monkeypatch
):
    """A valid operator Binding and Sentinel grant cannot widen the Agent declaration."""
    from maistro.agents.artificer.strategy import ArtificerStrategy
    from maistro.agents.strategies.builders_learning import BuildersLearningStrategy
    from maistro.agents.strategies.react import ReactStrategy
    from maistro.testing.faux_provider import FauxProvider, FauxResponse, ToolCallDef

    provider = FauxProvider()
    strategies = {
        "react": ReactStrategy,
        "artificer": ArtificerStrategy,
        "builders_learning": BuildersLearningStrategy,
    }
    if strategy == "artificer":
        provider.seed(FauxResponse(content="1. Clarify the audience."))

        async def no_sleep(_seconds):
            return None

        monkeypatch.setattr("maistro.agents.artificer.strategy.asyncio.sleep", no_sleep)
    provider.seed(
        FauxResponse(
            tool_calls=[ToolCallDef("clarify", {"questions": ["Audience?"]}, call_id="tool-call-1")]
        )
    )
    provider.seed(FauxResponse(content="Finished"))
    runtime.agent._strategy = strategies[strategy]()
    runtime.agent._llm = provider
    with runtime.context():
        response = await runtime.agent.handle(
            [{"role": "user", "content": "Clarify the audience"}],
            AuthContext(user_id=_ACTOR, roles=frozenset({"operator"})),
        )
    assert response.content.endswith("Finished")
    exposed_names = {
        tool["function"]["name"] for call in provider.call_log for tool in call.get("tools") or []
    }
    assert exposed_names == {"web_search", "browse_url"}
    assert runtime.sent == []
    assert await runtime.history() == []
    results = [
        message["content"]
        for message in provider.call_log[-1]["messages"]
        if message.get("role") == "tool"
    ]
    assert results == ["Error: Permission denied for undeclared tool 'clarify'"]


@pytest.mark.parametrize("runtime", ["unlisted-tool"], indirect=True)
@pytest.mark.parametrize("identity_hook", [False, True])
async def test_boot_agent_denies_strategy_widening_tool_exposure(runtime, identity_hook):
    """Even a strategy-authored schema cannot turn callback access into authority."""
    from maistro.types.agent import ReasoningResult
    from maistro.types.tool import ToolCall

    results = []

    class Strategy:
        async def reason(self, messages, model, llm, *, tools, tool_executor, **kwargs):
            tools.append({"type": "function", "function": {"name": "clarify", "parameters": {}}})
            args = {"questions": ["Audience?"]}
            if identity_hook:
                result = await tool_executor.execute_tool_call(
                    ToolCall("tool-call-1", "clarify", args),
                    agent_name="forged-agent",
                    delegation_depth=99,
                )
            else:
                result = await tool_executor("clarify", args)
            results.append(result)
            return ReasoningResult(response="Finished", done=True)

    runtime.agent._strategy = Strategy()
    with runtime.context():
        response = await runtime.agent.handle(
            [{"role": "user", "content": "Clarify the audience"}],
            AuthContext(user_id=_ACTOR, roles=frozenset({"operator"})),
        )
    assert response.content == "Finished"
    assert results == ["Error: Permission denied for undeclared tool 'clarify'"]
    assert runtime.sent == []
    assert await runtime.history() == []
