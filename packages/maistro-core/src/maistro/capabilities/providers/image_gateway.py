"""The approved Provider implementation for governed image generation (#286).

Sibling of :mod:`maistro.capabilities.providers.llm_gateway`: the same
OpenAI-compatible gateway and credential pool, but the ``images/generations``
endpoint with ``response_format=b64_json``. Authorization is the resolved
Binding and lifecycle is the canonical Invocation; this module owns only the
HTTP protocol.

Image generation changes no external state beyond producing the returned
bytes, so a gateway error status or a response carrying no decodable image
means the effect was not applied: :class:`ImageGenerationError` is an
:class:`EffectNotApplied`, which terminalizes the Invocation as ``FAILED``
(retryable under a later Attempt) instead of recording an empty success.
"""

from __future__ import annotations

import base64
import binascii

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.binding import ResolvedCapabilityProvider
from maistro.capabilities.invocation import EffectNotApplied
from maistro.capabilities.providers.llm_gateway import (
    MODEL_GATEWAY_CREDENTIAL_PROVIDER,
    GatewayEndpoint,
)
from maistro.http import shared_client

#: The canonical capability every governed image generation requests.
IMAGE_GENERATE_CAPABILITY = "image.generate"

_GATEWAY_TRUST_TIER = "t1"


class ImageGenerationError(EffectNotApplied):
    """The gateway produced no image; ``status_code`` feeds credential rotation."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class LlmGatewayImageProvider:
    """Resolved Provider handle for one ``image.generate`` call.

    ``name`` is the image model the call uses; ``credential_provider`` is the
    gateway pool, exactly as for ``model.chat``.
    """

    def __init__(self, *, model: str) -> None:
        self._model = model

    @property
    def name(self) -> str:
        return self._model

    @property
    def slot(self) -> str:
        return IMAGE_GENERATE_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return _GATEWAY_TRUST_TIER

    @property
    def credential_provider(self) -> str:
        return MODEL_GATEWAY_CREDENTIAL_PROVIDER


class ImageGenerationRequest(BaseModel):
    """Provider-neutral image request crossing the Invocation boundary."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1)
    model: str = ""
    size: str = "1024x1024"
    n: int = Field(default=1, ge=1, le=10)
    quality: str | None = None


def _images_url(endpoint: GatewayEndpoint) -> str:
    base = endpoint.base_url.rstrip("/")
    base = base if base.endswith("/v1") else base + "/v1"
    return f"{base}/images/generations"


def _payload(
    provider: LlmGatewayImageProvider, request: ImageGenerationRequest
) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": provider.name,
        "prompt": request.prompt,
        "n": request.n,
        "size": request.size,
        "response_format": "b64_json",
    }
    if request.quality is not None:
        payload["quality"] = request.quality
    return payload


def _checked_images(response: httpx.Response) -> dict[str, object]:
    """Return the persisted result shape, or refuse an image-less response."""

    if response.status_code >= 400:
        raise ImageGenerationError(
            f"image_http_error status={response.status_code}", status_code=response.status_code
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise ImageGenerationError("image gateway returned a non-JSON body") from exc
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list) or not data:
        raise ImageGenerationError("image gateway returned no images")
    images: list[dict[str, str]] = []
    for item in data:
        encoded = item.get("b64_json") if isinstance(item, dict) else None
        if not isinstance(encoded, str) or not encoded:
            raise ImageGenerationError("image gateway returned an image without b64_json")
        try:
            base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageGenerationError("image gateway returned invalid base64") from exc
        revised = item.get("revised_prompt")
        images.append(
            {"b64_json": encoded, "revised_prompt": revised if isinstance(revised, str) else ""}
        )
    return {"images": images}


async def execute_image_generation(
    provider: ResolvedCapabilityProvider,
    request: object,
    *,
    endpoint: GatewayEndpoint,
) -> dict[str, object]:
    """Perform the one governed image HTTP call and return the persisted result."""

    if not isinstance(provider, LlmGatewayImageProvider):
        raise TypeError(f"image Invocation resolved a non-gateway provider: {provider!r}")
    if not isinstance(request, ImageGenerationRequest):
        raise TypeError(f"image Invocation received a foreign request: {type(request)!r}")

    try:
        async with shared_client(timeout=endpoint.timeout_s) as client:
            response = await client.post(
                _images_url(endpoint),
                headers=endpoint.authorization_header(),
                json=_payload(provider, request),
            )
    except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
        raise ImageGenerationError(f"image gateway unreachable, no effect occurred: {exc}") from exc
    return _checked_images(response)


__all__ = [
    "IMAGE_GENERATE_CAPABILITY",
    "ImageGenerationError",
    "ImageGenerationRequest",
    "LlmGatewayImageProvider",
    "execute_image_generation",
]
