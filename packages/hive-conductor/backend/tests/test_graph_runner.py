"""Boy Scout coverage: services/graph_runner.py (was 10% line/branch).

Covers:
- execute_dag with stub maistro.graph: builds GraphConfig + invokes run_graph
- execute_dag entry_node fallback: when not set, uses first node's id
- genome_to_dag: maps PipelineGenome → DAG dict with all node + edge fields
- execute_champion: 4 branches (no svc / no population / no champion / success)
- _build_llm_call: no base URL → refuses (F3) unless ALLOW_STUB_LLM opt-in,
  in which case the stub payload is labelled `"stub": true`
- _build_llm_call: with base URL → real httpx fn
- _build_llm_call inner _httpx_llm: posts, parses content
- _build_llm_call with SecretStr-like api key (get_secret_value path)
- execute_dag_streaming: yields started + per-node + completed
- execute_dag_streaming: catches inner exception and yields failed
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import pathlib
import sys
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from services.dag_execution_scope import DagExecutionScope

from maistro.graph.durable_runs import RunStatus

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _execution_scope() -> DagExecutionScope:
    return DagExecutionScope(
        workspace_id="test-workspace", project_id="test-project", user_id="test-user"
    )


# --- _build_llm_call ----------------------------------------------------


def _unconfigure_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every LLM gateway env var — the "misconfigured deployment" state."""
    monkeypatch.delenv("LITELLM_API_BASE", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    monkeypatch.delenv("CHAT_DEFAULT_MODEL", raising=False)


def _set_allow_stub_llm(monkeypatch: pytest.MonkeyPatch, allowed: bool) -> None:
    """Force `Settings.allow_stub_llm`.

    `get_settings` is `@lru_cache`d, so setting ALLOW_STUB_LLM in the
    environment would not be observed; patch the accessor instead (same seam
    test_evolution_service.py uses).
    """
    import config

    class _S:
        allow_stub_llm = allowed

    monkeypatch.setattr(config, "get_settings", lambda: _S())


def test_build_llm_call_refuses_when_base_url_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """F3: no gateway and no opt-in → refuse loudly, never a stub.

    The old behaviour returned a success-shaped stub answer here, so a
    misconfigured deployment produced fake successes. The contract is now a
    `StubLLMNotAllowedError` naming what is unset and how to proceed.
    """
    from services.graph_runner import StubLLMNotAllowedError, _build_llm_call

    _unconfigure_llm(monkeypatch)
    _set_allow_stub_llm(monkeypatch, False)

    with pytest.raises(StubLLMNotAllowedError) as exc_info:
        _build_llm_call()

    message = str(exc_info.value)
    assert "LITELLM_API_BASE" in message  # names what is unset
    assert "ALLOW_STUB_LLM" in message  # names how to opt in


def test_build_llm_call_stub_is_labelled_when_opted_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the opt-in on, the stub still runs — but says so in its payload.

    `response`/`done` stay intact for callers that parse them; `stub: true` is
    the marker (maistro-evolve's SPEC-202 noise flag) that keeps a stub answer
    from being mistaken for a real one downstream.
    """
    import asyncio
    import json

    from services.graph_runner import _build_llm_call

    _unconfigure_llm(monkeypatch)
    _set_allow_stub_llm(monkeypatch, True)

    fn = _build_llm_call()
    payload = json.loads(asyncio.run(fn([{"role": "user", "content": "hi"}])))

    assert payload["stub"] is True
    assert "no LLM configured" in payload["response"]
    assert payload["done"] is True


def test_stub_llm_allowed_fails_closed_when_settings_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settings blow-up must not be read as consent to stub."""
    import config
    from services.graph_runner import stub_llm_allowed

    def _boom() -> Any:
        raise RuntimeError("settings exploded")

    monkeypatch.setattr(config, "get_settings", _boom)
    assert stub_llm_allowed() is False


def test_llm_gateway_configured_tracks_either_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.graph_runner import llm_gateway_configured

    _unconfigure_llm(monkeypatch)
    assert llm_gateway_configured() is False

    monkeypatch.setenv("LITELLM_PROXY_URL", "http://gateway.example")
    assert llm_gateway_configured() is True


async def test_run_llm_node_marks_node_failed_when_llm_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal reaches the DAG as a failed node, not a fake answer."""
    from services import graph_runner as gr

    _unconfigure_llm(monkeypatch)
    _set_allow_stub_llm(monkeypatch, False)

    results: dict[str, dict[str, Any]] = {}
    await gr._run_llm_node(
        {"id": "n1", "role": "worker"}, "n1", {"n1": set()}, results, "do a thing"
    )

    assert results["n1"]["success"] is False
    assert "LITELLM_API_BASE" in results["n1"]["response"]


async def test_execute_dag_streaming_fails_when_llm_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DAG stream against an unconfigured LLM ends in `failed`, not `completed`.

    The node is `safe`-tier so the LLM refusal is the failure that surfaces;
    a default-tier node is routed through the isolation floor instead, and
    that refusal is the sandbox contract's to assert, not this one's.
    """
    from services import graph_runner as gr

    _unconfigure_llm(monkeypatch)
    _set_allow_stub_llm(monkeypatch, False)

    events = [
        ev
        async for ev in gr.execute_dag_streaming(
            {
                "name": "d",
                "nodes": [
                    {
                        "id": "n1",
                        "role": "worker",
                        "config": {"execution_tier": "safe"},
                    }
                ],
                "edges": [],
            },
            scope=_execution_scope(),
        )
    ]

    statuses = [ev["status"] for ev in events]
    assert "completed" not in statuses
    assert statuses[-1] == "failed"
    assert events[-1]["error"] == "DAG execution failed; see server logs"


async def test_build_llm_call_real_httpx_posts_and_extracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://stub.example")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "default-model")

    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "out"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            captured["url"] = url
            captured["headers"] = headers
            captured["model"] = json["model"]
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    fn = _build_llm_call()
    out = await fn([{"role": "user", "content": "hi"}], model="picked-model")
    assert out == "out"
    assert captured["url"] == "http://stub.example/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer k"
    assert captured["model"] == "picked-model"


async def test_build_llm_call_on_response_hook_receives_body_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://stub.example")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {
                "choices": [{"message": {"content": "out"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 7},
            }

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    captured: dict[str, Any] = {}

    def on_response(data: dict, response: Any) -> None:
        captured["data"] = data

    fn = _build_llm_call(on_response)
    out = await fn([{"role": "user", "content": "hi"}], model="picked-model")
    assert out == "out"
    assert captured["data"]["usage"] == {"prompt_tokens": 5, "completion_tokens": 7}


async def test_build_llm_call_on_response_hook_failure_is_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://stub.example")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "out"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    def broken_hook(data: dict, response: Any) -> None:
        raise RuntimeError("recording hook blew up")

    fn = _build_llm_call(broken_hook)
    out = await fn([{"role": "user", "content": "hi"}], model="picked-model")
    assert out == "out"


async def test_build_llm_call_uses_default_model_when_kwarg_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without model kwarg, falls back to CHAT_DEFAULT_MODEL env var."""
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://x")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "k")
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "the-default")

    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            captured["model"] = json["model"]
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    fn = _build_llm_call()
    await fn([{"role": "user", "content": "hi"}])
    assert captured["model"] == "the-default"


async def test_build_llm_call_secret_str_api_key_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When LITELLM_API_KEY is set, it is passed as Bearer token."""
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://x")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.setenv("LITELLM_API_KEY", "from-secret")
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "m")

    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            captured["auth"] = headers.get("Authorization")
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    fn = _build_llm_call()
    await fn([{"role": "user", "content": "x"}])
    assert captured["auth"] == "Bearer from-secret"


async def test_build_llm_call_no_api_key_no_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If LITELLM_API_KEY is empty, Authorization header is 'Bearer '."""
    import httpx
    from services.graph_runner import _build_llm_call

    monkeypatch.setenv("LITELLM_API_BASE", "http://x")
    monkeypatch.delenv("LITELLM_PROXY_URL", raising=False)
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    monkeypatch.delenv("LITELLM_PROXY_KEY", raising=False)
    monkeypatch.setenv("CHAT_DEFAULT_MODEL", "m")

    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            pass

        def json(self) -> Any:
            return {"choices": [{"message": {"content": "ok"}}]}

    class _Client:
        def __init__(self, *a: Any, **kw: Any) -> None: ...
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *a: Any) -> None: ...
        async def post(self, url: str, *, json: Any, headers: Any) -> _Resp:
            captured["headers"] = dict(headers)
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    fn = _build_llm_call()
    await fn([{"role": "user", "content": "x"}])
    # With no API key set, raw_key is "" — header is still present but value is "Bearer "
    assert captured["headers"].get("Authorization") == "Bearer "


# --- execute_dag --------------------------------------------------------


async def test_execute_dag_builds_config_and_returns_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """execute_dag runs a wave executor; stub _build_llm_call and verify shape."""
    import services.graph_runner as gr

    # Stub _build_llm_call to return a coroutine that returns a response string.
    # n1 → n2 (two waves), so cycles == 2.
    calls: list[list[dict]] = []

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        calls.append(messages)
        return "stub response"

    monkeypatch.setattr(gr, "_build_llm_call", lambda *a, **kw: _stub_llm)

    out = await gr.execute_dag(
        {
            "name": "test",
            "description": "test dag",
            "nodes": [
                {
                    "id": "n1",
                    "role": "worker",
                    "name": "Worker",
                    "config": {"execution_tier": "safe"},
                },
                {
                    "id": "n2",
                    "role": "scout",
                    "name": "Scout",
                    "config": {"execution_tier": "safe"},
                },
            ],
            "edges": [{"from_node": "n1", "to_node": "n2"}],
            "entry_node": "n1",
        },
        scope=_execution_scope(),
    )
    assert out["status"] == "completed"
    assert out["cycles"] == 2  # wave 1: n1, wave 2: n2
    assert set(out["node_results"]) == {"n1", "n2"}
    assert out["node_results"]["n1"]["role"] == "worker"
    assert len(calls) == 2


async def test_execute_dag_entry_node_fallback_to_first_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-node DAG with no entry_node runs to completion (1 wave, 1 cycle)."""
    import services.graph_runner as gr

    calls: list[list[dict]] = []

    async def _stub_llm(messages: list[dict], **kw: Any) -> str:
        calls.append(messages)
        return "ok"

    monkeypatch.setattr(gr, "_build_llm_call", lambda *a, **kw: _stub_llm)

    out = await gr.execute_dag(
        {
            "name": "x",
            "nodes": [
                {
                    "id": "first-id",
                    "role": "worker",
                    "name": "F",
                    "config": {"execution_tier": "safe"},
                }
            ],
            "edges": [],
            # entry_node missing — wave executor needs no explicit entry; any
            # node with no inbound edges is a start node
        },
        scope=_execution_scope(),
    )
    assert out["status"] == "completed"
    assert out["cycles"] == 1
    assert "first-id" in out["node_results"]
    assert len(calls) == 1


# --- genome_to_dag ----------------------------------------------------


def test_genome_to_dag_maps_nodes_and_edges() -> None:
    from services.graph_runner import genome_to_dag

    class _Node:
        def __init__(self, **kw: Any) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    class _Edge:
        def __init__(self, **kw: Any) -> None:
            for k, v in kw.items():
                setattr(self, k, v)

    class _Topo:
        nodes: ClassVar = [
            _Node(
                id="abc123def",
                role="planner",
                model="m",
                system_prompt="p",
                strategy="react",
                temperature=0.5,
                max_tokens=512,
                max_tool_rounds=3,
            ),
        ]
        edges: ClassVar = [
            _Edge(id="e1", from_node="abc123def", to_node=None, condition=None),
        ]
        entry_node = "abc123def"
        max_cycles = 5
        use_scout = True

    class _Genome:
        topology = _Topo()
        name = "evolved"
        generation = 3
        fitness_score = 0.87
        id = "g-1"

    out = genome_to_dag(_Genome())
    assert out["name"] == "evolved"
    assert out["evolved"] is True
    assert out["genome_id"] == "g-1"
    assert out["nodes"][0]["id"] == "abc123def"
    assert out["nodes"][0]["name"] == "planner-abc123"  # first 6 chars
    assert out["edges"][0]["id"] == "e1"
    assert out["max_cycles"] == 5
    assert out["run_scout"] is True


# --- execute_champion ------------------------------------------------


async def test_execute_champion_returns_error_when_no_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo
    import services.graph_runner as gr

    evo._service = None
    out = await gr.execute_champion()
    assert out["status"] == "error"
    assert "not started" in out["error"]


async def test_execute_champion_no_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo
    import services.graph_runner as gr

    class _Svc:
        population = None

    evo._service = _Svc()
    try:
        out = await gr.execute_champion()
        assert out["status"] == "error"
        assert "population not initialized" in out["error"]
    finally:
        evo._service = None


async def test_execute_champion_no_champion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo
    import services.graph_runner as gr

    class _Pop:
        def get_champion(self) -> Any:
            return None

    class _Svc:
        population = _Pop()

    evo._service = _Svc()
    try:
        out = await gr.execute_champion()
        assert out["status"] == "error"
        assert "no champion" in out["error"]
    finally:
        evo._service = None


async def test_execute_champion_success_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.evolution as evo
    import services.graph_runner as gr

    class _Topo:
        nodes: ClassVar[list[Any]] = []
        edges: ClassVar[list[Any]] = []
        entry_node = ""
        max_cycles = 1
        use_scout = False

    class _Genome:
        id = "g-1"
        name = "champ"
        generation = 5
        fitness_score = 0.99
        topology = _Topo()

    class _Pop:
        def get_champion(self) -> Any:
            return _Genome()

    class _Svc:
        population = _Pop()

    evo._service = _Svc()

    async def _stub_execute(d: dict) -> dict[str, Any]:
        return {"status": "completed", "cycles": 0, "node_results": {}}

    monkeypatch.setattr(gr, "execute_dag", _stub_execute)
    try:
        out = await gr.execute_champion()
        assert out["status"] == "completed"
        assert out["genome_id"] == "g-1"
        assert out["fitness"] == 0.99
        assert out["generation"] == 5
    finally:
        evo._service = None


# --- execute_dag_streaming -------------------------------------------


class _CompletedRecord:
    """A finished canonical durable Run, in the shape `run_durable_graph` returns."""

    run_id = "run-1"

    class run:  # mirrors the durable record attribute
        status = RunStatus.COMPLETED
        error = None
        # Real `Run` records always carry their admission scope; `_project`
        # mirrors both onto the execution result (#1174).
        workspace_id = "hive-standalone-compat"
        project_id = "hive-standalone-compat"

    graph_state = SimpleNamespace(cycle=1, blackboard_snapshot={"node_annotations": {}})
    node_runs = (
        SimpleNamespace(
            node_id="n1",
            status=RunStatus.COMPLETED,
            result={"role": "worker", "response": "out", "success": True, "model": "m"},
        ),
    )


async def test_execute_dag_streaming_yields_full_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.graph_runner as gr
    from services import canonical_dag_runner as runner

    async def _run_durable_graph(graph: Any, **kw: Any) -> Any:
        return _CompletedRecord()

    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: object())
    monkeypatch.setattr(runner, "record_run_completion", lambda record: 0)
    monkeypatch.setattr(runner, "run_durable_graph", _run_durable_graph)

    events = []
    async for ev in gr.execute_dag_streaming(
        {
            "name": "x",
            "nodes": [{"id": "n1", "role": "worker", "name": "W"}],
            "edges": [],
            "entry_node": "n1",
        },
        scope=_execution_scope(),
    ):
        events.append(ev)
    statuses = [e["status"] for e in events]
    assert statuses == ["started", "node_complete", "completed"]


async def test_execute_dag_streaming_yields_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.graph_runner as gr
    from services import canonical_dag_runner as runner

    async def _boom(graph: Any, **kw: Any) -> Any:
        raise RuntimeError("synthetic")

    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: object())
    monkeypatch.setattr(runner, "run_durable_graph", _boom)

    events = []
    async for ev in gr.execute_dag_streaming(
        {
            "name": "x",
            "nodes": [{"id": "n1", "role": "worker", "name": "W"}],
            "edges": [],
            "entry_node": "n1",
        },
        scope=_execution_scope(),
    ):
        events.append(ev)
    assert events[0]["status"] == "started"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error"] == "RuntimeError: execution failed; see server logs"


