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

import pathlib
import sys
from typing import Any, ClassVar

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


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
    """A DAG stream against an unconfigured LLM ends in `failed`, not `completed`."""
    from services import graph_runner as gr

    _unconfigure_llm(monkeypatch)
    _set_allow_stub_llm(monkeypatch, False)

    events = [
        ev
        async for ev in gr.execute_dag_streaming(
            {"name": "d", "nodes": [{"id": "n1", "role": "worker"}], "edges": []}
        )
    ]

    statuses = [ev["status"] for ev in events]
    assert "completed" not in statuses
    assert statuses[-1] == "failed"
    assert "ALLOW_STUB_LLM" in events[-1]["error"]


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
        }
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
        }
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


async def test_execute_dag_streaming_yields_full_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.graph_runner as gr

    class _NR:
        node_id = "n1"
        role = "worker"
        selected_candidate = "out"
        success = True

    class _Result:
        total_cycles = 1
        node_results: ClassVar = [_NR()]

    async def _run_graph(**kw: Any) -> Any:
        return _Result()

    import maistro.graph.executor as exec_mod

    monkeypatch.setattr(exec_mod, "run_graph", _run_graph)
    monkeypatch.setattr(gr, "_build_llm_call", lambda *a, **kw: None)

    events = []
    async for ev in gr.execute_dag_streaming(
        {
            "name": "x",
            "nodes": [{"id": "n1", "role": "worker", "name": "W"}],
            "edges": [],
            "entry_node": "n1",
        }
    ):
        events.append(ev)
    statuses = [e["status"] for e in events]
    assert statuses == ["started", "node_complete", "completed"]


async def test_execute_dag_streaming_yields_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.graph_runner as gr

    async def _boom(**kw: Any) -> Any:
        raise RuntimeError("synthetic")

    import maistro.graph.executor as exec_mod

    monkeypatch.setattr(exec_mod, "run_graph", _boom)
    monkeypatch.setattr(gr, "_build_llm_call", lambda *a, **kw: None)

    events = []
    async for ev in gr.execute_dag_streaming(
        {
            "name": "x",
            "nodes": [{"id": "n1", "role": "worker", "name": "W"}],
            "edges": [],
            "entry_node": "n1",
        }
    ):
        events.append(ev)
    assert events[0]["status"] == "started"
    assert events[-1]["status"] == "failed"
    assert "synthetic" in events[-1]["error"]
