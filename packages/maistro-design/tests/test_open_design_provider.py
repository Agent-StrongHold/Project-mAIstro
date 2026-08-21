"""Open Design renderer provider — SPEC-070426-6ea8.

Drives the provider against a stubbed daemon (httpx.MockTransport): discovery
up/down/absent, and render ingest for each slot, plus the failure path that the
substrate circuit-breaks on.
"""

from __future__ import annotations

import httpx
import pytest

from maistro_design.providers import OpenDesignConfig, OpenDesignProvider
from maistro_design.renderers import RendererRegistry, RenderSlot
from maistro_design.trust import TrustTier
from maistro_design.types import ArtifactKind, DesignSkill, OutputFormat, SkillMode


def _skill(slot: RenderSlot | None) -> DesignSkill:
    return DesignSkill(
        slug="landing", name="landing", mode=SkillMode.PROTOTYPE, description="", render_slot=slot
    )


def _provider(handler, *, enabled: bool = True, token: str | None = "tok") -> OpenDesignProvider:
    transport = httpx.MockTransport(handler)
    return OpenDesignProvider(
        OpenDesignConfig(enabled=enabled, token=token),
        client_factory=lambda: httpx.AsyncClient(transport=transport),
    )


# ─── discovery: absence is silent ───────────────────────────────────────────────


async def test_discover_up_when_daemon_healthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/health"
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json={"ok": True})

    result = await _provider(handler).discover()
    assert result.available
    assert RenderSlot.REFLOWABLE_WEB in result.slots


async def test_discover_down_when_disabled_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no HTTP call when disabled")

    result = await _provider(handler, enabled=False).discover()
    assert not result.available


async def test_discover_down_on_unhealthy_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    assert not (await _provider(handler).discover()).available


async def test_discover_down_on_connect_error_does_not_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("daemon down")

    result = await _provider(handler).discover()  # absence, never propagates
    assert not result.available


# ─── render: ingest by slot ─────────────────────────────────────────────────────


async def test_render_reflowable_web_yields_editable_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/chat"
        return httpx.Response(200, text="<main>hi</main>")

    node = await _provider(handler).render("PROMPT", _skill(RenderSlot.REFLOWABLE_WEB))
    assert node.kind is ArtifactKind.FILE
    assert node.format is OutputFormat.HTML
    assert node.value == "<main>hi</main>"
    assert node.metadata["trust_tier"] is TrustTier.T2
    assert node.metadata["source"] == "open-design"


async def test_render_reflowable_web_accumulates_sse_stream() -> None:
    body = (
        'data: {"content": "<main>"}\n\ndata: {"delta": "hi"}\n\ndata: </main>\n\ndata: [DONE]\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    node = await _provider(handler).render("PROMPT", _skill(RenderSlot.REFLOWABLE_WEB))
    assert node.value == "<main>hi</main>"


async def test_render_accumulates_nested_anthropic_deltas() -> None:
    """content_block_delta events nest text under delta.text — extract it, not str(dict)."""
    body = (
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "<h1>"}}\n\n'
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}}\n\n'
        'data: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "</h1>"}}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    node = await _provider(handler).render("PROMPT", _skill(RenderSlot.REFLOWABLE_WEB))
    assert node.value == "<h1>Hi</h1>"
    assert "text_delta" not in str(node.value)  # no raw dict leaked into the artifact


async def test_render_deck_yields_pptx_blob() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"PK\x03\x04pptx")

    node = await _provider(handler).render("PROMPT", _skill(RenderSlot.DECK))
    assert node.kind is ArtifactKind.BLOB
    assert node.format is OutputFormat.PPTX
    assert node.value == b"PK\x03\x04pptx"


async def test_render_video_yields_blob_tagged_mp4() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"\x00\x00mp4")

    node = await _provider(handler).render("PROMPT", _skill(RenderSlot.VIDEO))
    assert node.kind is ArtifactKind.BLOB
    assert node.metadata["format"] == "mp4"


async def test_render_raises_on_daemon_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(handler).render("PROMPT", _skill(RenderSlot.REFLOWABLE_WEB))


# ─── end to end through the substrate ───────────────────────────────────────────


async def test_provider_plugs_into_registry_and_breaker_trips_on_failure() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200)
        calls["n"] += 1
        return httpx.Response(500)  # render always fails

    reg = RendererRegistry()
    reg.register(_provider(handler))
    filled = await reg.discover_all()
    assert RenderSlot.REFLOWABLE_WEB in filled  # discovered => offered

    from maistro_design.renderers import RenderProviderError

    with pytest.raises(RenderProviderError):
        await reg.render(RenderSlot.REFLOWABLE_WEB, "P", _skill(RenderSlot.REFLOWABLE_WEB))
    # failure (not absence) => circuit-broken, slot withdrawn until re-discovery
    assert RenderSlot.REFLOWABLE_WEB not in reg.filled_slots()
