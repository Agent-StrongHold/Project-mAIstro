"""Production wiring of the governed hive tool seam (#57).

The boot Agent tool executor, the chat web tools, and the governed helpers in
``services.governed_tools`` all cross the canonical Binding -> Invocation
boundary with host-owned contracts. These tests prove the shipped wiring --
not just the library -- enforces it: schema and allowlist refusals happen
before any backend, the reversibility tier is resolved from the host registry
and recorded as an Invocation admission fact, and a missing live canonical
identity is a refusal rather than a fallback to a raw effect.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from maistro.capabilities.invocation import InvocationStatus
from maistro.container import create_container
from maistro.graph.definitions import Graph, Node
from maistro.observability.correlation import bind_execution_context
from maistro.runs.lifecycle import transition_path
from maistro.runs.model import AttemptStatus, RunStatus
from maistro.runs.store import RunIntegrityError
from maistro.types.config import AgentConfig

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_WORKSPACE = "governed-tools-workspace"
_ACTOR = "governed-tools-operator"


class _Runtime:
    """A real SQLite Container with a live canonical Run/NodeRun/Attempt."""

    def __init__(self, container: Any, identity: tuple[str, str, str], project_id: str):
        self.container = container
        self.identity = identity
        self.project_id = project_id

    def context(self):
        return bind_execution_context(
            workspace_id=_WORKSPACE,
            project_id=self.project_id,
            run_id=self.identity[0],
            node_run_id=self.identity[1],
            attempt_id=self.identity[2],
        )


@pytest.fixture
async def runtime(tmp_path: pathlib.Path):
    database_url = f"sqlite:///{tmp_path / 'governed-tools.sqlite3'}"
    container = await create_container(
        AgentConfig(router_api_key="fixture-router-key", database_url=database_url)
    )
    await container.workspace_store.create(
        name="Governed tools", creator_user_id=_ACTOR, workspace_id=_WORKSPACE
    )
    project = await container.project_scope_store.root_for_workspace(_WORKSPACE)
    graph = Graph(
        name="Governed tool execution",
        workspace_id=_WORKSPACE,
        project_id=project.project_id,
        nodes=[Node(node_id="tool-node", node_type="tool", name="research")],
    )
    run = await container.run_store.create_run(
        graph, actor_principal_id=_ACTOR, initial_status=RunStatus.QUEUED
    )
    await container.run_store.transition_run(run.run_id, RunStatus.RUNNING)
    node = await container.run_store.create_node_run(run.run_id, node_id="tool-node")
    for status in transition_path(node.status, RunStatus.RUNNING):
        node = await container.run_store.transition_node_run(node.node_run_id, status)
    attempt = await container.run_store.create_attempt(
        node.node_run_id,
        deadline_at=datetime.now(UTC) + timedelta(minutes=5),
        lease_holder="governed-tools-worker",
        lease_ttl=timedelta(minutes=5),
    )
    await container.run_store.transition_attempt(
        attempt.attempt_id,
        AttemptStatus.RUNNING,
        fencing_token=attempt.execution_lease.fencing_token,
    )
    try:
        yield _Runtime(
            container, (run.run_id, node.node_run_id, attempt.attempt_id), project.project_id
        )
    finally:
        await container.aclose()


def _tool_binding_id(runtime: _Runtime) -> str:
    return f"hive-tool:{_WORKSPACE}:{runtime.project_id}"


async def _tool_invocations(runtime: _Runtime, effect_key: str) -> list[Any]:
    return await runtime.container.capability_effects.invocation_store.list_effect(
        run_id=runtime.identity[0],
        node_run_id=runtime.identity[1],
        binding_id=_tool_binding_id(runtime),
        effect_key=effect_key,
    )


async def test_governed_tool_records_invocation_with_registry_tier(runtime, monkeypatch) -> None:
    """A shipped tool effect becomes a canonical Invocation whose admission
    carries the reversibility tier resolved from the host registry (#57)."""
    import services.governed_tools as governed
    import services.tool_executor as tools

    seen: list[tuple[str, int]] = []

    async def fake_search(query: str, max_results: int = 5, *, model_call=None) -> dict[str, Any]:
        seen.append((query, max_results))
        return {"query": query, "summary": "found", "citations": [], "source": "fixture"}

    monkeypatch.setattr(tools, "web_search", fake_search)

    with runtime.context():
        result = await governed.governed_web_search(
            "adr-050", max_results=2, container=runtime.container
        )

    assert result["summary"] == "found"
    assert seen == [("adr-050", 2)]
    from maistro.tools.contracts import canonical_digest

    rows = await _tool_invocations(
        runtime, f"tool:web_search:{canonical_digest({'query': 'adr-050', 'max_results': 2})}"
    )
    assert len(rows) == 1
    invocation = rows[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.binding.capability == governed.HIVE_TOOL_CAPABILITY
    assert (invocation.workspace_id, invocation.project_id) == (_WORKSPACE, runtime.project_id)
    assert (invocation.run_id, invocation.node_run_id, invocation.attempt_id) == runtime.identity
    # The tier is an admission fact resolved from the host registry, never a
    # caller string: INTERNAL per the shipped read-only contract.
    assert invocation.request["_tool_reversibility"] == "internal"


async def test_unlisted_and_badly_typed_tools_refuse_before_the_backend(
    runtime, monkeypatch
) -> None:
    import services.governed_tools as governed
    import services.tool_executor as tools

    called = False

    async def fake_search(query: str, max_results: int = 5, *, model_call=None) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)

    from maistro.tools.contracts import ToolArgumentError, ToolNotAuthorized

    with runtime.context():
        with pytest.raises(ToolNotAuthorized):
            await governed.governed_hive_tool(
                "shell", {"cmd": "rm -rf /"}, container=runtime.container
            )
        with pytest.raises(ToolArgumentError):
            await governed.governed_web_search(
                "query", max_results="not-a-number", container=runtime.container
            )
        # A caller-supplied allowlist can only narrow, never widen.
        with pytest.raises(ToolNotAuthorized):
            await governed.governed_hive_tool(
                "web_search",
                {"query": "query"},
                container=runtime.container,
                authorized_tools=frozenset(),
            )
    assert called is False
    assert await _tool_invocations(runtime, "tool:web_search:") == []


async def test_governed_tool_refuses_without_live_canonical_identity(runtime, monkeypatch) -> None:
    """No live Run/NodeRun/Attempt means refusal, not a raw fallback effect."""
    import services.governed_tools as governed
    import services.tool_executor as tools

    called = False

    async def fake_search(query: str, max_results: int = 5, *, model_call=None) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)

    # Outside any execution context the seam fails closed.
    with pytest.raises(RunIntegrityError):
        await governed.governed_web_search("query", container=runtime.container)
    assert called is False