async def test_execute_dag_streaming_defers_run_until_past_started_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `started` frame precedes execution (#355).

    `execute_dag_streaming` is an async generator: `run_durable_graph` (and the
    `on_result` projection) only run once the consumer resumes past the first
    frame. A websocket client that disconnects before acknowledging `started`
    therefore starts no Run at all — which is why the DAG Builder's unmount
    cleanup defers its socket close to that acknowledged frame instead of
    closing a CONNECTING socket (navigation must not cancel a requested Run).
    """

    import services.graph_runner as gr
    from services import canonical_dag_runner as runner

    calls: list[str] = []

    async def _run_durable_graph(graph: Any, **kw: Any) -> Any:
        calls.append("run")
        return _CompletedRecord()

    async def _project(result: dict[str, Any]) -> None:
        calls.append("project")

    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: object())
    monkeypatch.setattr(runner, "record_run_completion", lambda record: 0)
    monkeypatch.setattr(runner, "run_durable_graph", _run_durable_graph)

    stream = gr.execute_dag_streaming(
        {
            "name": "x",
            "nodes": [{"id": "n1", "role": "worker", "name": "W"}],
            "edges": [],
            "entry_node": "n1",
        },
        scope=_execution_scope(),
        on_result=_project,
    )
    first = await anext(stream)
    assert first["status"] == "started"
    # First frame produced, Run not yet started: this is exactly the window a
    # pre-acknowledgement client disconnect falls in.
    assert calls == []
    second = await anext(stream)
    assert second["status"] == "node_complete"
    # Resuming past `started` is what actually starts the Run and, after it
    # settles, records the projection.
    assert calls == ["run", "project"]
    await stream.aclose()


# --- execute_dag_streaming: the live contract (#1183) -------------------


def _live_dag(*node_ids: str) -> dict[str, Any]:
    ids = list(node_ids) or ["n1"]
    return {
        "name": "x",
        "nodes": [
            {
                "id": nid,
                "role": "worker",
                "name": nid.upper(),
                # A safe-tier LLM node: the sandbox tier would shell out to
                # bwrap, which this environment does not provide.
                "prompt": f"answer {nid}",
                "config": {"execution_tier": "safe"},
            }
            for nid in ids
        ],
        "edges": [
            {"id": f"{a}-{b}", "from_node": a, "to_node": b} for a, b in itertools.pairwise(ids)
        ],
        "entry_node": ids[0],
    }


def _completed_record_for(run_id: str, responses: dict[str, str]) -> Any:
    """A finished canonical durable Run carrying completed legacy nodes."""
    return SimpleNamespace(
        run_id=run_id,
        run=SimpleNamespace(
            status=RunStatus.COMPLETED,
            error=None,
            workspace_id="test-workspace",
            project_id="test-project",
        ),
        graph_state=SimpleNamespace(cycle=1, blackboard_snapshot={"node_annotations": {}}),
        node_runs=tuple(
            SimpleNamespace(
                node_id=node_id,
                status=RunStatus.COMPLETED,
                result={"role": "worker", "response": response, "success": True},
            )
            for node_id, response in responses.items()
        ),
    )


def _stub_canonical_walk(
    monkeypatch: pytest.MonkeyPatch,
    llm_builder: Any,
    walk: Any,
) -> None:
    """Point `execute_dag` at a stubbed durable walk with a stubbed spine."""
    from services import canonical_dag_runner as runner

    monkeypatch.setattr(gr_mod(), "_build_llm_call", llm_builder)
    monkeypatch.setattr(runner, "_container", lambda: None)
    monkeypatch.setattr(runner, "get_run_store", lambda: object())
    monkeypatch.setattr(runner, "record_run_completion", lambda record: 0)
    monkeypatch.setattr(runner, "run_durable_graph", walk)


def gr_mod() -> Any:
    import services.graph_runner as gr

    return gr


def _collect(stream: Any, on_frame: Any = None) -> tuple[asyncio.Task[None], list[dict[str, Any]]]:
    """Consume a stream in a background task, mirroring a socket reader."""
    frames: list[dict[str, Any]] = []

    async def run() -> None:
        try:
            async for frame in stream:
                frames.append(frame)
                if on_frame is not None:
                    await on_frame(frame)
        except (RuntimeError, asyncio.CancelledError):
            pass  # stream torn down under us (disconnect semantics)

    return asyncio.create_task(run()), frames


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_live_stream_delivers_node_frames_while_the_run_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1183: progress streams while the Run runs, not only after it settles.

    The stubbed walk executes the REAL legacy node adapter (so the real
    progress hook fires) and then blocks at a barrier before returning. The
    live node frame must arrive — durably recorded first — while the walk is
    still in flight.
    """
    import asyncio

    from services.legacy_dag_node import _LegacyInputs

    from maistro.graph.nodes.base import NodeContext

    llm_started = asyncio.Event()
    release_llm = asyncio.Event()
    walk_at_barrier = asyncio.Event()
    release_walk = asyncio.Event()
    walk_returned = asyncio.Event()

    def _gated_builder(on_response: Any = None):
        async def _call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            llm_started.set()
            await asyncio.wait_for(release_llm.wait(), timeout=10.0)
            return "out"

        return _call

    async def _walk(graph: Any, **kw: Any) -> Any:
        node = kw["node_resolver"]("n1", graph)
        ctx = NodeContext(
            run_id="run-live",
            dag_id="dag-live",
            node_id="n1",
            node_run_id="nr-1",
            attempt_id="a-1",
        )
        result = await node.run(_LegacyInputs(), ctx)
        assert result.success
        walk_at_barrier.set()
        await asyncio.wait_for(release_walk.wait(), timeout=10.0)
        walk_returned.set()
        return _completed_record_for("run-live", {"n1": "out"})

    recorded: list[dict[str, Any]] = []
    got_node_frame = asyncio.Event()
    recorded_at_frame: list[int] = []

    async def on_event(event: dict[str, Any]) -> int | None:
        recorded.append(dict(event))
        return len(recorded)

    async def on_frame(frame: dict[str, Any]) -> None:
        if frame.get("status") == "node_complete":
            recorded_at_frame.append(len(recorded))
            got_node_frame.set()

    _stub_canonical_walk(monkeypatch, _gated_builder, _walk)

    stream = gr_mod().execute_dag_streaming(
        _live_dag(),
        scope=_execution_scope(),
        execution_mode="interactive",
        on_event=on_event,
        keepalive_interval=0.05,
    )
    consumer, frames = _collect(stream, on_frame)
    try:
        # Resuming past `started` is what starts the walk (#355): the node's
        # LLM call only begins once the consumer pulls.
        await asyncio.wait_for(llm_started.wait(), timeout=10.0)
        release_llm.set()
        await asyncio.wait_for(walk_at_barrier.wait(), timeout=10.0)
        await asyncio.wait_for(got_node_frame.wait(), timeout=10.0)

        live_frame = next(f for f in frames if f["status"] == "node_complete")
        assert live_frame["success"] is True
        assert live_frame["node_id"] == "n1"
        assert live_frame["run_id"] == "run-live"
        assert live_frame["seq"] == 2
        # Mid-flight proof: the walk has not returned its record, yet the
        # node's outcome is already delivered — and already durable.
        assert not walk_returned.is_set()
        assert recorded_at_frame == [2]
        assert [ev["kind"] for ev in recorded] == ["node_started", "node_completed"]
        assert recorded[-1]["run_id"] == "run-live"

        release_walk.set()
        await asyncio.wait_for(consumer, timeout=10.0)
    finally:
        release_llm.set()
        release_walk.set()
        if not consumer.done():
            consumer.cancel()

    # The node already streamed live: no duplicated terminal replay, and the
    # terminal frame is the one canonical settlement produced.
    assert [frame["status"] for frame in frames] == ["started", "node_complete", "completed"]
    assert frames[-1]["run_id"] == "run-live"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_live_stream_sends_bounded_heartbeats_for_idle_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1183: idle stretches carry `heartbeat` frames so alive-idle is
    distinguishable from a dead socket, and the traffic stays bounded."""
    import asyncio

    from services.legacy_dag_node import _LegacyInputs

    from maistro.graph.nodes.base import NodeContext

    def _slow_builder(on_response: Any = None):
        async def _call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            await asyncio.sleep(0.25)
            return "out"

        return _call

    async def _walk(graph: Any, **kw: Any) -> Any:
        node = kw["node_resolver"]("n1", graph)
        ctx = NodeContext(run_id="run-idle", dag_id="d", node_id="n1")
        result = await node.run(_LegacyInputs(), ctx)
        assert result.success
        return _completed_record_for("run-idle", {"n1": "out"})

    async def on_event(event: dict[str, Any]) -> int | None:
        return 1

    _stub_canonical_walk(monkeypatch, _slow_builder, _walk)

    frames = []
    async for frame in gr_mod().execute_dag_streaming(
        _live_dag(),
        scope=_execution_scope(),
        execution_mode="interactive",
        on_event=on_event,
        keepalive_interval=0.05,
    ):
        frames.append(frame)

    statuses = [frame["status"] for frame in frames]
    heartbeats = [frame for frame in frames if frame["status"] == "heartbeat"]
    assert heartbeats, "an idle Run must emit at least one heartbeat"
    # Bounded: one per idle interval. The node sleeps 0.25s at a 0.05s
    # cadence; a per-tick emitter would produce hundreds.
    assert len(heartbeats) <= 10
    assert statuses[0] == "started"
    assert statuses[-1] == "completed"
    for heartbeat in heartbeats:
        assert set(heartbeat) == {"status", "run_id", "ts"}


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_live_stream_marks_resync_when_progress_channel_overflows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#1183: a consumer that stops reading must not silently lose frames.

    With the channel held at one slot, the second node's live frame is
    dropped. The stream then says so explicitly (`resync`) and backfills the
    missed node's terminal state from canonical truth before the terminal —
    every node's outcome appears exactly once.
    """
    import asyncio

    from services.legacy_dag_node import _LegacyInputs

    from maistro.graph.nodes.base import NodeContext

    gr = gr_mod()
    monkeypatch.setattr(gr, "STREAM_PROGRESS_QUEUE_MAX", 1)

    def _builder(on_response: Any = None):
        async def _call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            await asyncio.sleep(0.12)
            # The prompt is "answer <node_id>": reply with a per-node payload
            # so live and backfilled frames can be told apart by content.
            return f"out-{str(messages[0]['content']).split()[-1]}"

        return _call

    async def _walk(graph: Any, **kw: Any) -> Any:
        resolve = kw["node_resolver"]
        for node_id in ("n1", "n2"):
            node = resolve(node_id, graph)
            ctx = NodeContext(run_id="run-overflow", dag_id="d", node_id=node_id)
            result = await node.run(_LegacyInputs(), ctx)
            assert result.success
        walk_done.set()
        return _completed_record_for("run-overflow", {"n1": "out-n1", "n2": "out-n2"})

    async def on_event(event: dict[str, Any]) -> int | None:
        return 1

    walk_done = asyncio.Event()
    _stub_canonical_walk(monkeypatch, _builder, _walk)

    stream = gr.execute_dag_streaming(
        _live_dag("n1", "n2"),
        scope=_execution_scope(),
        execution_mode="interactive",
        on_event=on_event,
        keepalive_interval=0.05,
    )
    # Kick the walk past `started`, read exactly ONE frame (the first idle
    # heartbeat — the walk is still sleeping), then stop reading: the two
    # node frames queue up and the second overflows the single slot.
    aiter = stream.__aiter__()
    assert (await anext(aiter))["status"] == "started"
    kicked = asyncio.create_task(anext(aiter))
    kicked_frame = await asyncio.wait_for(kicked, timeout=10.0)
    assert kicked_frame["status"] == "heartbeat"

    # Keep NOT reading until the walk has settled, so the second node's live
    # frame really overflows the single slot while nobody drains.
    await asyncio.wait_for(walk_done.wait(), timeout=10.0)

    frames = [frame async for frame in aiter]
    node_frames = [frame for frame in frames if frame["status"] == "node_complete"]
    resyncs = [frame for frame in frames if frame["status"] == "resync"]
    assert resyncs, "dropped live frames must be announced, never silent"
    assert resyncs[0]["missed_live_frames"] >= 1
    assert resyncs[0]["recover"] == "GET /v1/dag-runs/run-overflow"
    # Exactly one terminal state per node, and both nodes converge.
    assert sorted(frame["node_id"] for frame in node_frames) == ["n1", "n2"]
    assert {frame["node_id"]: frame["response"] for frame in node_frames} == {
        "n1": "out-n1",
        "n2": "out-n2",
    }
    assert frames[-1]["status"] == "completed"


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
@pytest.mark.asyncio
async def test_abandoning_a_live_stream_cancels_the_in_flight_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A consumer that goes away mid-Run cancels the in-flight Run.

    The #355 semantics awaiting execution inline always had, preserved
    through the live pump: cancelling the consuming task (what a socket
    disconnect does to the response handler) reaches the node's LLM call.
    """
    import asyncio

    from services.legacy_dag_node import _LegacyInputs

    from maistro.graph.nodes.base import NodeContext

    llm_started = asyncio.Event()
    llm_cancelled = asyncio.Event()

    def _gated_builder(on_response: Any = None):
        async def _call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            llm_started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                llm_cancelled.set()
                raise
            return "out"

        return _call

    async def _walk(graph: Any, **kw: Any) -> Any:
        node = kw["node_resolver"]("n1", graph)
        ctx = NodeContext(run_id="run-cancel", dag_id="d", node_id="n1")
        await node.run(_LegacyInputs(), ctx)
        raise AssertionError("walk should have been cancelled inside the node")

    async def on_event(event: dict[str, Any]) -> int | None:
        return 1

    _stub_canonical_walk(monkeypatch, _gated_builder, _walk)

    stream = gr_mod().execute_dag_streaming(
        _live_dag(),
        scope=_execution_scope(),
        execution_mode="interactive",
        on_event=on_event,
        keepalive_interval=60,
    )
    consumer, _frames = _collect(stream)
    try:
        await asyncio.wait_for(llm_started.wait(), timeout=10.0)
        consumer.cancel()
        with contextlib.suppress(asyncio.CancelledError, RuntimeError):
            await asyncio.wait_for(consumer, timeout=10.0)
        await asyncio.wait_for(llm_cancelled.wait(), timeout=10.0)
    finally:
        if not consumer.done():
            consumer.cancel()


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize("status", ["failed", "cancelled", "timed_out"])
async def test_failed_stream_diagnostics_stay_private(monkeypatch, live, status):
    import services.graph_runner as gr

    secret = "postgres://operator:private-password@internal-db/private/path"
    raw = {
        "run_id": "private-run",
        "status": status,
        "error": secret,
        "node_results": {
            "failed-node": {"role": "worker", "success": False, "response": secret},
            "good-node": {"role": "worker", "success": True, "response": "legitimate output"},
        },
    }
    recorded_events, recorded_results = [], []

    async def execute(*args, on_event=None, **kwargs):
        if on_event:
            await on_event(
                {
                    "kind": "node_failed",
                    "run_id": "private-run",
                    "node_id": "failed-node",
                    "response": secret,
                }
            )
        raise gr.CanonicalDagExecutionError(raw)

    async def record_event(event):
        recorded_events.append(event)
        return len(recorded_events)

    async def record_result(result):
        recorded_results.append(result)

    monkeypatch.setattr(gr, "execute_dag", execute)
    frames = [
        frame
        async for frame in gr.execute_dag_streaming(
            {"nodes": []},
            on_result=record_result,
            on_event=record_event if live else None,
        )
    ]
    assert secret not in str((frames, recorded_events, recorded_results))
    assert frames[-1] == {
        "status": status,
        "run_id": "private-run",
        "error": "DAG execution failed; see server logs",
    }
    assert any(frame.get("response") == "legitimate output" for frame in frames)
    if live:
        assert next(frame for frame in frames if frame.get("node_id") == "failed-node")["seq"] == 1
    assert recorded_results[0]["status"] == status
    assert recorded_results[0]["run_id"] == "private-run"
    assert raw["error"] == secret
    assert raw["node_results"]["failed-node"]["response"] == secret
