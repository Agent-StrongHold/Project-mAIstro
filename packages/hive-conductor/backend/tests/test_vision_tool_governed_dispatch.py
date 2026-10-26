"""The dashboard vision tool and the degraded builder path stay governed.

Two shipped seams in `services.chat_completion` had no direct tests:

- `_tool_analyze_dashboard` — issue #1084 bounded work item 5: the tool's
  model dispatch must cross the same `build_llm_port` seam every other chat
  turn uses, not a private transport. These tests pin the request shape it
  sends (text prompt + dashboard image part), the answer it returns, and the
  error shape when the vision call fails.
- `build_llm_port`'s engine-failure path — when the engine cannot supply the
  Container's governed client, the port composes the canonical compatibility
  client itself (registered default credential, canonical Invocation ledger);
  it never returns an ungoverned dispatcher.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import services.chat_completion as chat_completion
from adapters.llm_http import HttpOpenAIProtocolLLM
from models.schemas import ChatCompletionRequest
from services.chat_completion import _tool_analyze_dashboard

pytestmark = pytest.mark.asyncio


class _FakeScreenshotClient:
    """Stands in for the pooled client the screenshot endpoint is read on."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    async def __aenter__(self) -> _FakeScreenshotClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, *args: Any, **kwargs: Any) -> Any:
        payload = self._payload

        class _Resp:
            def json(self) -> dict[str, Any]:
                return payload

        return _Resp()


class _RecordingVisionPort:
    """Records the vision request; answers like a chat.completions call."""

    def __init__(self, answer: dict[str, Any] | Exception) -> None:
        self._answer = answer
        self.requests: list[ChatCompletionRequest] = []

    async def complete(self, req: ChatCompletionRequest) -> dict[str, Any]:
        self.requests.append(req)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer

    async def stream(self, req: ChatCompletionRequest) -> Any:  # pragma: no cover
        raise AssertionError("the dashboard tool dispatches one complete, never a stream")


def _patch_screenshot(monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]) -> None:
    monkeypatch.setattr(
        chat_completion,
        "shared_client",
        lambda timeout: _FakeScreenshotClient(payload),
    )


async def test_analyze_dashboard_dispatches_the_vision_call_through_the_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool's model call crosses the one LLM seam, image and prompt on it."""

    _patch_screenshot(monkeypatch, {"screenshot": "ZmFrZS1wbmc="})
    port = _RecordingVisionPort(
        {"choices": [{"message": {"content": "chart 2 is broken"}}]},
    )
    monkeypatch.setattr(chat_completion, "build_llm_port", lambda: port)

    out = await _tool_analyze_dashboard({}, "user-1", None)

    assert out == {"analysis": "chart 2 is broken", "model": "gpt-4o-mini"}
    (sent,) = port.requests
    assert sent.model == "gpt-4o-mini"
    text_part, image_part_full = sent.messages[0]["content"]
    assert text_part["type"] == "text"
    assert text_part["text"].startswith("Analyze this dashboard screenshot")
    assert image_part_full["type"] == "image_url"
    image_part = image_part_full["image_url"]["url"]
    assert image_part.startswith("data:image/png;base64,")
    assert "ZmFrZS1wbmc=" in image_part


async def test_analyze_dashboard_reports_a_failed_vision_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refused vision call is an error result, never a fabricated analysis."""

    _patch_screenshot(monkeypatch, {"screenshot": "ZmFrZS1wbmc="})
    port = _RecordingVisionPort(RuntimeError("status=503 gateway refused"))
    monkeypatch.setattr(chat_completion, "build_llm_port", lambda: port)

    out = await _tool_analyze_dashboard({}, "user-1", None)

    assert out == {"error": "Vision analysis failed: status=503 gateway refused"}


async def test_build_llm_port_survives_a_broken_engine_and_stays_governed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the engine's Container the port composes the canonical client.

    The engine failing to name a Container must not degrade the process to an
    ungoverned dispatcher: the builder's fallback composes the same core
    compatibility client itself, so model dispatch still lands on the
    canonical Invocation ledger.
    """

    class _ExplodingAgentPort:
        @property
        def container(self) -> Any:
            raise RuntimeError("engine container not ready")

    class _ExplodingEngine:
        agent_port = _ExplodingAgentPort()

    monkeypatch.setattr(
        chat_completion,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base="https://gateway.invalid",
            litellm_key="builder-key",
            llm_http_variant="chat_completions",
        ),
    )
    monkeypatch.setattr(
        chat_completion, "_resolve_litellm_api_key", lambda _settings: "builder-key"
    )
    monkeypatch.setattr("services.engine.get_engine", lambda: _ExplodingEngine())

    port = chat_completion.build_llm_port()

    assert isinstance(port, HttpOpenAIProtocolLLM)
    # The composed client is the governed one: an egress authority is present,
    # not a raw-HTTP dispatcher.
    assert port._client is not None  # type: ignore[attr-defined]
    assert port._client._egress is not None  # type: ignore[attr-defined]


async def test_build_llm_port_without_a_container_composes_the_canonical_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An engine that names no Container (stub/dev process) stays governed.

    `container=None` is the documented stub/dev shape, not a license for raw
    dispatch: the builder falls through to the same self-composed canonical
    compatibility client the failure path uses.
    """

    monkeypatch.setattr(
        chat_completion,
        "get_settings",
        lambda: SimpleNamespace(
            litellm_api_base="https://gateway.invalid",
            litellm_key="builder-key",
            llm_http_variant="chat_completions",
        ),
    )
    monkeypatch.setattr(
        chat_completion, "_resolve_litellm_api_key", lambda _settings: "builder-key"
    )
    monkeypatch.setattr(
        "services.engine.get_engine",
        lambda: SimpleNamespace(agent_port=SimpleNamespace(container=None)),
    )

    port = chat_completion.build_llm_port()

    assert isinstance(port, HttpOpenAIProtocolLLM)
    assert port._client is not None  # type: ignore[attr-defined]
    assert port._client._egress is not None  # type: ignore[attr-defined]