async def test_chat_web_tools_route_through_the_governed_seam(runtime, monkeypatch) -> None:
    """The chat handlers execute via governed_web_search/governed_browse_url."""
    import services.chat_completion as chat
    import services.governed_tools as governed

    routed: list[str] = []

    async def fake_governed_web_search(query, max_results=5, *, model_call=None, container=None):
        routed.append(query)
        return {"query": query, "summary": "ok", "citations": [], "source": "fixture"}

    async def fake_governed_browse_url(url, task="Extract key facts and quotes", *, container=None):
        routed.append(url)
        return {"url": url, "title": url, "text": "body"}

    monkeypatch.setattr(governed, "governed_web_search", fake_governed_web_search)
    monkeypatch.setattr(governed, "governed_browse_url", fake_governed_browse_url)

    with runtime.context():
        search = await chat._tool_web_search({"query": "hive conductor"}, "user-1", None)
        browse = await chat._tool_browse_url({"url": "https://example.com"}, "user-1", None)

    assert search["summary"] == "ok"
    assert browse["title"] == "https://example.com"
    assert routed == ["hive conductor", "https://example.com"]


async def test_boot_agent_tool_effect_creates_its_own_invocation(runtime, monkeypatch) -> None:
    """The admitted boot executor admits the tool effect itself, beneath the
    same live Attempt its model sub-effects correlate to."""
    import services.tool_executor as tools

    from maistro.capabilities.admitted_model import AdmittedModelCalls
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.types.tool import ToolCall

    seen: list[str] = []

    async def fake_browse(url: str, task: str) -> dict[str, Any]:
        seen.append(url)
        return {"url": url, "title": url, "text": "facts"}

    monkeypatch.setattr(tools, "browse_url", fake_browse)

    async def refusing_complete(**_kwargs: Any) -> Any:  # pragma: no cover - must not run
        raise AssertionError("browse_url needs no model sub-effect")

    calls = AdmittedModelCalls(
        runtime.container.capability_effects,
        registry=runtime.container.provider_registry,
        router=runtime.container.llm_router,
        endpoint=GatewayEndpoint(base_url="https://gateway.fixture", api_key="unused"),
        run_store=runtime.container.run_store,
        binding_ids=(),
    )
    monkeypatch.setattr(calls, "complete", refusing_complete)
    executor = tools.admitted_tool_executor(calls, container=runtime.container)

    with runtime.context():
        result = await executor.execute_tool_call(
            ToolCall(id="call-1", name="browse_url", arguments={"url": "https://example.com"}),
            agent_name="researcher",
        )

    assert result["title"] == "https://example.com"
    assert seen == ["https://example.com"]
    from maistro.tools.contracts import canonical_digest

    scope = '["researcher",0,0,"call-1","browse_url"]'
    rows = await _tool_invocations(
        runtime,
        f"tool:browse_url:{scope}:{canonical_digest({'url': 'https://example.com'})}",
    )
    assert len(rows) == 1
    assert rows[0].status is InvocationStatus.COMPLETED


