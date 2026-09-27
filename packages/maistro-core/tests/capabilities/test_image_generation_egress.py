"""Governed ``image.generate`` egress through the shipped Container (#286).

The Container's own canonical effect context carries the Binding, the
Binding-scoped gateway credential, and the Invocation ledger; only the httpx
transport is faked.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import (
    BindingDisabled,
    BindingNotFound,
    BindingScopeDenied,
)
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.governed_invocation import InvocationDenied
from maistro.capabilities.image_generation import (
    IMAGE_GENERATE_CAPABILITY,
    ImageGenerationEgress,
    ImageGenerationRequest,
)
from maistro.capabilities.invocation import CapabilityUnavailable, InvocationStatus
from maistro.capabilities.providers.image_gateway import (
    ImageGenerationError,
    LlmGatewayImageProvider,
    execute_image_generation,
)
from maistro.capabilities.providers.llm_gateway import (
    DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,
    GatewayEndpoint,
)
from maistro.container import Container, create_container
from maistro.credentials.router import CredentialScopeError
from maistro.http import override_transport
from maistro.policy.types import Decision, PolicyVerdict
from maistro.types.config import AgentConfig, ModelBindingConfig

_PNG = b"\x89PNG\r\n\x1a\nfake-image-bytes"
_ENDPOINT = GatewayEndpoint(base_url="http://gw:4000")


class _Gateway:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body = (
            body
            if body is not None
            else {
                "created": 1,
                "data": [{"b64_json": base64.b64encode(_PNG).decode(), "revised_prompt": "a fox"}],
            }
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if isinstance(self.body, Exception):
            raise self.body
        if isinstance(self.body, bytes):
            return httpx.Response(self.status, content=self.body)
        return httpx.Response(self.status, json=self.body)


@pytest.fixture
def gateway() -> Iterator[_Gateway]:
    fake = _Gateway()
    with override_transport(httpx.MockTransport(fake)):
        yield fake


async def _container() -> Container:
    # The declared chat Binding is what registers the deployment's physical
    # gateway key for ws1/p1; image Bindings authorize the same key id.
    return await create_container(
        AgentConfig(
            router_api_key="router-key",
            litellm_key="sk-gateway",
            workspace_id="ws1",
            model_bindings=[ModelBindingConfig(binding_id="chat-p1", project_id="p1")],
        )
    )


async def _image_binding(
    container: Container, *, binding_id: str = "img-p1", **overrides: Any
) -> Binding:
    values: dict[str, Any] = {
        "binding_id": binding_id,
        "workspace_id": "ws1",
        "project_id": "p1",
        "capability": IMAGE_GENERATE_CAPABILITY,
        "provider_name": "flux-dev",
        "credential_refs": (DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
    }
    values.update(overrides)
    stored = await container.capability_effects.bindings.put(Binding.model_validate(values))
    return await container.capability_effects.bindings.resolve(
        stored.binding_id,
        workspace_id=stored.workspace_id,
        project_id=stored.project_id,
        node_id="illustrate",
        capability=stored.capability,
    )


async def _generate(
    egress: ImageGenerationEgress, binding: Binding, *, effect_key: str = "page-1"
) -> Any:
    return await egress.generate(
        binding=binding,
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="att-1",
        effect_key=effect_key,
        request=ImageGenerationRequest(prompt="a fox in the snow", size="512x512"),
    )


async def test_authorized_call_persists_correlated_invocation_and_returns_bytes(
    gateway: _Gateway,
) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    binding = await _image_binding(container)

    result = await _generate(egress, binding)

    assert result.images == [_PNG]
    assert result.model == "flux-dev"
    (sent,) = gateway.requests
    assert str(sent.url) == "http://gw:4000/v1/images/generations"
    assert sent.headers["authorization"] == "Bearer sk-gateway"
    assert json.loads(sent.content) == {
        "model": "flux-dev",
        "prompt": "a fox in the snow",
        "n": 1,
        "size": "512x512",
        "response_format": "b64_json",
    }

    stored = await container.capability_effects.invocation_store.get(result.invocation_id)
    assert stored is not None
    assert stored.status is InvocationStatus.COMPLETED
    assert (stored.run_id, stored.node_run_id, stored.attempt_id) == ("run-1", "nr-1", "att-1")
    assert stored.binding.capability == IMAGE_GENERATE_CAPABILITY
    assert stored.binding.binding_id == "img-p1"
    assert stored.usage is not None
    assert (stored.usage.units, stored.usage.output_units, stored.usage.model) == (
        "images",
        1,
        "flux-dev",
    )
    assert "sk-gateway" not in stored.model_dump_json()
    history = await container.capability_effects.invocation_store.list_effect(
        run_id="run-1", node_run_id="nr-1", binding_id="img-p1", effect_key="page-1"
    )
    assert [item.invocation_id for item in history] == [result.invocation_id]


async def test_replay_of_same_effect_returns_prior_result_without_second_post(
    gateway: _Gateway,
) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    binding = await _image_binding(container)

    first = await _generate(egress, binding)
    second = await _generate(egress, binding)

    assert len(gateway.requests) == 1
    assert second.invocation_id == first.invocation_id
    assert second.images == [_PNG]


async def test_request_model_is_used_when_binding_does_not_pin(gateway: _Gateway) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    binding = await _image_binding(container, provider_name="")

    result = await egress.generate(
        binding=binding,
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="att-1",
        effect_key="page-1",
        request=ImageGenerationRequest(prompt="a fox", model="sdxl", quality="hd"),
    )

    assert result.model == "sdxl"
    sent = json.loads(gateway.requests[0].content)
    assert (sent["model"], sent["quality"]) == ("sdxl", "hd")


async def test_unselected_model_is_unavailable_before_http(gateway: _Gateway) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    binding = await _image_binding(container, provider_name="")

    with pytest.raises(CapabilityUnavailable):
        await _generate(egress, binding)
    assert gateway.requests == []


async def test_out_of_scope_binding_without_authorized_credential_makes_no_http(
    gateway: _Gateway,
) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    other_project = await _image_binding(container, binding_id="img-p2", project_id="p2")

    with pytest.raises(CredentialScopeError):
        await _generate(egress, other_project)
    assert gateway.requests == []


async def test_disabled_or_foreign_capability_binding_makes_no_http(gateway: _Gateway) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    chat_binding = await container.capability_effects.bindings.get("chat-p1")
    assert chat_binding is not None
    disabled = await container.capability_effects.bindings.put(
        Binding(
            binding_id="img-off",
            workspace_id="ws1",
            project_id="p1",
            capability=IMAGE_GENERATE_CAPABILITY,
            provider_name="flux-dev",
            disabled=True,
            credential_refs=(DEFAULT_MODEL_GATEWAY_CREDENTIAL_REF,),
        )
    )

    with pytest.raises(BindingScopeDenied):
        await _generate(egress, chat_binding)
    with pytest.raises(BindingDisabled):
        await _generate(egress, disabled)
    assert gateway.requests == []
    assert not await container.capability_effects.invocation_store.list_effect(
        run_id="run-1", node_run_id="nr-1", binding_id="chat-p1", effect_key="page-1"
    )


async def test_policy_denial_makes_no_http(gateway: _Gateway) -> None:
    async def deny(*_: Any) -> PolicyVerdict:
        return PolicyVerdict(Decision.DENY, reason="images off", rule="test.deny")

    effects = new_effect_context(policy_evaluator=deny)
    egress = ImageGenerationEgress(effects, endpoint=_ENDPOINT)
    binding = await effects.bindings.put(
        Binding(
            binding_id="img-p1",
            workspace_id="ws1",
            project_id="p1",
            capability=IMAGE_GENERATE_CAPABILITY,
            provider_name="flux-dev",
        )
    )

    with pytest.raises(InvocationDenied):
        await _generate(egress, binding)
    assert gateway.requests == []


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (503, {"error": "upstream down"}),
        (200, {"created": 1, "data": []}),
        (200, {"created": 1, "data": [{"url": "http://cdn/x.png"}]}),
        (200, b"<html>bad gateway</html>"),
        (200, {"created": 1, "data": ["not-an-object"]}),
        (200, {"created": 1, "data": [{"b64_json": "!!not base64!!"}]}),
        (200, {"created": 1, "data": [{"b64_json": base64.b64encode(b"plain text").decode()}]}),
        (200, httpx.ConnectError("gateway down")),
    ],
    ids=[
        "gateway-5xx",
        "empty-data",
        "no-b64",
        "non-json",
        "non-object",
        "bad-b64",
        "not-an-image",
        "unreachable",
    ],
)
async def test_failed_physical_call_is_failed_invocation_not_empty_success(
    gateway: _Gateway, status: int, body: Any
) -> None:
    gateway.status, gateway.body = status, body
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    binding = await _image_binding(container)

    with pytest.raises(ImageGenerationError):
        await _generate(egress, binding)

    (failed,) = await container.capability_effects.invocation_store.list_effect(
        run_id="run-1", node_run_id="nr-1", binding_id="img-p1", effect_key="page-1"
    )
    assert failed.status is InvocationStatus.FAILED
    assert failed.result is None
    assert failed.error

    # FAILED (not UNKNOWN) is what lets a later Attempt retry the same effect.
    gateway.status, gateway.body = 200, _Gateway().body
    retried = await egress.generate(
        binding=binding,
        run_id="run-1",
        node_run_id="nr-1",
        attempt_id="att-2",
        effect_key="page-1",
        request=ImageGenerationRequest(prompt="a fox in the snow", size="512x512"),
    )
    assert retried.images == [_PNG]
    assert len(gateway.requests) == 2


async def test_physical_seam_refuses_foreign_provider_or_request(gateway: _Gateway) -> None:
    request = ImageGenerationRequest(prompt="a fox")

    with pytest.raises(TypeError, match="non-gateway provider"):
        await execute_image_generation(object(), request, endpoint=_ENDPOINT)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="foreign request"):
        await execute_image_generation(
            LlmGatewayImageProvider(model="flux-dev"), {"prompt": "x"}, endpoint=_ENDPOINT
        )
    assert gateway.requests == []


async def test_unregistered_or_tampered_binding_makes_no_http(gateway: _Gateway) -> None:
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)
    registered = await _image_binding(container)
    forged = registered.model_copy(update={"binding_id": "never-registered"})
    widened = registered.model_copy(update={"project_id": "p2"})

    with pytest.raises(BindingNotFound):
        await _generate(egress, forged)
    with pytest.raises(BindingScopeDenied, match="registered definition"):
        await _generate(egress, widened)
    assert gateway.requests == []


@pytest.mark.parametrize(
    "image",
    [b"\xff\xd8\xff\xe0jpeg", b"GIF89a-gif", b"RIFF\x00\x00\x00\x00WEBPVP8 "],
    ids=["jpeg", "gif", "webp"],
)
async def test_other_image_formats_are_accepted(gateway: _Gateway, image: bytes) -> None:
    gateway.body = {"created": 1, "data": [{"b64_json": base64.b64encode(image).decode()}]}
    container = await _container()
    egress = ImageGenerationEgress(container.capability_effects, endpoint=_ENDPOINT)

    result = await _generate(egress, await _image_binding(container))

    assert result.images == [image]
