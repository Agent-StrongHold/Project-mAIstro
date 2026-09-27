"""Workspace DAG model calls land on the canonical quota ledger (#718).

The reachable `POST /v1/dags/{id}/run` path used to execute its LLM nodes
through the raw `_build_llm_call` httpx POST — no canonical Invocation and no
quota evidence, so per-provider rows could present as complete while a whole
production call class was invisible. After the cutover, a DAG node's physical
model call crosses the governed Binding -> Invocation egress whenever the
bridge Container composes, and the Invocation authority's single
terminalization recorder owns the ledger entry.

These tests drive a real governed DAG execution through `execute_dag` — a real
effect context, real durable Graph execution, a fake gateway — and observe the
quota ledger move, the missing-usage case surface as unreported evidence, and
the legacy builder stay a fallback that records nothing.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, ClassVar

import httpx
import pytest
from services.dag_execution_scope import DagExecutionScope

# The DAG node's env default model; pinned explicitly on the node below.
_NODE_MODEL = "test-dag-model"


def _dag() -> dict[str, Any]:
    return {
        "id": "governed-quota-dag",
        "name": "governed-quota-dag",
        "description": "one governed model call",
        "nodes": [
            {
                "id": "n1",
                "role": "worker",
                "name": "n1",
                "prompt": "do governed work",
                "model": _NODE_MODEL,
                "config": {"execution_tier": "safe"},
            }
        ],
        "edges": [],
        "entry_node": "n1",
    }


class _FakeGatewayResponse:
    def __init__(self, body: dict[str, Any]) -> None:
        self.status_code = 200
        self._body = body

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeGatewayClient:
    """Stand-in for `httpx.AsyncClient` answering one canned gateway body."""

    seen: ClassVar[list[dict[str, Any]]] = []
    response_body: ClassVar[dict[str, Any]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    @property
    def is_closed(self) -> bool:
        return False

    async def aclose(self) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> _FakeGatewayResponse:
        cls = type(self)
        cls.seen.append({"url": url, **kwargs})
        return _FakeGatewayResponse(dict(cls.response_body))


class _UnknownModelRegistry:
    """No registry metadata: the gateway provider still resolves by alias."""

    async def get_model(self, name: str) -> Any:
        from maistro.providers.errors import ModelNotFoundError

        raise ModelNotFoundError(name)


class _RecordingTracker:
    """Spy on exactly what the canonical recorder charged the tracker."""

    def __init__(self) -> None:
        self.invocations: list[dict[str, Any]] = []

    async def record_invocation(
        self,
        invocation_id: str,
        provider: str,
        billing_cycle: str,
        input_tokens: int,
        output_tokens: int,
        usage_reported: bool,
    ) -> dict[str, Any]:
        self.invocations.append(
            {
                "invocation_id": invocation_id,
                "provider": provider,
                "billing_cycle": billing_cycle,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "usage_reported": usage_reported,
            }
        )
        return {"provider": provider}


def _gateway_body(*, usage: dict[str, int] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": _NODE_MODEL,
        "choices": [{"message": {"role": "assistant", "content": '{"done": true}'}}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


@pytest.fixture
def governed_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://gateway.test")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "test-gateway-key")


def _install_container(monkeypatch: pytest.MonkeyPatch, tracker: _RecordingTracker) -> Any:
    """Wire `canonical_dag_runner._container` to a Container stand-in.

    Returns (container, usage_log, invocation_store): the same authorities the
    node's governed runtime will compose with, so assertions read the ledger
    the production seam writes.
    """
    import services.canonical_dag_runner as runner

    from maistro.capabilities.effect_context import new_effect_context
    from maistro.quota.usage_log import InMemoryUsageLog

    usage_log = InMemoryUsageLog()
    effects = new_effect_context(usage_log=usage_log, quota_tracker=tracker)
    container = SimpleNamespace(
        capability_effects=effects,
        provider_registry=_UnknownModelRegistry(),
        llm_router=SimpleNamespace(),
        run_store=None,
    )
    monkeypatch.setattr(runner, "_container", lambda: container)
    return container, usage_log, effects.invocation_store


def _scope() -> DagExecutionScope:
    return DagExecutionScope(workspace_id="ws-quota", project_id="proj-quota", user_id="quota-user")


@pytest.mark.asyncio
async def test_dag_node_model_call_records_invocation_quota_evidence(
    monkeypatch: pytest.MonkeyPatch, governed_env: None
) -> None:
    """A governed DAG model call moves the quota ledger with full identity.

    The node executes with NO raw llm_builder at all: the only way it can
    succeed is through the canonical governed egress, which is the point —
    the physical call must be un-reachable except through the Invocation
    authority that records it.
    """
    from services.canonical_dag_runner import execute_dag

    tracker = _RecordingTracker()
    _container, usage_log, _invocation_store = _install_container(monkeypatch, tracker)
    _FakeGatewayClient.response_body = _gateway_body(
        usage={"prompt_tokens": 13, "completion_tokens": 7}
    )
    _FakeGatewayClient.seen = []

    with pytest.MonkeyPatch.context() as http_patch:
        http_patch.setattr(httpx, "AsyncClient", _FakeGatewayClient)
        result = await execute_dag(_dag(), scope=_scope())

    assert result["status"] == "completed", result
    node = result["node_results"]["n1"]
    assert node["success"] is True
    assert node["response"] == '{"done": true}'

    # The physical call crossed the one governed gateway seam.
    assert len(_FakeGatewayClient.seen) == 1
    served = _FakeGatewayClient.seen[0]
    assert served["url"].endswith("/chat/completions")
    assert served["json"]["model"] == _NODE_MODEL

    # Usage ledger: provider-attributed, invocation-linked, reported.
    assert usage_log.scope_keys() == (_NODE_MODEL,)
    (event,) = usage_log.events_for(_NODE_MODEL)
    assert event.usage_reported is True
    assert event.input_tokens == 13
    assert event.output_tokens == 7
    assert event.invocation_id

    # The spy tracker saw the recorder's at-most-once charge for the
    # canonical Invocation identity — the same one the usage log carries.
    assert len(tracker.invocations) == 1
    charge = tracker.invocations[0]
    assert charge["provider"] == _NODE_MODEL
    assert charge["usage_reported"] is True
    assert (charge["input_tokens"], charge["output_tokens"]) == (13, 7)
    assert charge["invocation_id"] == event.invocation_id


@pytest.mark.asyncio
async def test_dag_node_without_provider_usage_records_unreported_evidence(
    monkeypatch: pytest.MonkeyPatch, governed_env: None
) -> None:
    """A gateway that omits usage yields an unreported marker, not a zero.

    The ledger entry must say the evidence is missing (usage_reported=False,
    unreported_count) so quota percentages cannot silently present a call
    that never reported as free.
    """
    from services.canonical_dag_runner import execute_dag

    tracker = _RecordingTracker()
    _container, usage_log, _store = _install_container(monkeypatch, tracker)
    _FakeGatewayClient.response_body = _gateway_body(usage=None)
    _FakeGatewayClient.seen = []

    with pytest.MonkeyPatch.context() as http_patch:
        http_patch.setattr(httpx, "AsyncClient", _FakeGatewayClient)
        result = await execute_dag(_dag(), scope=_scope())

    assert result["status"] == "completed", result
    (event,) = usage_log.events_for(_NODE_MODEL)
    assert event.usage_reported is False
    assert (event.input_tokens, event.output_tokens) == (0, 0)

    assert len(tracker.invocations) == 1
    charge = tracker.invocations[0]
    assert charge["usage_reported"] is False
    assert charge["invocation_id"] == event.invocation_id


@pytest.mark.asyncio
async def test_dag_node_without_effect_authority_falls_back_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No canonical authority: the compatibility builder runs, ledger silent.

    The fallback exists for standalone execution and direct construction, and
    it must be visible as exactly that: the call happens through the injected
    builder, and no Invocation or quota evidence is manufactured for it.
    """
    import services.canonical_dag_runner as runner
    from services.canonical_dag_runner import execute_dag

    def _fake_builder(on_response: Any = None):
        async def call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
            return "ok:legacy"

        return call

    monkeypatch.setattr(runner, "_container", lambda: None)
    _FakeGatewayClient.seen = []

    with pytest.MonkeyPatch.context() as http_patch:
        http_patch.setattr(httpx, "AsyncClient", _FakeGatewayClient)
        result = await execute_dag(_dag(), scope=_scope(), llm_builder=_fake_builder)

    assert result["status"] == "completed", result
    assert result["node_results"]["n1"]["response"] == "ok:legacy"
    # The legacy path is the visible compatibility seam: no governed gateway
    # call happened, and the injected builder served the node instead.
    assert _FakeGatewayClient.seen == []
