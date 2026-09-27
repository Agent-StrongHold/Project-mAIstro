"""One governed image egress: Binding -> Invocation -> approved Provider (#286).

Mirrors :mod:`maistro.capabilities.model_chat`. This module owns no HTTP: the
Binding is checked for the ``image.generate`` capability, policy and
credential routing run inside the canonical Invocation service, and only then
does :func:`execute_image_generation` post to the gateway. A Binding pin
selects the image model; otherwise the request must name one, and an
unselected model is unavailable rather than guessed.
"""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingDisabled, BindingScopeDenied
from maistro.capabilities.credential_routing import CredentialBackedProvider
from maistro.capabilities.invocation import Invocation
from maistro.capabilities.providers.image_gateway import (
    IMAGE_GENERATE_CAPABILITY,
    ImageGenerationRequest,
    LlmGatewayImageProvider,
    execute_image_generation,
)
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.capabilities.types import Unavailable

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext


class ImageGenerationResult(BaseModel):
    """Governed image outcome plus the Invocation that records it."""

    model_config = ConfigDict(extra="forbid")

    invocation_id: str
    model: str
    images: list[bytes]


def _require_image_binding(binding: Binding) -> None:
    if binding.capability != IMAGE_GENERATE_CAPABILITY:
        raise BindingScopeDenied(
            f"Binding {binding.binding_id!r} authorizes Capability {binding.capability!r}, "
            f"not {IMAGE_GENERATE_CAPABILITY!r}"
        )
    if binding.disabled:
        raise BindingDisabled(
            f"Binding {binding.binding_id!r} is disabled and cannot authorize effects"
        )


def _result(invocation: Invocation) -> ImageGenerationResult:
    body = invocation.result if isinstance(invocation.result, dict) else {}
    items = body.get("images")
    images = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    return ImageGenerationResult(
        invocation_id=invocation.invocation_id,
        model=invocation.binding.provider_name,
        images=[base64.b64decode(str(item["b64_json"])) for item in images],
    )


class ImageGenerationEgress:
    """Cross the one governed image-generation boundary for an effect consumer."""

    def __init__(self, effects: CapabilityEffectContext, *, endpoint: GatewayEndpoint) -> None:
        self._effects = effects
        self._endpoint = endpoint

    async def generate(
        self,
        *,
        binding: Binding,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        effect_key: str,
        request: ImageGenerationRequest,
    ) -> ImageGenerationResult:
        """Run one governed image generation and return the decoded images."""

        _require_image_binding(binding)

        async def resolve(candidate: Binding) -> ResolvedCapabilityProvider | Unavailable:
            model = candidate.provider_name or request.model
            if not model:
                return Unavailable(
                    slot=IMAGE_GENERATE_CAPABILITY,
                    reason="neither the Binding nor the request selects an image model",
                )
            return LlmGatewayImageProvider(model=model)

        async def execute(provider: ResolvedCapabilityProvider, payload: Any) -> Any:
            if not isinstance(provider, CredentialBackedProvider):
                raise TypeError("image physical execution requires a Binding-scoped credential")
            endpoint = self._endpoint.model_copy(update={"api_key": provider.credential.api_key})
            return await execute_image_generation(provider.base, payload, endpoint=endpoint)

        routing = self._effects.credential_routing()
        invocation = await self._effects.invocations.invoke(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key,
            request=request,
            resolver=routing.resolver(resolve),
            executor=routing.executor(execute),
        )
        return _result(invocation)


__all__ = [
    "IMAGE_GENERATE_CAPABILITY",
    "ImageGenerationEgress",
    "ImageGenerationRequest",
    "ImageGenerationResult",
]
