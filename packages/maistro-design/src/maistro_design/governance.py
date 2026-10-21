"""One governed model seam for design explore/judge graph nodes (#987).

Every model call a design pack node makes crosses the canonical
Capability -> Provider -> Binding -> Invocation boundary
(ADR-081226-6b46) through :class:`maistro.capabilities.model_chat.ModelChatEgress`.
Nothing in this package opens an HTTP client or a provider SDK itself — the
architecture-fitness gate (``scripts/check-design-model-egress.py`` and the
in-repo test of the same name) fails any module that tries.

Responsibilities collected here so the explore and judge nodes cannot drift
into two different ideas of "authorized":

- resolving a Workspace/Project/node-scoped ``model.chat`` Binding, failing
  closed when none exists;
- reading the deployment's gateway endpoint from the environment (never from
  a Graph definition, so saved packs stay portable);
- Warden-scanning every inbound model payload before it may become a thesis
  or an eval record;
- extracting the strict JSON payload the pack prompts demand.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY, ModelChatEgress
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.graph.nodes.base import NodeContext
from maistro.security.warden.detector import Warden
from maistro_design.types import TrustBannedError

#: The capability a design explore/judge Binding authorizes. Design does not
#: mint its own capability namespace: model inference is one canonical
#: Capability with one Provider family, and Binding scope (workspace / project
#: / node_id) is what narrows it to the explore or judge caller.
DESIGN_MODEL_CAPABILITY = MODEL_CHAT_CAPABILITY

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")

#: Boundaries Warden is documented for (user_input / tool_result). A thesis or
#: a judge rationale is a tool result: untrusted content produced by a model.
_THESIS_BOUNDARY = "tool_result"


async def resolve_design_binding(
    effects: CapabilityEffectContext,
    *,
    binding_id: str,
    ctx: NodeContext,
) -> Binding:
    """Resolve the node's pre-authorized ``model.chat`` Binding, failing closed.

    An empty id, an unregistered id, a disabled Binding, or a Binding scoped to
    another Workspace/Project/node/capability all refuse here — before any
    prompt is assembled and before any thesis or eval record could exist. A
    caller that gets past this function has an authorized route; one that does
    not gets an exception, never a canned payload shaped like success.
    """

    if not binding_id.strip():
        raise BindingNotFound(
            "design explore/judge requires a pre-authorized model.chat binding_id "
            "before any model call"
        )
    return await effects.bindings.resolve(
        binding_id,
        workspace_id=str(ctx.workspace_id or ""),
        project_id=str(ctx.project_id or ""),
        node_id=ctx.node_id,
        capability=DESIGN_MODEL_CAPABILITY,
    )


def gateway_endpoint_from_env(timeout_s: float) -> GatewayEndpoint:
    """The deployment's LLM gateway endpoint, from the environment only.

    Same configuration surface ``llm.summarize`` reads. Credentials and hosts
    never travel inside a Graph/Node definition, so a saved design pack stays
    portable across environments. A deployment with no gateway configured is a
    hard refusal — not an empty endpoint that would fail obscurely later.
    """

    base_url = (
        os.environ.get("MAISTRO_LLM_BASE_URL")
        or os.environ.get("LITELLM_URL")
        or os.environ.get("LITELLM_API_BASE")
        or ""
    ).rstrip("/")
    api_key = (
        os.environ.get("MAISTRO_LLM_API_KEY")
        or os.environ.get("LITELLM_API_KEY")
        or os.environ.get("LITELLM_MASTER_KEY")
        or ""
    )
    if not base_url:
        raise RuntimeError(
            "design explore/judge: no LLM gateway base URL configured "
            "(MAISTRO_LLM_BASE_URL or LITELLM_API_BASE)"
        )
    return GatewayEndpoint(base_url=base_url, api_key=api_key, timeout_s=timeout_s)


def build_model_egress(
    effects: CapabilityEffectContext,
    *,
    registry: Any,
    router: Any,
    endpoint: GatewayEndpoint,
) -> ModelChatEgress:
    """The one governed egress instance pack nodes call through."""

    return ModelChatEgress(effects, registry=registry, router=router, endpoint=endpoint)


async def scan_model_text(text: str, *, what: str) -> str:
    """Warden-scan inbound model content before it may be accepted.

    A blocked payload raises instead of being trimmed, wrapped, or passed
    through: a hostile model response must never become a thesis payload or an
    eval record, and a recorded failed Attempt is the honest evidence of that
    refusal.
    """

    verdict = await Warden().scan(text, boundary=_THESIS_BOUNDARY)
    if verdict.blocked or not verdict.clean:
        raise TrustBannedError(
            f"{what} failed the Warden scan and was refused: {', '.join(verdict.flags)}"
        )
    return text


def extract_json_payload(raw: str, *, what: str) -> dict[str, Any]:
    """Parse the strict JSON object pack prompts require, fences tolerated.

    Malformed model output raises — a node never substitutes a guessed payload
    for the one it asked for, because a fabricated thesis or score is exactly
    the "sample wave presented as execution" this lane forbids.
    """

    candidate = _FENCE_RE.sub("", raw.strip()).strip()
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{what}: model returned malformed JSON ({exc})") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{what}: model returned JSON that is not an object")
    return parsed


__all__ = [
    "DESIGN_MODEL_CAPABILITY",
    "build_model_egress",
    "extract_json_payload",
    "gateway_endpoint_from_env",
    "resolve_design_binding",
    "scan_model_text",
]
