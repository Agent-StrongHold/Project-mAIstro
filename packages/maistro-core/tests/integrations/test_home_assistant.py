"""Tests for maistro.integrations.home_assistant — Home Assistant REST integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from maistro.events.bus import Event, EventCategory
from maistro.http import set_test_transport
from maistro.integrations.home_assistant import HomeAssistantIntegration


def _patched_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    set_test_transport(transport)


class TestInit:
    def test_strips_trailing_slash(self) -> None:
        ha = HomeAssistantIntegration(url="http://localhost:8123/")
        assert ha._url == "http://localhost:8123"

    def test_no_event_bus_by_default(self) -> None:
        ha = HomeAssistantIntegration()
        assert ha._bus is None


class TestHeaders:
    def test_includes_bearer_token(self) -> None:
        ha = HomeAssistantIntegration(token="abc123")
        assert ha._headers() == {
            "Authorization": "Bearer abc123",
            "Content-Type": "application/json",
        }


class TestGetStates:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://ha/api/states"
            assert request.headers["authorization"] == "Bearer tok"
            return httpx.Response(200, json=[{"entity_id": "light.x", "state": "on"}])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha", token="tok")
        result = await ha.get_states()
        assert result == [{"entity_id": "light.x", "state": "on"}]

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        with pytest.raises(httpx.HTTPStatusError):
            await ha.get_states()


class TestGetState:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://ha/api/states/light.x"
            return httpx.Response(200, json={"entity_id": "light.x", "state": "on"})

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        result = await ha.get_state("light.x")
        assert result == {"entity_id": "light.x", "state": "on"}

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        assert await ha.get_state("light.missing") is None

    @pytest.mark.asyncio
    async def test_raises_on_other_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        with pytest.raises(httpx.HTTPStatusError):
            await ha.get_state("light.x")


class TestCallService:
    @pytest.mark.asyncio
    async def test_posts_with_payload(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json=[{"ok": True}])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        result = await ha.call_service("light", "turn_on", {"entity_id": "light.x"})
        assert result == [{"ok": True}]
        assert captured["url"] == "http://ha/api/services/light/turn_on"
        assert captured["body"] == {"entity_id": "light.x"}

    @pytest.mark.asyncio
    async def test_defaults_service_data_to_empty_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json=[])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        await ha.call_service("light", "turn_off")
        assert captured["body"] == {}

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400)

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        with pytest.raises(httpx.HTTPStatusError):
            await ha.call_service("light", "turn_on")


class TestControlDevice:
    @pytest.mark.asyncio
    async def test_returns_error_for_uncontrollable_domain(self) -> None:
        ha = HomeAssistantIntegration(url="http://ha")
        result = await ha.control_device("sensor.temp", "turn_on")
        assert result == "Error: domain 'sensor' not controllable"

    @pytest.mark.asyncio
    async def test_success_returns_ok_message(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        result = await ha.control_device("light.x", "turn_on")
        assert result == "OK: light.x → turn_on"

    @pytest.mark.asyncio
    async def test_includes_params_in_service_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json=[])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        await ha.control_device("light.x", "turn_on", params={"brightness": 100})
        assert captured["body"] == {"entity_id": "light.x", "brightness": 100}

    @pytest.mark.asyncio
    async def test_catches_http_error_and_returns_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        result = await ha.control_device("light.x", "turn_on")
        assert result.startswith("Error: ")


class TestEmitStateChanges:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_bus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call get_states when bus is None")

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        assert await ha.emit_state_changes() == 0

    @pytest.mark.asyncio
    async def test_emits_one_event_per_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"entity_id": "light.x", "state": "on", "attributes": {"brightness": 5}},
                    {"entity_id": "light.y", "state": "off"},
                ],
            )

        _patched_client(monkeypatch, handler)
        bus = AsyncMock()
        ha = HomeAssistantIntegration(url="http://ha", event_bus=bus)
        count = await ha.emit_state_changes()

        assert count == 2
        assert bus.emit.await_count == 2
        first_event: Event = bus.emit.await_args_list[0].args[0]
        assert first_event.category == EventCategory.SMART_HOME
        assert first_event.event_type == "ha_state"
        assert first_event.source == "home_assistant"
        assert first_event.payload == {
            "entity_id": "light.x",
            "state": "on",
            "attributes": {"brightness": 5},
        }
        second_event: Event = bus.emit.await_args_list[1].args[0]
        assert second_event.payload == {
            "entity_id": "light.y",
            "state": "off",
            "attributes": {},
        }


class TestHandleWebhook:
    @pytest.mark.asyncio
    async def test_noop_when_no_bus(self) -> None:
        ha = HomeAssistantIntegration(url="http://ha")
        await ha.handle_webhook({"event_type": "x"})

    @pytest.mark.asyncio
    async def test_emits_event_with_given_event_type(self) -> None:
        bus = AsyncMock()
        ha = HomeAssistantIntegration(url="http://ha", event_bus=bus)
        await ha.handle_webhook({"event_type": "motion_detected", "data": {"x": 1}})

        event: Event = bus.emit.await_args.args[0]
        assert event.category == EventCategory.SMART_HOME
        assert event.event_type == "motion_detected"
        assert event.source == "home_assistant"
        assert event.payload == {"event_type": "motion_detected", "data": {"x": 1}}

    @pytest.mark.asyncio
    async def test_defaults_event_type_to_webhook(self) -> None:
        bus = AsyncMock()
        ha = HomeAssistantIntegration(url="http://ha", event_bus=bus)
        await ha.handle_webhook({"data": {}})

        event: Event = bus.emit.await_args.args[0]
        assert event.event_type == "webhook"


class TestListDevices:
    @pytest.mark.asyncio
    async def test_filters_to_controllable_domains(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "entity_id": "light.x",
                        "state": "on",
                        "attributes": {"friendly_name": "Lamp"},
                    },
                    {"entity_id": "sensor.temp", "state": "21"},
                ],
            )

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        devices = await ha.list_devices()
        assert devices == [{"entity_id": "light.x", "state": "on", "friendly_name": "Lamp"}]

    @pytest.mark.asyncio
    async def test_defaults_friendly_name_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"entity_id": "light.x", "state": "on"}])

        _patched_client(monkeypatch, handler)
        ha = HomeAssistantIntegration(url="http://ha")
        devices = await ha.list_devices()
        assert devices == [{"entity_id": "light.x", "state": "on", "friendly_name": ""}]
