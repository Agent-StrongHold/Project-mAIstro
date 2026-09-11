"""Behavioral pins for the one-node legacy adapter extracted in #835.

`services/legacy_dag_node.py` holds the per-node compatibility surface the
convergence kept: the tool-node dispatch, the per-node isolation
classification, and the compatibility wave helper older tests still call.
Canonical execution reaches all of it through `LegacyConductorNode`, so these
tests exercise the helpers directly — the scheduler-shaped callers that used
to wrap them are gone, and with them the incidental coverage.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

from maistro.graph.nodes.base import NodeContext

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


# --- tool-node dispatch --------------------------------------------------------


async def test_an_unknown_tool_fails_the_node_without_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wave contract: a bad node is a failed result, not a dead run."""
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    monkeypatch.setattr(tools, "TOOLS", {})
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_tool_node(
        {"id": "n1", "role": "worker", "tool": "no_such_tool"},
        "n1",
        {},
        results,
        "task",
    )

    assert results["n1"]["success"] is False
    assert "Unknown tool" in results["n1"]["response"]


async def test_web_search_iterates_over_a_parent_json_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    seen: list[tuple[str, int]] = []

    async def fake_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
        seen.append((query, max_results))
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)
    results: dict[str, dict[str, Any]] = {
        "src": {"response": '{"topics": ["alpha", "beta"]}', "success": True}
    }

    await adapter._run_tool_node(
        {"id": "n1", "tool": "web_search", "tool_config": {"iterate_over": "src.topics"}},
        "n1",
        {"n1": {"src"}},
        results,
        "task",
    )

    assert [query for query, _ in seen] == ["alpha", "beta"]
    assert results["n1"]["success"] is True
    assert '"alpha"' in results["n1"]["response"]