async def test_boot_executor_reports_contract_refusals_as_strategy_errors(
    runtime, monkeypatch
) -> None:
    import services.tool_executor as tools

    from maistro.capabilities.admitted_model import AdmittedModelCalls
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
    from maistro.types.tool import ToolCall

    called = False

    async def fake_search(query: str, max_results: int = 5, *, model_call=None) -> dict[str, Any]:
        nonlocal called
        called = True
        return {"query": query}

    monkeypatch.setattr(tools, "web_search", fake_search)
    calls = AdmittedModelCalls(
        runtime.container.capability_effects,
        registry=runtime.container.provider_registry,
        router=runtime.container.llm_router,
        endpoint=GatewayEndpoint(base_url="https://gateway.fixture", api_key="unused"),
        run_store=runtime.container.run_store,
        binding_ids=(),
    )
    executor = tools.admitted_tool_executor(calls, container=runtime.container)

    with runtime.context():
        result = await executor.execute_tool_call(
            ToolCall(id="call-2", name="web_search", arguments={"query": "ok", "extra": 1}),
            agent_name="researcher",
        )
        unlisted = await executor.execute_tool_call(
            ToolCall(id="call-3", name="shell", arguments={"cmd": "ls"}),
            agent_name="researcher",
        )

    assert isinstance(result, str) and result.startswith("Error: unknown tool arguments")
    assert isinstance(unlisted, str) and unlisted.startswith("Error: ")
    assert called is False


async def test_distinct_logical_tool_calls_do_not_replay_each_other(runtime, monkeypatch) -> None:
    """Two ToolCall ids with identical arguments are two logical effects; a
    retry of the same id replays the recorded outcome."""

    import services.governed_tools as governed
    import services.tool_executor as tools

    seen: list[str] = []

    async def fake_browse(url: str, task: str) -> dict[str, Any]:
        seen.append(url)
        return {"url": url, "title": url}

    monkeypatch.setattr(tools, "browse_url", fake_browse)

    with runtime.context():
        first = await governed.governed_hive_tool(
            "browse_url",
            {"url": "https://example.com"},
            container=runtime.container,
            effect_scope='["a",0,0,"call-1","browse_url"]',
        )
        second = await governed.governed_hive_tool(
            "browse_url",
            {"url": "https://example.com"},
            container=runtime.container,
            effect_scope='["a",0,0,"call-2","browse_url"]',
        )
        replay = await governed.governed_hive_tool(
            "browse_url",
            {"url": "https://example.com"},
            container=runtime.container,
            effect_scope='["a",0,0,"call-1","browse_url"]',
        )

    assert first == second == replay
    assert seen == ["https://example.com", "https://example.com"]


def test_hive_tool_registry_is_host_owned() -> None:
    """The exposure, schemas and tiers come from the module, not callers."""
    import services.governed_tools as governed

    registry = governed.hive_tool_contracts()
    assert registry.names() == frozenset({"web_search", "browse_url", "clarify"})
    for name in registry.names():
        assert registry.reversibility_of(name).value == "internal"
    schema = registry.require("web_search").schema
    assert schema["additionalProperties"] is False
    assert governed.hive_tool_names() == registry.names()
