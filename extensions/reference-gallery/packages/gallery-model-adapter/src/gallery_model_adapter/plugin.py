"""The gallery model adapter's entrypoint module (capability-provider family, #980).

This is the provider-adapter family member (#980), written against the
third-party provider adapter SDK contract (ADR-104): an out-of-tree package
declares its models, auth style, and error taxonomy as **plain data**, and
implements the normalization hooks as **pure functions**. The host validates
the spec through the SDK's registration conformance and registers it through
``register_adapter_models`` — the one registration seam. The adapter never
owns a transport, never holds a credential (the spec has no field that could
carry one), and never classifies outside the canonical error taxonomy.

The data/functions here are shaped so a host can wrap them in the SDK's
``ProviderAdapter`` protocol without this module importing a single
product type.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

#: Error-kind constants, mirrored from the SDK's ``AdapterErrorKind``. String
#: constants on purpose: the adapter stays dependency-free and the taxonomy
#: comparison stays a string equality either side of the seam.
AUTH = "auth"
RATE_LIMITED = "rate_limited"
RETRYABLE = "retryable"
PERMANENT = "permanent"

#: The adapter's declarative spec, exactly the fields
#: ``ProviderAdapterSpec`` (``extra="forbid"``) accepts. No secret-shaped key
#: exists in it and none may be added: credential material is resolved per
#: call by the host's scoped credential pool, and the spec only declares
#: *how* the resolved secret is presented (``auth_style``).
SPEC: dict[str, object] = {
    "adapter_id": "gallery-model-adapter",
    "display_name": "Gallery model adapter (reference)",
    "base_url": "https://gallery-provider.invalid/v1",
    "protocol": "openai-chat-completions",
    "auth_style": "bearer",
    "credential_provider": "gallery-provider",
    "credential_ref": "gallery-provider-key",
    "timeout_s": 30.0,
    "capabilities": {"streaming": False, "tools": True, "structured_output": False},
    "models": [
        {
            "name": "gallery-chat-fast",
            "cost_per_1k_input": 0.1,
            "cost_per_1k_output": 0.4,
            "latency_p50_ms": 600,
            "tier": "fast",
            "capabilities": {"tools": True},
        },
        {
            "name": "gallery-chat-balanced",
            "cost_per_1k_input": 0.5,
            "cost_per_1k_output": 1.5,
            "latency_p50_ms": 1200,
            "tier": "balanced",
        },
    ],
    "health_path": "/health",
}

#: The object the manifest's entry point names.
PLUGIN: dict[str, object] = {
    "kind": "capability-provider",
    "name": "gallery.model_adapter",
    "version": "1.0.0",
    "capabilities": ["network.outbound"],
    "spec": SPEC,
    "handlers": [
        "normalize_request",
        "normalize_response",
        "usage_from",
        "error_kind_for",
        "health_from",
    ],
}


def normalize_request(model: str, request: Any) -> dict[str, object]:
    """Canonical chat request -> this provider's JSON payload.

    ``request`` is the host's canonical request value (attributes ``model``,
    ``messages``, ``temperature``, ``max_tokens``, ``tools``,
    ``tool_choice``, ``response_format``). ``None`` sampling fields stay
    absent, preserving callers that intentionally leave sampling to the
    provider. Pure: the payload is data, the transport is the host's.
    """
    payload: dict[str, object] = {
        "model": model,
        "messages": [dict(message) for message in request.messages],
        "stream": False,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_tokens is not None:
        payload["max_tokens"] = request.max_tokens
    if request.tools:
        payload["tools"] = [dict(tool) for tool in request.tools]
    if request.tool_choice:
        payload["tool_choice"] = request.tool_choice
    if request.response_format is not None:
        payload["response_format"] = dict(request.response_format)
    return payload


def normalize_response(payload: Mapping[str, object]) -> dict[str, object]:
    """Provider response body -> the canonical chat-completions body.

    The upstream speaks the canonical shape already, so normalization is a
    copy — the honest behavior for an OpenAI-compatible provider, and the
    same shape the built-in reference adapter normalizes to.
    """
    return dict(payload)


def usage_from(payload: Mapping[str, object]) -> tuple[int, int] | None:
    """(input_tokens, output_tokens) the provider reported, or ``None``."""
    usage = payload.get("usage")
    if not isinstance(usage, Mapping):
        return None
    try:
        return (
            int(usage.get("prompt_tokens", 0) or 0),
            int(usage.get("completion_tokens", 0) or 0),
        )
    except (TypeError, ValueError):
        return None


def error_kind_for(status: int) -> str:
    """Map one HTTP status into the canonical error taxonomy.

    Pinned to the classification the platform's resilience layer infers from
    the same status: 401/403 auth, 429 rate-limited, 5xx retryable, other
    4xx permanent. An adapter that contradicted the canonical reading of a
    status would be refused at registration.
    """
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMITED
    if status >= 500:
        return RETRYABLE
    return PERMANENT


def health_from(payload: Mapping[str, object]) -> bool:
    """Whether an (unauthenticated, by declaration) health probe reports healthy."""
    return payload.get("status") in (None, "ok", "healthy")


#: Exported for hosts that enumerate what an entry point object offers.
HANDLERS: dict[str, Callable[..., object]] = {
    "normalize_request": normalize_request,
    "normalize_response": normalize_response,
    "usage_from": usage_from,
    "error_kind_for": error_kind_for,
    "health_from": health_from,
}
