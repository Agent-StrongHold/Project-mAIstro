"""Open Design renderer provider — SPEC-070426-6ea8 / ADR-070426-f2a0.

Fills the slots canvas cannot: ``reflowable-web``, ``deck``, ``video``, and
``designsystems.live``, by talking to a local Open Design daemon
(``nexu-io/open-design``, Apache-2.0). It is a :class:`RenderProvider`, so the substrate
(SPEC-070426-a22b) handles the absence-vs-failure split:

* **Absence** — :meth:`discover` never raises; a daemon that is disabled, unreachable, or
  unhealthy yields ``down()`` and the provider fills no slots (its skills are silently
  filtered, no error).
* **Failure** — :meth:`render` *may* raise (bad status / transport error); the substrate
  circuit-breaks the provider on that.

Daemon surface (as of nexu-io/open-design main): base ``http://127.0.0.1:7456``, bearer
auth, health ``GET /api/health``, dispatch ``POST /api/chat``. The token is supplied by the
caller (resolved from the vault upstream); this provider never reads secrets itself.

Fidelity note: the daemon streams SSE and writes artifacts to disk. This first cut treats
``POST /api/chat`` as request/response and ingests the returned body — enough to plug the
provider in end-to-end and test it. True SSE + on-disk artifact ingest is tracked in the SPEC.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from maistro_design.renderers import RendererDiscovery
from maistro_design.trust import TrustTier
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignSkill,
    OutputFormat,
    RenderSlot,
)

logger = logging.getLogger("maistro.design.providers.open_design")


@dataclass
class OpenDesignConfig:
    """Connection settings. ``token`` is resolved from the vault by the caller."""

    enabled: bool = True
    base_url: str = "http://127.0.0.1:7456"
    token: str | None = None
    timeout: float = 1.5


class OpenDesignProvider:
    """A :class:`~maistro_design.renderers.RenderProvider` backed by an Open Design daemon."""

    slots: tuple[RenderSlot, ...] = (
        RenderSlot.REFLOWABLE_WEB,
        RenderSlot.DECK,
        RenderSlot.VIDEO,
        RenderSlot.DESIGN_SYSTEMS_LIVE,
    )

    def __init__(
        self,
        config: OpenDesignConfig | None = None,
        *,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self.config = config or OpenDesignConfig()
        # injectable for tests (httpx.MockTransport); defaults to a real client
        self._client_factory = client_factory or (lambda: httpx.AsyncClient())

    @property
    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config.token}"} if self.config.token else {}

    async def discover(self) -> RendererDiscovery:
        if not self.config.enabled:
            return RendererDiscovery.down()
        try:
            async with self._client_factory() as client:
                resp = await client.get(
                    f"{self.config.base_url}/api/health",
                    headers=self._auth,
                    timeout=self.config.timeout,
                )
        except Exception:
            logger.info(
                "Open Design daemon unreachable at %s; feature absent", self.config.base_url
            )
            return RendererDiscovery.down()
        if resp.is_success:
            return RendererDiscovery.up(self.slots)
        logger.info("Open Design health returned %s; treating as down", resp.status_code)
        return RendererDiscovery.down()

    async def render(self, prompt_stack: str, skill: DesignSkill) -> ArtifactNode:
        """Dispatch the prompt stack to the daemon and ingest the returned artifact.

        Raises ``httpx.HTTPStatusError`` / transport errors on failure — the substrate
        circuit-breaks the provider on that (failure is not silent)."""
        async with self._client_factory() as client:
            resp = await client.post(
                f"{self.config.base_url}/api/chat",
                headers=self._auth,
                json={"prompt": prompt_stack, "skill": skill.slug},
                timeout=self.config.timeout,
            )
            resp.raise_for_status()
            return _ingest(resp, skill)


def _ingest(resp: httpx.Response, skill: DesignSkill) -> ArtifactNode:
    """Map a daemon response to a trust-tagged ArtifactNode by the skill's slot."""
    meta = {"trust_tier": TrustTier.T2, "source": "open-design"}
    if skill.render_slot is RenderSlot.DECK:
        return ArtifactNode(
            key=skill.slug,
            kind=ArtifactKind.BLOB,
            format=OutputFormat.PPTX,
            value=resp.content,
            metadata=meta,
        )
    if skill.render_slot is RenderSlot.VIDEO:
        return ArtifactNode(
            key=skill.slug,
            kind=ArtifactKind.BLOB,
            format=None,
            value=resp.content,
            metadata={**meta, "format": "mp4"},
        )
    # reflowable-web and everything else: text (HTML). The daemon streams SSE, so
    # accumulate the event payloads; a plain-body response passes through unchanged.
    content_type = resp.headers.get("content-type", "")
    value = _sse_text(resp.text) if "text/event-stream" in content_type else resp.text
    return ArtifactNode(
        key=skill.slug,
        kind=ArtifactKind.FILE,
        format=OutputFormat.HTML,
        value=value,
        metadata=meta,
    )


def _sse_text(body: str) -> str:
    """Concatenate the ``data:`` payloads of a text/event-stream body.

    Handles flat JSON events (``content`` / ``text`` / ``delta`` as a string), the
    Anthropic-style nested shape (``content_block_delta`` with
    ``delta: {"type": "text_delta", "text": ...}``), and raw-text events; skips
    comments, empty lines, and the ``[DONE]`` sentinel.
    """
    chunks: list[str] = []
    for line in body.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            chunks.append(payload)
            continue
        chunks.append(_event_text(event))
    return "".join(chunks)


def _event_text(event: object) -> str:
    """Extract the text an SSE event carries, across the shapes daemons emit."""
    if isinstance(event, str):
        return event
    if not isinstance(event, dict):
        return str(event)
    # Anthropic/Open Design nested delta: {"delta": {"type": "text_delta", "text": "..."}}
    delta = event.get("delta")
    if isinstance(delta, dict):
        return str(delta.get("text") or delta.get("partial_json") or "")
    # Flat shapes: content / text / delta as a plain string.
    for key in ("content", "text", "delta"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
