"""Tests for the ntfy NotificationClient and event-bus action handler."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.events.bus import Event, EventCategory, Trigger
from maistro.events.handlers import BUILTIN_HANDLERS, ntfy_action
from maistro.integrations.ntfy import NtfyClient
from maistro.protocols.notification import Notification, NotificationClient


def _mock_client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_ntfy_client_posts_message_with_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        captured["headers"] = request.headers  # httpx.Headers: case-insensitive
        return httpx.Response(200)

    client = _mock_client(handler)
    ntfy = NtfyClient(
        base_url="https://ntfy.example.com",
        default_topic="maistro-abc",
        access_token="tk_123",
        client=client,
    )
    await ntfy.send(
        Notification(
            message="hello world",
            title="Heads up",
            priority=4,
            tags=("warning", "robot"),
            click="https://example.com/x",
        )
    )
    await ntfy.aclose()
    await client.aclose()

    assert captured["url"] == "https://ntfy.example.com/maistro-abc"
    assert captured["body"] == "hello world"
    assert captured["headers"]["title"] == "Heads up"
    assert captured["headers"]["priority"] == "4"
    assert captured["headers"]["tags"] == "warning,robot"
    assert captured["headers"]["click"] == "https://example.com/x"
    assert captured["headers"]["authorization"] == "Bearer tk_123"


@pytest.mark.asyncio
async def test_ntfy_client_uses_notification_topic_override() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200)

    client = _mock_client(handler)
    ntfy = NtfyClient(
        base_url="https://ntfy.example.com/",
        default_topic="default",
        client=client,
    )
    await ntfy.send(Notification(message="x", topic="override-topic"))
    await ntfy.aclose()
    await client.aclose()

    assert captured["url"] == "https://ntfy.example.com/override-topic"


@pytest.mark.asyncio
async def test_ntfy_client_skips_when_no_topic() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    client = _mock_client(handler)
    ntfy = NtfyClient(base_url="https://ntfy.example.com", client=client)
    await ntfy.send(Notification(message="hello"))
    await ntfy.aclose()
    await client.aclose()

    assert calls == 0


@pytest.mark.asyncio
async def test_ntfy_client_swallows_transport_errors() -> None:
    attempts = 0

    def boom(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError("refused", request=request)

    client = _mock_client(boom)
    ntfy = NtfyClient(base_url="https://ntfy.example.com", default_topic="t", client=client)
    await ntfy.send(Notification(message="x"))
    await ntfy.aclose()
    await client.aclose()

    assert attempts == 1


def test_ntfy_client_satisfies_protocol() -> None:
    ntfy = NtfyClient(base_url="https://ntfy.example.com")
    assert isinstance(ntfy, NotificationClient)


def test_ntfy_action_registered_in_builtins() -> None:
    assert BUILTIN_HANDLERS["ntfy"] is ntfy_action


@pytest.mark.asyncio
async def test_ntfy_action_posts_formatted_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode()
        captured["headers"] = request.headers  # httpx.Headers: case-insensitive
        return httpx.Response(200)

    # A MockTransport rather than a stand-in client class: the request is
    # captured after httpx has built it, so the assertions below check what
    # would actually go on the wire rather than what the call site passed.
    monkeypatch.setattr("maistro.http._test_transport", httpx.MockTransport(handler), raising=False)

    trigger = Trigger(
        name="fitness-alert",
        event_types=["agent_fitness"],
        action_type="ntfy",
        action_config={
            "ntfy_url": "https://ntfy.example.com",
            "topic": "maistro-abc",
            "access_token": "tk",
            "title": "Agent {name}",
            "message": "fitness={value}",
            "priority": 4,
            "tags": ["warning"],
        },
    )
    event = Event(
        category=EventCategory.AGENT,
        event_type="agent_fitness",
        source="router",
        payload={"name": "alpha", "value": 0.12},
    )

    await ntfy_action(trigger, event)

    assert captured["url"] == "https://ntfy.example.com/maistro-abc"
    assert captured["body"] == "fitness=0.12"
    assert captured["headers"]["Title"] == "Agent alpha"
    assert captured["headers"]["Priority"] == "4"
    assert captured["headers"]["Tags"] == "warning"
    assert captured["headers"]["Authorization"] == "Bearer tk"


@pytest.mark.asyncio
async def test_ntfy_action_noop_without_url_or_topic(caplog: pytest.LogCaptureFixture) -> None:
    trigger = Trigger(
        name="x",
        event_types=["t"],
        action_type="ntfy",
        action_config={"topic": "only-topic"},
    )
    event = Event(category=EventCategory.AGENT, event_type="t", source="s", payload={})
    await ntfy_action(trigger, event)

    assert "missing ntfy_url or topic" in caplog.text