async def test_web_search_falls_back_to_the_task_when_iteration_data_is_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parent result that is not the promised JSON shape searches the task
    description once rather than running zero queries and reporting success."""
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    seen: list[str] = []

    async def fake_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
        seen.append(query)
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)
    results: dict[str, dict[str, Any]] = {"src": {"response": "not json", "success": True}}

    await adapter._run_tool_node(
        {"id": "n1", "tool": "web_search", "tool_config": {"iterate_over": "src.topics"}},
        "n1",
        {"n1": {"src"}},
        results,
        "the task text",
    )

    assert seen == ["the task text"]
    assert results["n1"]["success"] is True


async def test_web_search_templated_queries_from_the_task_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    seen: list[str] = []

    async def fake_search(query: str, *, max_results: int = 5) -> dict[str, Any]:
        seen.append(query)
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)

    await adapter._run_tool_node(
        {
            "id": "n1",
            "tool": "web_search",
            "tool_config": {"queries_from_input": True, "query_template": "site:docs {input}"},
        },
        "n1",
        {},
        {},
        "read the label",
    )

    assert seen == ["site:docs read the label"]


async def test_clarify_renders_each_question_with_its_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    async def fake_clarify(questions: list[str], context: dict[str, Any]) -> dict[str, str]:
        return {str(index + 1): f"answer {index + 1}" for index in range(len(questions))}

    monkeypatch.setattr(tools, "clarify", fake_clarify)
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_tool_node(
        {"id": "n1", "tool": "clarify", "tool_config": {"questions": ["why?", "when?"]}},
        "n1",
        {},
        results,
        "task",
    )

    assert results["n1"]["success"] is True
    assert "Q: why?" in results["n1"]["response"]
    assert "A: answer 1" in results["n1"]["response"]


async def test_clarify_uses_the_supplied_governed_model_caller() -> None:
    from services.tool_executor import clarify

    captured: dict[str, Any] = {}

    async def model_call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        captured["messages"] = messages
        captured.update(kwargs)
        return '{"answers": {"1": "governed answer"}}'

    answers = await clarify(["why?"], {"input": "task"}, model_call=model_call)

    assert answers == {"1": "governed answer"}
    assert captured["model"] == "chat"
    assert "Original request: task" in captured["messages"][0]["content"]


async def test_grounded_search_uses_the_supplied_governed_model_caller() -> None:
    from services.tool_executor import _gemini_grounded_search

    async def model_call(_messages: list[dict[str, Any]], **_kwargs: Any) -> str:
        return '{"summary": "current", "citations": [{"title": "Doc"}]}'

    result = await _gemini_grounded_search("the topic", 1, model_call=model_call)

    assert result == {
        "query": "the topic",
        "summary": "current",
        "citations": [{"title": "Doc"}],
        "source": "gemini-grounded",
    }


async def test_browse_url_returns_the_extractor_payload_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    async def fake_browse(url: str, task: str) -> dict[str, Any]:
        return {"url": url, "task": task, "facts": ["one"]}

    monkeypatch.setattr(tools, "browse_url", fake_browse)
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_tool_node(
        {"id": "n1", "tool": "browse_url", "tool_config": {"url": "https://example.com"}},
        "n1",
        {},
        results,
        "task",
    )

    assert results["n1"]["success"] is True
    assert '"facts"' in results["n1"]["response"]


async def test_a_generic_tool_result_is_json_encoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    async def fake_tool(task_desc: str) -> dict[str, Any]:
        return {"did": task_desc}

    monkeypatch.setattr(tools, "TOOLS", {"custom": fake_tool})
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_tool_node({"id": "n1", "tool": "custom"}, "n1", {}, results, "the task")

    assert results["n1"] == {
        "role": "worker",
        "response": '{"did": "the task"}',
        "success": True,
    }


async def test_a_failing_tool_becomes_a_failed_node_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    async def boom(task_desc: str) -> dict[str, Any]:
        raise RuntimeError("tool exploded")

    monkeypatch.setattr(tools, "TOOLS", {"custom": boom})
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_tool_node({"id": "n1", "tool": "custom"}, "n1", {}, results, "task")

    assert results["n1"]["success"] is False
    assert "Tool error" in results["n1"]["response"]


async def test_run_llm_node_dispatches_a_tool_node_without_touching_the_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_run_llm_node` is the historical single entry for both shapes; a node
    with a `tool` key must never resolve a model or build a call."""
    import services.legacy_dag_node as adapter
    import services.tool_executor as tools

    def _unexpected_builder(*_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        raise AssertionError("llm builder must not be consulted for a tool node")

    async def fake_tool(task_desc: str) -> str:
        return f"tool:{task_desc}"

    monkeypatch.setattr(tools, "TOOLS", {"custom": fake_tool})
    results: dict[str, dict[str, Any]] = {}

    await adapter._run_llm_node(
        {"id": "n1", "tool": "custom"},
        "n1",
        {},
        results,
        "task",
        on_response=None,
        llm_builder=_unexpected_builder,
    )

    assert results["n1"]["success"] is True


# --- per-node isolation classification ----------------------------------------


def test_an_untrusted_node_without_admin_approval_is_blocked() -> None:
    import services.legacy_dag_node as adapter

    assert adapter._classify_node_execution({"config": {"untrusted": True}}, "n1") == "blocked"


def test_an_approved_untrusted_node_goes_to_the_sandbox() -> None:
    import services.legacy_dag_node as adapter

    assert (
        adapter._classify_node_execution(
            {"config": {"untrusted": True, "tier_approved_by": "admin"}}, "n1"
        )
        == "sandbox"
    )


@pytest.mark.parametrize(
    "config",
    [
        {"capabilities": ["shell"]},
        {"capabilities": ["jira_write"]},
        {"capabilities": ["file_write"]},
        {"execution_tier": "container"},
    ],
)
def test_dangerous_capabilities_and_heavy_tiers_go_to_the_sandbox(config: dict) -> None:
    import services.legacy_dag_node as adapter

    assert adapter._classify_node_execution({"config": config}, "n1") == "sandbox"


def test_a_node_with_no_tier_and_no_capabilities_defaults_to_the_sandbox() -> None:
    """No declared shape at all: the floor is the sandbox, not the loop."""
    import services.legacy_dag_node as adapter

    assert adapter._classify_node_execution({"config": {}}, "n1") == "sandbox"
    assert adapter._classify_node_execution({}, "n1") == "sandbox"


def test_a_declared_but_benign_shape_still_sandboxes() -> None:
    import services.legacy_dag_node as adapter

    assert (
        adapter._classify_node_execution({"config": {"capabilities": ["read_only"]}}, "n1")
        == "sandbox"
    )


def test_safe_and_light_tiers_run_inline() -> None:
    import services.legacy_dag_node as adapter

    assert adapter._classify_node_execution({"config": {"execution_tier": "safe"}}, "n1") == "async"
    assert (
        adapter._classify_node_execution({"config": {"execution_tier": "light"}}, "n1") == "async"
    )


# --- compatibility helpers retained for tests ----------------------------------


def test_build_dependency_graph_maps_nodes_and_inbound_edges() -> None:
    import services.legacy_dag_node as adapter

    node_map, inbound = adapter._build_dependency_graph(
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        [
            {"from_node": "a", "to_node": "b"},
            {"from_node": "ghost", "to_node": "c"},  # unknown endpoints are ignored
        ],
    )

    assert set(node_map) == {"a", "b", "c"}
    assert inbound == {"a": set(), "b": {"a"}, "c": set()}


async def test_run_subprocess_wave_runs_each_node_and_fires_usage_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter

    def fake_subprocess(node: dict, task: str, context: str, env: dict, mode: str) -> dict:
        return {
            "role": "worker",
            "response": f"ran {node['id']} with {task!r}",
            "success": True,
            "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        }

    monkeypatch.setattr(adapter, "_run_node_subprocess", fake_subprocess)

    usage_events: list[dict[str, Any]] = []

    def on_response(data: dict, response: Any) -> None:
        usage_events.append(data)

    results: dict[str, dict[str, Any]] = {"up": {"response": "ctx", "success": True}}

    await adapter._run_subprocess_wave(
        ["n1"],
        {"n1": {"id": "n1"}},
        {"n1": {"up"}},
        results,
        "task",
        {"PATH": ""},
        "interactive",
        on_response,
    )

    assert results["n1"]["success"] is True
    assert "ran n1" in results["n1"]["response"]
    assert usage_events and usage_events[0]["usage"]["completion_tokens"] == 2


# --- the adapter node itself ----------------------------------------------------


def _ctx() -> NodeContext:
    return NodeContext(run_id="run-1", dag_id="dag-1", node_id="n1")


def _adapter_node(raw_node: dict[str, Any], **kwargs: Any):
    from services.legacy_dag_node import LegacyConductorNode

    return LegacyConductorNode(
        raw_node=raw_node,
        task_desc=kwargs.pop("task_desc", "the task"),
        node_env=kwargs.pop("node_env", {}),
        execution_mode=kwargs.pop("execution_mode", "interactive"),
        on_response=kwargs.pop("on_response", None),
        **kwargs,
    )


async def test_an_unapproved_untrusted_adapter_node_refuses_to_execute() -> None:
    node = _adapter_node({"id": "n1", "config": {"untrusted": True}})

    with pytest.raises(PermissionError, match="untrusted node requires admin approval"):
        await node._execute(node.input_schema(), _ctx())


async def test_canonical_model_node_records_attempt_correlated_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import new_in_memory_effect_context
    from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter

    class _Response:
        status_code = 200

        def json(self) -> dict[str, Any]:
            return {
                "model": "model-v2",
                "choices": [{"message": {"content": "governed answer"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 2},
            }

    class _Client:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> _Response:
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    effects = new_in_memory_effect_context()
    await effects.bindings.put(
        Binding(
            binding_id="legacy-model-binding",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="n1",
            capability=MODEL_CHAT_CAPABILITY,
        )
    )
    registry = InMemoryProviderRegistry()
    node = _adapter_node(
        {
            "id": "n1",
            "model": "legacy-model",
            "binding_id": "legacy-model-binding",
            "config": {"execution_tier": "safe"},
        },
        node_env={"LITELLM_API_BASE": "http://gateway.test"},
        effect_context=effects,
        provider_registry=registry,
        llm_router=CostAwareRouter(registry),
    )

    result = await node.run(
        node.input_schema(),
        NodeContext(
            run_id="run-1",
            dag_id="dag-1",
            node_id="n1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            workspace_id="ws-1",
            project_id="project-1",
        ),
    )

    assert result.success is True
    assert result.output is not None
    assert result.output.response == "governed answer"
    invocations = list(effects.invocation_store._items.values())  # type: ignore[attr-defined]
    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation.run_id == "run-1"
    assert invocation.node_run_id == "node-run-1"
    assert invocation.attempt_id == "attempt-1"
    assert invocation.binding.provider_name == "legacy-model"
    assert invocation.usage is not None
    assert invocation.usage.input_units == 4
    assert invocation.usage.output_units == 2


@pytest.mark.parametrize("failure", ["connect", "http500", "timeout"])
async def test_governed_model_failure_cannot_report_success(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    import httpx

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import new_in_memory_effect_context
    from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
    from maistro.providers.registry import InMemoryProviderRegistry
    from maistro.providers.router import CostAwareRouter

    class _Response:
        status_code = 500

        def json(self) -> dict[str, Any]:
            return {"error": "gateway failure"}

    class _Client:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, *_args: Any, **_kwargs: Any) -> Any:
            if failure == "connect":
                raise httpx.ConnectError("gateway unavailable")
            if failure == "timeout":
                raise httpx.ReadTimeout("gateway timed out")
            return _Response()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    effects = new_in_memory_effect_context()
    await effects.bindings.put(
        Binding(
            binding_id="legacy-failing-binding",
            workspace_id="ws-1",
            project_id="project-1",
            node_id="n1",
            capability=MODEL_CHAT_CAPABILITY,
        )
    )
    registry = InMemoryProviderRegistry()
    node = _adapter_node(
        {"id": "n1", "binding_id": "legacy-failing-binding", "config": {"execution_tier": "safe"}},
        node_env={"LITELLM_API_BASE": "http://gateway.test"},
        effect_context=effects,
        provider_registry=registry,
        llm_router=CostAwareRouter(registry),
    )

    result = await node.run(
        node.input_schema(),
        NodeContext(
            run_id="run-1",
            dag_id="dag-1",
            node_id="n1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            workspace_id="ws-1",
            project_id="project-1",
        ),
    )

    assert result.success is False
    assert result.status == "failed"
    invocations = list(effects.invocation_store._items.values())  # type: ignore[attr-defined]
    assert len(invocations) == 1
    assert invocations[0].status.value == ("failed" if failure == "connect" else "unknown")


async def test_a_sandbox_tier_adapter_node_runs_the_isolated_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter

    captured: dict[str, Any] = {}

    def fake_subprocess(raw_node: dict, task: str, context: str, env: dict, mode: str) -> dict:
        captured.update(node=raw_node["id"], task=task, context=context, mode=mode)
        return {
            "role": "worker",
            "response": "isolated output",
            "success": True,
            "usage": {"prompt_tokens": 3, "completion_tokens": 4},
        }

    monkeypatch.setattr(adapter, "_run_node_subprocess", fake_subprocess)

    usage_events: list[dict[str, Any]] = []

    def on_response(data: dict, response: Any) -> None:
        usage_events.append(data)

    node = _adapter_node(
        {"id": "n1", "config": {"capabilities": ["shell"]}},
        on_response=on_response,
    )
    output = await node._execute(node.input_schema(), _ctx())

    assert captured == {"node": "n1", "task": "the task", "context": "", "mode": "interactive"}
    assert output.response == "isolated output"
    assert usage_events and usage_events[0]["usage"]["prompt_tokens"] == 3


async def test_a_failed_isolated_node_fails_the_adapter_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.legacy_dag_node as adapter

    def fake_subprocess(raw_node: dict, task: str, context: str, env: dict, mode: str) -> dict:
        return {"role": "worker", "response": "subprocess refused", "success": False}

    monkeypatch.setattr(adapter, "_run_node_subprocess", fake_subprocess)

    node = _adapter_node({"id": "n1", "config": {"capabilities": ["shell"]}})

    with pytest.raises(RuntimeError, match="subprocess refused"):
        await node._execute(node.input_schema(), _ctx())
