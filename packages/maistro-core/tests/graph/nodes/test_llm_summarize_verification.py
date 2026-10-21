"""Verification-aware contracts of `llm.summarize` (epic M4-I).

The node is the production wiring for two M4-I primitives: observation
modality routing at the governed model egress (text vs image alias selection
plus content-part encoding) and the quality self-report the executor's
escalation ladder supervises. These tests pin the production behavior —
the policy modules they consume are unit-tested under
``tests/graph/verification/``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.graph.nodes import NodeContext
from maistro.graph.nodes.llm_summarize import LlmSummarizeNode
from maistro.graph.verification.escalation import (
    ESCALATED_MODEL_CONTEXT_KEY,
    LADDER_START_CONTEXT_KEY,
    QUALITY_METADATA_KEY,
)
from maistro.graph.verification.quality import summarize_quality
from maistro.providers.registry import InMemoryProviderRegistry
from maistro.providers.router import CostAwareRouter
from maistro.providers.types import ModelMetadata


def _llm_node(*, effect_context: CapabilityEffectContext) -> LlmSummarizeNode:
    registry = InMemoryProviderRegistry(
        models=[
            ModelMetadata(
                name="gemini-3.1-flash-lite",
                provider="test-gateway",
                cost_per_1k_input=0.1,
                cost_per_1k_output=0.2,
                latency_p50_ms=100,
            ),
            ModelMetadata(
                name="vision-pro",
                provider="test-gateway",
                cost_per_1k_input=0.5,
                cost_per_1k_output=1.0,
                latency_p50_ms=200,
            ),
        ]
    )
    return LlmSummarizeNode(
        registry=registry, router=CostAwareRouter(registry), effect_context=effect_context
    )


def _ctx(**overrides: Any) -> NodeContext:
    base: dict[str, Any] = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "n1",
        "user_id": "u1",
        "project_id": "p1",
        "workspace_id": "w1",
        "node_run_id": "nr1",
        "attempt_id": "a1",
    }
    base.update(overrides)
    return NodeContext(**base)


@pytest.fixture
async def llm_env() -> tuple[LlmSummarizeNode, str]:
    """A fresh governed context, the node wired to it, and the model.chat
    Binding llm.summarize resolves (#56).

    One fresh ``CapabilityEffectContext`` per test, not the process-wide
    default: the governed egress dedupes on ``(run_id, binding_id,
    effect_key)`` and a completed Invocation is replayed without another
    provider call, so tests sharing one context (and one run_id) would
    silently replay each other's completions instead of exercising their
    own request shape.
    """

    from maistro.capabilities.binding import Binding
    from maistro.capabilities.effect_context import (
        binding_scope_policy,
        new_in_memory_effect_context,
    )
    from maistro.capabilities.providers.llm_gateway import (
        DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
        MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    )
    from maistro.credentials.types import CredentialRecord

    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            created_at=datetime(2026, 10, 1, tzinfo=UTC),
            binding_id="llm-summarize-verification-binding",
            workspace_id="w1",
            project_id="p1",
            capability="model.chat",
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        )
    )
    effects.credentials.add(
        workspace_id="w1",
        project_id="p1",
        record=CredentialRecord(
            key_id=DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
            provider=MODEL_GATEWAY_CREDENTIAL_PROVIDER,
            api_key="test-litellm-key",
        ),
    )
    return _llm_node(effect_context=effects), "llm-summarize-verification-binding"


def _fake_gateway(
    monkeypatch: pytest.MonkeyPatch,
    seen: dict[str, Any],
    *,
    summary: str = "- shipped the migration",
) -> None:
    """Patch the shared client to record the request body and answer once."""

    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return {
                "model": "answered",
                "choices": [{"message": {"content": summary}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            }

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def post(self, url: str, *, json: Any = None, headers: Any = None) -> _Resp:
            seen["url"] = url
            seen["body"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_completion_self_reports_quality_metadata(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """Every completion carries the deterministic quality the ladder reads."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen, summary="- shipped the migration")

    source = (
        "The payments migration shipped after a two-week canary and latency "
        "improved forty percent, but refunds still queue asynchronously."
    )
    out = await llm_node.run(
        {"text": source, "binding_id": llm_binding_id},
        _ctx(),
    )
    assert out.success
    assert out.metadata[QUALITY_METADATA_KEY] == summarize_quality(source, out.output.summary)


async def test_escalated_rung_outranks_the_default_alias(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """A supervision-chosen rung replaces the node's default model alias."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    ctx = _ctx(metadata={ESCALATED_MODEL_CONTEXT_KEY: "vision-pro"})
    out = await llm_node.run({"text": "activity", "binding_id": llm_binding_id}, ctx)
    assert out.success
    assert seen["body"]["model"] == "vision-pro"


async def test_seeded_ladder_start_runs_cheapest_rung_on_the_first_visit(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """The executor-seeded ladder start, not the ambient default, runs first.

    Review-finding regression: on the first visit there used to be no
    ``escalated_model``, so the node ran ``inputs.model`` — which could be a
    more expensive or unlisted model — while the fold still escalated as if
    the cheapest rung had run. The seeded start makes cheap-first hold by
    construction; a conflicting ``inputs.model`` simply loses.
    """
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    ctx = _ctx(metadata={LADDER_START_CONTEXT_KEY: "gemini-3.1-flash-lite"})
    out = await llm_node.run(
        {"text": "activity", "model": "pro", "binding_id": llm_binding_id},
        ctx,
    )
    assert out.success
    assert seen["body"]["model"] == "gemini-3.1-flash-lite"


async def test_seeded_ladder_start_yields_to_the_vision_alias(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """The seeded start is the ladder's beginning, not a supervision order:
    an image observation's vision alias still governs the first visit."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    ctx = _ctx(metadata={LADDER_START_CONTEXT_KEY: "gemini-3.1-flash-lite"})
    out = await llm_node.run(
        {
            "observations": ["data:image/png;base64,QUJDREVG"],
            "image_model": "vision-pro",
            "model": "pro",
            "binding_id": llm_binding_id,
        },
        ctx,
    )
    assert out.success
    assert seen["body"]["model"] == "vision-pro"


async def test_text_observations_encode_as_text_parts(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """Text observations ride as text content parts; the alias is unchanged."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    out = await llm_node.run(
        {
            "text": "frame these",
            "observations": ["JIRA-101 moved to Done", {"field": "status", "value": "green"}],
            "binding_id": llm_binding_id,
        },
        _ctx(),
    )
    assert out.success
    user = seen["body"]["messages"][1]["content"]
    assert isinstance(user, list)
    assert {"type": "text", "text": "JIRA-101 moved to Done"} in user
    assert {"type": "text", "text": "frame these"} in user
    # No image observation: the node's own default alias stays in charge.
    assert seen["body"]["model"] == "gemini-3.1-flash-lite"


async def test_text_observations_route_to_the_configured_text_alias(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """When all observations are textual, the configured text alias governs
    the request; falling back to ``model`` would make ``text_model`` dead
    configuration."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    out = await llm_node.run(
        {
            "text": "frame these",
            "observations": ["JIRA-101 moved to Done"],
            "text_model": "vision-pro",
            "binding_id": llm_binding_id,
        },
        _ctx(),
    )
    assert out.success
    assert seen["body"]["model"] == "vision-pro"


async def test_image_observation_routes_to_the_vision_alias(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """An image observation lifts the request to the configured vision alias
    and encodes as an image content part, never as lossy text."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    screenshot = "data:image/png;base64,QUJDREVG"
    out = await llm_node.run(
        {
            "text": "what changed in this screenshot?",
            "observations": [screenshot, "companion text payload"],
            "image_model": "vision-pro",
            "binding_id": llm_binding_id,
        },
        _ctx(),
    )
    assert out.success
    assert seen["body"]["model"] == "vision-pro"
    user = seen["body"]["messages"][1]["content"]
    assert {"type": "image_url", "image_url": {"url": screenshot}} in user
    assert {"type": "text", "text": "companion text payload"} in user
    assert {"type": "text", "text": "what changed in this screenshot?"} in user


async def test_image_observation_without_vision_alias_refuses_loudly(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """No configured vision alias is a visible failure, not a lossy re-encode."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    out = await llm_node.run(
        {"observations": ["data:image/png;base64,QUJDREVG"], "binding_id": llm_binding_id},
        _ctx(),
    )
    assert out.success is False
    assert out.error_code == "RuntimeError"
    assert "image_model" in (out.error_message or "")
    # The refusal happened before any model call crossed the egress.
    assert "body" not in seen


async def test_escalated_rung_outranks_the_modality_floor(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """Supervision's rung wins over the vision alias when both apply — the
    ladder is declared by the graph author who knows the modalities."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    _fake_gateway(monkeypatch, seen)

    ctx = _ctx(metadata={ESCALATED_MODEL_CONTEXT_KEY: "vision-ultra"})
    out = await llm_node.run(
        {
            "observations": ["data:image/png;base64,QUJDREVG"],
            "image_model": "vision-pro",
            "binding_id": llm_binding_id,
        },
        ctx,
    )
    assert out.success
    assert seen["body"]["model"] == "vision-ultra"


async def test_quality_is_measured_against_text_observations_too(
    monkeypatch: pytest.MonkeyPatch,
    llm_env: tuple[LlmSummarizeNode, str],
) -> None:
    """A summary cannot score well by ignoring the observation payloads it
    was handed: the observation text counts as source for the quality score."""
    llm_node, llm_binding_id = llm_env
    monkeypatch.setenv("MAISTRO_LLM_BASE_URL", "http://fake-litellm:4000")
    monkeypatch.setenv("MAISTRO_LLM_API_KEY", "fake-key")
    seen: dict[str, Any] = {}
    salient_source = "payments migration canary latency dashboard " + ("filler text " * 20)
    _fake_gateway(monkeypatch, seen, summary="stuff happened somehow")

    out = await llm_node.run(
        {"observations": [salient_source], "binding_id": llm_binding_id},
        _ctx(),
    )
    assert out.success
    assert out.metadata[QUALITY_METADATA_KEY] == summarize_quality(
        salient_source.strip(), "stuff happened somehow"
    )
    # And the salient-dropping summary is exactly the kind of shortfall a
    # declared ladder withholds.
    assert out.metadata[QUALITY_METADATA_KEY] <= 0.5
