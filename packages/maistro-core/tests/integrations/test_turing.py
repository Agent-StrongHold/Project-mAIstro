"""Tests for maistro.integrations.turing — Project Turing self-model integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from maistro.events.bus import Event, EventCategory
from maistro.http import set_test_transport
from maistro.integrations.turing import TuringIntegration


def _patched_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    set_test_transport(transport)


class TestInit:
    def test_strips_trailing_slashes(self) -> None:
        turing = TuringIntegration(chat_url="http://chat/", metrics_url="http://metrics/")
        assert turing._chat_url == "http://chat"
        assert turing._metrics_url == "http://metrics"

    def test_no_event_bus_by_default(self) -> None:
        turing = TuringIntegration()
        assert turing._bus is None


class TestChat:
    @pytest.mark.asyncio
    async def test_posts_message_and_returns_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "hi there"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        result = await turing.chat("hello", user="alice")
        assert result == "hi there"
        assert captured["url"] == "http://chat/api/chat"
        assert captured["body"] == {"message": "hello", "user": "alice"}

    @pytest.mark.asyncio
    async def test_defaults_user_to_system(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        await turing.chat("hello")
        assert captured["body"] == {"message": "hello", "user": "system"}

    @pytest.mark.asyncio
    async def test_defaults_response_to_empty_string_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        assert await turing.chat("hello") == ""

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        with pytest.raises(httpx.HTTPStatusError):
            await turing.chat("hello")


class TestTriggerReflection:
    @pytest.mark.asyncio
    async def test_uses_given_topic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        await turing.trigger_reflection("the project")
        body = captured["body"]
        assert "the project" in body["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_defaults_topic_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        await turing.trigger_reflection()
        body = captured["body"]
        assert "your recent experiences and growth" in body["message"]  # type: ignore[index]


class TestTriggerDaydream:
    @pytest.mark.asyncio
    async def test_sends_daydream_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        await turing.trigger_daydream()
        body = captured["body"]
        assert "daydream" in body["message"].lower()  # type: ignore[index]


class TestTriggerWriting:
    @pytest.mark.asyncio
    async def test_sends_writing_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        await turing.trigger_writing("write a haiku")
        body = captured["body"]
        assert "write a haiku" in body["message"]  # type: ignore[index]


class TestGetMetrics:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://metrics/metrics"
            return httpx.Response(200, json={"mood": "calm"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(metrics_url="http://metrics")
        result = await turing.get_metrics()
        assert result == {"mood": "calm"}

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(metrics_url="http://metrics")
        with pytest.raises(httpx.HTTPStatusError):
            await turing.get_metrics()


class TestEmitMoodEvent:
    @pytest.mark.asyncio
    async def test_noop_when_no_bus(self) -> None:
        turing = TuringIntegration()
        await turing.emit_mood_event({"mood": "happy"})

        assert turing._bus is None

    @pytest.mark.asyncio
    async def test_emits_event_with_mood_data(self) -> None:
        bus = AsyncMock()
        turing = TuringIntegration(event_bus=bus)
        await turing.emit_mood_event({"mood": "happy", "valence": 0.8})

        event: Event = bus.emit.await_args.args[0]
        assert event.category == EventCategory.TURING
        assert event.event_type == "mood_shift"
        assert event.source == "turing"
        assert event.payload == {"mood": "happy", "valence": 0.8}


class TestEmitWritingEvent:
    @pytest.mark.asyncio
    async def test_noop_when_no_bus(self) -> None:
        turing = TuringIntegration()
        await turing.emit_writing_event("blog", "Title")

        assert turing._bus is None

    @pytest.mark.asyncio
    async def test_emits_event_with_truncated_preview(self) -> None:
        bus = AsyncMock()
        turing = TuringIntegration(event_bus=bus)
        long_preview = "x" * 300
        await turing.emit_writing_event("blog", "Title", long_preview)

        event: Event = bus.emit.await_args.args[0]
        assert event.category == EventCategory.TURING
        assert event.event_type == "writing_complete"
        assert event.source == "turing"
        assert event.payload == {
            "writing_type": "blog",
            "title": "Title",
            "preview": "x" * 200,
        }

    @pytest.mark.asyncio
    async def test_defaults_preview_to_empty_string(self) -> None:
        bus = AsyncMock()
        turing = TuringIntegration(event_bus=bus)
        await turing.emit_writing_event("blog", "Title")

        event: Event = bus.emit.await_args.args[0]
        assert event.payload["preview"] == ""


class TestHandleCoinswarmEvent:
    @pytest.mark.asyncio
    async def test_agent_fitness_sends_chat_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.TRADING,
            event_type="agent_fitness",
            payload={"agent_id": "a1", "fitness": 0.875},
        )
        await turing.handle_coinswarm_event(event)
        body = captured["body"]
        assert "Agent a1" in body["message"]  # type: ignore[index]
        assert "0.88" in body["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_evolution_cycle_complete_sends_chat_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.TRADING,
            event_type="evolution_cycle_complete",
            payload={"generation": 4, "best_fitness": 0.95},
        )
        await turing.handle_coinswarm_event(event)
        body = captured["body"]
        assert "cycle 4" in body["message"]  # type: ignore[index]
        assert "0.95" in body["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_unrecognized_event_type_does_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call chat for unrecognized event type")

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(category=EventCategory.TRADING, event_type="other", payload={})
        await turing.handle_coinswarm_event(event)


class TestHandleHaEvent:
    @pytest.mark.asyncio
    async def test_sensor_entity_sends_chat_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.SMART_HOME,
            event_type="ha_state",
            payload={
                "entity_id": "sensor.temp",
                "state": "21",
                "attributes": {"friendly_name": "Living Room Temp"},
            },
        )
        await turing.handle_ha_event(event)
        body = captured["body"]
        assert "Living Room Temp" in body["message"]  # type: ignore[index]
        assert "21" in body["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_binary_sensor_entity_sends_chat_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.SMART_HOME,
            event_type="ha_state",
            payload={"entity_id": "binary_sensor.door", "state": "open"},
        )
        await turing.handle_ha_event(event)
        assert "binary_sensor.door" in captured["body"]["message"]  # type: ignore[index]
        assert "open" in captured["body"]["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_weather_entity_sends_chat_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.SMART_HOME,
            event_type="ha_state",
            payload={"entity_id": "weather.home", "state": "sunny"},
        )
        await turing.handle_ha_event(event)
        assert "weather.home" in captured["body"]["message"]  # type: ignore[index]
        assert "sunny" in captured["body"]["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_falls_back_to_entity_id_when_no_friendly_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"response": "ok"})

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.SMART_HOME,
            event_type="ha_state",
            payload={"entity_id": "sensor.temp", "state": "21"},
        )
        await turing.handle_ha_event(event)
        body = captured["body"]
        assert "sensor.temp" in body["message"]  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_non_sensor_entity_does_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call chat for non-sensor entity")

        _patched_client(monkeypatch, handler)
        turing = TuringIntegration(chat_url="http://chat")
        event = Event(
            category=EventCategory.SMART_HOME,
            event_type="ha_state",
            payload={"entity_id": "light.x", "state": "on"},
        )
        await turing.handle_ha_event(event)
