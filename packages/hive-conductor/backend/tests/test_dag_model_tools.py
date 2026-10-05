"""#1085: model sub-effects use the shipped DAG resolver and real Container."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from services import canonical_dag_runner as runner
from services import tool_executor
from services.dag_execution_scope import DagExecutionScope

from maistro.capabilities.invocation import InvocationStatus
from maistro.container import Container, create_container
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.types.config import AgentConfig

_WORKSPACE = "model-tools-workspace"
_ACTOR = "model-tools-user"
_BINDING = "model-tools-binding"
_MODEL = "model-tools-provider"


@pytest.fixture
async def container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> AsyncIterator[Container]:
    providers = tmp_path / "providers.yaml"
    providers.write_text(
        f"models:\n  - name: {_MODEL}\n    provider: openai\n"
        "    cost_input: 1.0\n    cost_output: 2.0\n    latency_p50_ms: 1\n"
    )
    database_url = f"sqlite:///{tmp_path / 'runtime.sqlite3'}"
    initial = await create_container(
        AgentConfig(router_api_key="test-router-key", database_url=database_url)
    )
    await initial.workspace_store.create(
        name="Model tools", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await initial.project_scope_store.root_for_workspace(_WORKSPACE)
    await initial.aclose()
    owner = await create_container(
        AgentConfig(
            router_api_key="test-router-key",
            database_url=database_url,
            workspace_id=_WORKSPACE,
            provider_config_path=str(providers),
            litellm_key="binding-scoped-test-key" if getattr(request, "param", True) else "",
            model_bindings=[
                {
                    "binding_id": _BINDING,
                    "project_id": project.project_id,
                    "provider_name": _MODEL,
                },
                {
                    "binding_id": "disabled-model",
                    "project_id": project.project_id,
                    "provider_name": _MODEL,
                    "disabled": True,
                },
                {
                    "binding_id": "foreign-model",
                    "project_id": "foreign-project",
                    "provider_name": _MODEL,
                },
            ],
        )
    )
    monkeypatch.setattr(runner, "_container", lambda: owner)
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "https://gateway.test")
    # The provider must use the Binding's credential rather than this ambient key.
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "ambient-key-must-not-win")
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "request-alias")

    def forbid_raw_model_http(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("tool adapters must not open raw model HTTP")

    monkeypatch.setattr(tool_executor, "shared_client", forbid_raw_model_http)
    yield owner
    await owner.aclose()


def _dag(tool: str = "clarify", *, binding_id: str = _BINDING) -> dict[str, Any]:
    return {
        "id": "model-tools-dag",
        "name": "Model tool production proof",
        "description": "Build a useful project",
        "nodes": [
            {
                "id": "tool-node",
                "role": "worker",
                "tool": tool,
                "model_binding_id": binding_id,
                "tool_config": {"questions": ["Which audience?"], "max_results": 1},
                "config": {"execution_tier": "safe", "timeout_s": 15},
            }
        ],
        "edges": [],
        "entry_node": "tool-node",
    }


async def _execute(container: Container, dag: dict[str, Any]) -> dict[str, Any]:
    return await runner.execute_dag(
        dag,
        scope=DagExecutionScope(
            workspace_id=_WORKSPACE,
            project_id=container.config.model_bindings[0].project_id,
            user_id=_ACTOR,
        ),
    )


def _model_transport(monkeypatch: pytest.MonkeyPatch, *, content: str | None = None):
    import maistro.capabilities.model_chat as model_chat
    from maistro.capabilities.providers.llm_gateway import _chat_payload

    calls: list[dict[str, Any]] = []

    async def execute(provider: Any, request: Any, *, endpoint: Any) -> dict[str, Any]:
        calls.append({"payload": _chat_payload(provider, request), "endpoint": endpoint})
        return {
            "model": f"{_MODEL}-version",
            "choices": [
                {
                    "message": {
                        "content": '{"answers":{"1":"Developers"}}' if content is None else content
                    }
                }
            ],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }

    # Substitute only physical Provider transport. Binding/policy/credential,
    # Invocation/quota/usage and Run/Attempt composition are production code.
    monkeypatch.setattr(model_chat, "execute_model_chat", execute)
    return calls


async def _invocations(container: Container, result: dict[str, Any], tool: str):
    nodes = await container.run_store.list_node_runs(result["run_id"])
    assert len(nodes) == 1
    node = nodes[0]
    attempts = await container.run_store.list_attempts(node.node_run_id)
    assert len(attempts) == 1
    inner = await container.invocation_store.list_effect(
        run_id=result["run_id"],
        node_run_id=node.node_run_id,
        binding_id=_BINDING,
        effect_key=f"legacy-tool:{tool}:model:1",
    )
    outer = await container.invocation_store.list_effect(
        run_id=result["run_id"],
        node_run_id=node.node_run_id,
        binding_id=f"legacy-tool:{_WORKSPACE}:{container.config.model_bindings[0].project_id}:tool-node:{tool}",
        effect_key=f"legacy-tool:{tool}",
    )
    return node, attempts[0], inner, outer


@pytest.mark.parametrize("binding_placement", ["top-level", "config"])
async def test_clarify_records_model_and_tool_on_the_same_real_attempt(
    container: Container, monkeypatch: pytest.MonkeyPatch, binding_placement: str
) -> None:
    calls = _model_transport(monkeypatch)
    dag = _dag()
    if binding_placement == "config":
        dag["nodes"][0]["config"]["model_binding_id"] = dag["nodes"][0].pop("model_binding_id")
    result = await _execute(container, dag)
    assert result["status"] == "completed", result
    assert "Developers" in result["node_results"]["tool-node"]["response"]
    node, attempt, inner, outer = await _invocations(container, result, "clarify")
    assert node.status is RunStatus.COMPLETED
    assert attempt.status is AttemptStatus.COMPLETED
    assert len(inner) == len(outer) == len(calls) == 1
    invocation = inner[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.attempt_id == outer[0].attempt_id == attempt.attempt_id
    assert invocation.actor_id == outer[0].actor_id == _ACTOR
    run = await container.run_store.get_run(result["run_id"])
    assert run.actor_principal_id == invocation.actor_id
    assert invocation.binding.workspace_id == _WORKSPACE
    assert invocation.binding.project_id == container.config.model_bindings[0].project_id
    assert invocation.usage.cost_cents == 2.0
    assert invocation.usage.model == _MODEL
    assert outer[0].usage is None
    assert calls[0]["endpoint"].base_url == "https://gateway.test"
    assert calls[0]["endpoint"].api_key == "binding-scoped-test-key"
    assert calls[0]["endpoint"].timeout_s == 15.0
    payload = calls[0]["payload"]
    assert payload["model"] == _MODEL  # the configured pin outranks request alias
    assert payload["response_format"] == {"type": "json_object"}
    assert "temperature" not in payload  # preserve the old Provider-default sampling
    assert "max_tokens" not in payload


@pytest.mark.parametrize("binding_id", ["", "missing-model", "disabled-model", "foreign-model"])
async def test_binding_refusals_fail_the_real_attempt_without_model_dispatch(
    container: Container, monkeypatch: pytest.MonkeyPatch, binding_id: str
) -> None:
    calls = _model_transport(monkeypatch)
    result = await _execute(container, _dag(binding_id=binding_id))
    assert result["status"] == "failed", result
    assert calls == []
    node, attempt, inner, outer = await _invocations(container, result, "clarify")
    assert node.status is RunStatus.FAILED
    # The canonical adapter returned a failed NodeResult: physical evaluation
    # completed, while its accepted domain outcome and NodeRun both failed.
    assert attempt.result["status"] == "failed"
    assert inner == []
    assert len(outer) == 1
    assert outer[0].status is not InvocationStatus.COMPLETED


@pytest.mark.parametrize(
    "content",
    ["not-json", "", "[]", '{"answers":[]}', "{}", '{"refusal":"no"}', '{"1":null}', '{"1":""}'],
)
async def test_bad_model_output_cannot_become_success_shaped_clarification(
    container: Container, monkeypatch: pytest.MonkeyPatch, content: str
) -> None:
    calls = _model_transport(monkeypatch, content=content)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert len(calls) == 1
    _, attempt, inner, outer = await _invocations(container, result, "clarify")
    assert attempt.result["status"] == "failed"
    assert inner[0].status is InvocationStatus.COMPLETED  # transport succeeded
    assert outer[0].status is not InvocationStatus.COMPLETED  # domain decoding failed


async def test_grounded_search_uses_the_same_model_capability(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.tools import browser

    class UnavailableBrowser:
        async def search_web(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("browser unavailable")

    monkeypatch.setattr(browser, "BrowserClient", UnavailableBrowser)
    for key in ("BRAVE_SEARCH_API_KEY", "SERPER_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    calls = _model_transport(
        monkeypatch,
        content=json.dumps({"summary": "A result", "citations": [{"url": "https://example.com"}]}),
    )
    result = await _execute(container, _dag("web_search"))
    assert result["status"] == "completed", result
    _, attempt, inner, outer = await _invocations(container, result, "web_search")
    assert len(inner) == len(outer) == len(calls) == 1
    assert inner[0].attempt_id == attempt.attempt_id
    assert inner[0].usage.cost_cents == 2.0
    assert calls[0]["payload"]["response_format"] == {"type": "json_object"}


@pytest.mark.parametrize("tool", ["clarify", "grounded"])
async def test_unbound_model_tools_fail_closed_without_environment_fallback(tool: str) -> None:
    with pytest.raises(RuntimeError, match="governed model capability"):
        if tool == "clarify":
            await tool_executor.clarify(["Who?"], {})
        else:
            await tool_executor._gemini_grounded_search("query", 1)


async def test_model_sub_effect_refuses_an_uncomposed_runtime() -> None:
    from services.legacy_dag_node import _tool_model_caller

    from maistro.capabilities.providers.llm_gateway import ModelChatRequest
    from maistro.graph.nodes.base import NodeContext

    call = _tool_model_caller(
        _dag()["nodes"][0], NodeContext(run_id="r", dag_id="g", node_id="tool-node"), None
    )
    with pytest.raises(RuntimeError, match="no governed model runtime"):
        await call(ModelChatRequest())


@pytest.mark.parametrize("unit", ["requests", "tokens", "micro_usd"])
async def test_real_quota_refuses_before_model_transport(
    container: Container, monkeypatch: pytest.MonkeyPatch, unit: Any
) -> None:
    from maistro.quota.invocation_quota import QuotaBudget
    from maistro.quota.sqlite_invocation_quota import SqliteInvocationQuota

    quota = container.capability_effects.quota
    assert isinstance(quota, SqliteInvocationQuota)
    await quota.register_budget(
        QuotaBudget(
            budget_id=f"model-tools-{unit}",
            unit=unit,
            limit=0 if unit == "requests" else 100000,
            period_start=0,
            period_end=2**62,
            coverage_ref="fresh-test-period",
            opening_spend=0,
            workspace_id=_WORKSPACE,
            principal_id=_ACTOR,
            capability="model.chat",
        )
    )
    calls = _model_transport(monkeypatch)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert calls == []
    # No estimate is invented from characters, registry prices or model defaults.
    assert "quota" in result["error"].lower()


@pytest.mark.parametrize("container", [False], indirect=True)
async def test_missing_scoped_credential_cannot_use_ambient_gateway_key(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _model_transport(monkeypatch)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert calls == []
    assert "credential" in result["error"].lower()


@pytest.mark.parametrize("refusal", ["revoked", "unavailable"])
async def test_runtime_authority_changes_are_observed_before_dispatch(
    container: Container, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    from maistro.capabilities.binding_store import RevocableBindingStore

    if refusal == "revoked":
        bindings = container.capability_effects.bindings
        assert isinstance(bindings, RevocableBindingStore)
        await bindings.revoke(_BINDING)
    else:
        container.provider_registry.mark_unavailable(_MODEL)
    calls = _model_transport(monkeypatch)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert calls == []


async def test_failed_provider_is_unknown_evidence_and_a_failed_node(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    import maistro.capabilities.model_chat as model_chat

    calls: list[str] = []

    async def fail(provider: Any, request: Any, *, endpoint: Any) -> Any:
        calls.append(provider.name)
        raise TimeoutError("provider completion unknown")

    monkeypatch.setattr(model_chat, "execute_model_chat", fail)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert calls == [_MODEL]
    node, attempt, inner, outer = await _invocations(container, result, "clarify")
    assert node.status is RunStatus.FAILED
    assert attempt.result["status"] == "failed"
    assert inner[0].status is InvocationStatus.UNKNOWN
    assert outer[0].status is not InvocationStatus.COMPLETED


def test_model_tool_module_contains_no_direct_model_egress() -> None:
    """A call-site ratchet regression cannot hide behind route/string scanning."""
    import ast
    import inspect

    source = inspect.getsource(tool_executor)
    assert "chat/completions" not in source
    for function in (tool_executor.clarify, tool_executor._gemini_grounded_search):
        calls = (
            node
            for node in ast.walk(ast.parse(inspect.getsource(function)))
            if isinstance(node, ast.Call)
        )
        assert not any(
            isinstance(call.func, ast.Attribute) and call.func.attr in {"post", "stream", "request"}
            for call in calls
        )


async def test_repeated_dags_share_binding_but_keep_distinct_execution_evidence(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _model_transport(monkeypatch)
    first = await _execute(container, _dag())
    second = await _execute(container, _dag())
    assert first["status"] == second["status"] == "completed"
    assert first["run_id"] != second["run_id"]
    _, first_attempt, first_inner, first_outer = await _invocations(container, first, "clarify")
    _, second_attempt, second_inner, second_outer = await _invocations(container, second, "clarify")
    assert first_attempt.attempt_id != second_attempt.attempt_id
    assert first_inner[0].invocation_id != second_inner[0].invocation_id
    assert first_outer[0].binding.binding_id == second_outer[0].binding.binding_id
    assert len(calls) == 2


async def test_concurrent_first_registration_reconciles_only_the_same_tool_binding(
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.legacy_dag_node import _register_tool_binding

    from maistro.capabilities.binding import Binding

    definition = {
        "binding_id": "first-registration-race",
        "workspace_id": _WORKSPACE,
        "project_id": container.config.model_bindings[0].project_id,
        "capability": "legacy_tool:clarify",
    }
    bindings = container.capability_effects.bindings
    original_get = bindings.get
    barrier = asyncio.Barrier(2)
    initial_reads = 0

    async def simultaneous_absence(binding_id: str):
        nonlocal initial_reads
        record = await original_get(binding_id)
        initial_reads += 1
        if initial_reads <= 2:
            assert record is None
            await barrier.wait()
        return record

    # Preserve the selected store's actual reads/writes. Only schedule the
    # two initial absent observations before either real put can win.
    monkeypatch.setattr(bindings, "get", simultaneous_absence)
    first, second = await asyncio.gather(
        _register_tool_binding(container.capability_effects, Binding(**definition)),
        _register_tool_binding(container.capability_effects, Binding(**definition)),
    )
    assert first == second
    with pytest.raises(ValueError, match="different definition"):
        await _register_tool_binding(
            container.capability_effects,
            Binding(**{**definition, "capability": "legacy_tool:web_search"}),
        )


async def test_reused_tool_definition_cannot_resurrect_a_revoked_binding(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maistro.capabilities.binding_store import RevocableBindingStore

    calls = _model_transport(monkeypatch)
    first = await _execute(container, _dag())
    _, _, _, outer = await _invocations(container, first, "clarify")
    bindings = container.capability_effects.bindings
    assert isinstance(bindings, RevocableBindingStore)
    await bindings.revoke(outer[0].binding.binding_id)
    second = await _execute(container, _dag())
    assert second["status"] == "failed"
    assert len(calls) == 1


async def test_completed_tool_replay_reuses_both_invocations_without_dispatch(
    container: Container, monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.legacy_dag_node import _run_tool_node

    from maistro.graph.nodes.base import NodeContext

    calls = _model_transport(monkeypatch)
    dag = _dag()
    first = await _execute(container, dag)
    node, attempt, inner, outer = await _invocations(container, first, "clarify")
    scratch: dict[str, dict[str, Any]] = {}
    await _run_tool_node(
        dag["nodes"][0],
        "tool-node",
        {},
        scratch,
        dag["description"],
        effect_context=container.capability_effects,
        ctx=NodeContext(
            run_id=first["run_id"],
            dag_id=dag["id"],
            node_id="tool-node",
            node_run_id=node.node_run_id,
            attempt_id=attempt.attempt_id,
            workspace_id=_WORKSPACE,
            project_id=container.config.model_bindings[0].project_id,
            user_id=_ACTOR,
        ),
    )
    assert scratch["tool-node"]["success"] is True
    _, _, replayed_inner, replayed_outer = await _invocations(container, first, "clarify")
    assert replayed_inner == inner
    assert replayed_outer == outer
    assert len(calls) == 1


@pytest.mark.parametrize("choices", [None, [], [None], [{"message": {}}]])
async def test_gateway_without_text_cannot_complete_the_tool(
    container: Container, monkeypatch: pytest.MonkeyPatch, choices: Any
) -> None:
    import maistro.capabilities.model_chat as model_chat

    async def empty(provider: Any, request: Any, *, endpoint: Any) -> dict[str, Any]:
        return {"choices": choices}

    monkeypatch.setattr(model_chat, "execute_model_chat", empty)
    result = await _execute(container, _dag())
    assert result["status"] == "failed", result
    assert "no text content" in result["error"]
