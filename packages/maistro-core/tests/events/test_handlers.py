"""Tests for maistro.events.handlers — built-in event-bus action handlers."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.events import handlers
from maistro.events.bus import Event, EventCategory, Trigger


@pytest.fixture(autouse=True)
def _reset_service_client() -> None:
    handlers.set_service_client(None)
    yield
    handlers.set_service_client(None)


class _Resp:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _FakeAsyncClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    async def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
        _seen.append({"method": method, "url": url, **kwargs})
        return _Resp()

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        _seen.append({"method": "POST", "url": url, **kwargs})
        return _Resp()


_seen: list[dict[str, Any]] = []


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    _seen.clear()
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)


class _FakeServiceClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _Resp:
        self.calls.append({"method": method, "url": url, **kwargs})
        return _Resp(status_code=201)

    async def post(self, url: str, **kwargs: Any) -> _Resp:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return _Resp(status_code=201)


def _event(**kwargs: object) -> Event:
    defaults: dict[str, Any] = {
        "event_type": "agent.fitness_low",
        "source": "coinswarm",
        "payload": {"agent_id": "abc"},
    }
    defaults.update(kwargs)
    return Event(**defaults)


def _trigger(**kwargs: object) -> Trigger:
    defaults: dict[str, Any] = {"name": "my-trigger", "action_config": {}}
    defaults.update(kwargs)
    return Trigger(**defaults)


class TestRenderTemplate:
    def test_renders_known_keys(self) -> None:
        result = handlers._render_template("hello {name}", {"name": "world"})
        assert result == "hello world"

    def test_missing_key_becomes_placeholder(self) -> None:
        result = handlers._render_template("hello {name}", {})
        assert result == "hello <name>"

    def test_malformed_template_falls_back(self) -> None:
        result = handlers._render_template("hello {0}", {"name": "world"})
        assert result.startswith("hello {0} (payload:")


class TestServiceClientGlobal:
    def test_set_and_get_service_client(self) -> None:
        client = _FakeServiceClient()
        handlers.set_service_client(client)
        assert handlers._get_client() is client

    def test_get_client_defaults_to_none(self) -> None:
        assert handlers._get_client() is None


class TestWebhookAction:
    @pytest.mark.asyncio
    async def test_without_service_client_uses_httpx(self) -> None:
        trigger = _trigger(action_config={"url": "http://example.com/hook", "method": "post"})
        await handlers.webhook_action(trigger, _event())
        assert _seen[0]["method"] == "POST"
        assert _seen[0]["url"] == "http://example.com/hook"

    @pytest.mark.asyncio
    async def test_with_service_client(self) -> None:
        client = _FakeServiceClient()
        handlers.set_service_client(client)
        trigger = _trigger(action_config={"url": "http://example.com/hook"})
        await handlers.webhook_action(trigger, _event())
        assert client.calls[0]["url"] == "http://example.com/hook"

    @pytest.mark.asyncio
    async def test_bearer_token_added_when_no_authorization_header(self) -> None:
        trigger = _trigger(
            action_config={"url": "http://example.com/hook", "bearer_token": "tok123"}
        )
        await handlers.webhook_action(trigger, _event())
        assert _seen[0]["headers"]["Authorization"] == "Bearer tok123"

    @pytest.mark.asyncio
    async def test_explicit_authorization_header_not_overridden(self) -> None:
        trigger = _trigger(
            action_config={
                "url": "http://example.com/hook",
                "bearer_token": "tok123",
                "headers": {"Authorization": "Bearer explicit"},
            }
        )
        await handlers.webhook_action(trigger, _event())
        assert _seen[0]["headers"]["Authorization"] == "Bearer explicit"


class TestConductorChatAction:
    @pytest.mark.asyncio
    async def test_without_message_template_builds_default_message(self) -> None:
        trigger = _trigger(action_config={})
        await handlers.conductor_chat_action(trigger, _event())
        content = _seen[0]["json"]["messages"][0]["content"]
        assert "my-trigger" in content
        assert "agent.fitness_low" in content

    @pytest.mark.asyncio
    async def test_with_message_template_renders_payload(self) -> None:
        trigger = _trigger(action_config={"message": "Agent {agent_id} fired"})
        await handlers.conductor_chat_action(trigger, _event())
        content = _seen[0]["json"]["messages"][0]["content"]
        assert content == "Agent abc fired"

    @pytest.mark.asyncio
    async def test_with_api_key_sets_authorization(self) -> None:
        trigger = _trigger(action_config={"api_key": "secret"})
        await handlers.conductor_chat_action(trigger, _event())
        assert _seen[0]["headers"]["Authorization"] == "Bearer secret"

    @pytest.mark.asyncio
    async def test_with_service_client(self) -> None:
        client = _FakeServiceClient()
        handlers.set_service_client(client)
        trigger = _trigger(action_config={"conductor_url": "http://conductor:8100"})
        await handlers.conductor_chat_action(trigger, _event())
        assert client.calls[0]["url"] == "http://conductor:8100/v1/chat/completions"


class TestCoinswarmAction:
    @pytest.mark.asyncio
    async def test_renders_string_params_and_passes_through_others(self) -> None:
        trigger = _trigger(
            action_config={
                "endpoint": "/agents/notify",
                "params": {"msg": "agent {agent_id} flagged", "count": 1},
            }
        )
        await handlers.coinswarm_action(trigger, _event())
        body = _seen[0]["json"]
        assert body["msg"] == "agent abc flagged"
        assert body["count"] == 1
        assert _seen[0]["url"] == "http://localhost:8080/agents/notify"

    @pytest.mark.asyncio
    async def test_with_service_client(self) -> None:
        client = _FakeServiceClient()
        handlers.set_service_client(client)
        trigger = _trigger(action_config={"endpoint": "/agents/notify", "params": {}})
        await handlers.coinswarm_action(trigger, _event())
        assert client.calls[0]["url"] == "http://localhost:8080/agents/notify"


class TestHaAction:
    @pytest.mark.asyncio
    async def test_builds_url_and_payload(self) -> None:
        trigger = _trigger(
            action_config={
                "ha_token": "tok",
                "domain": "light",
                "service": "turn_on",
                "entity_id": "light.kitchen",
                "service_data": {"brightness": 128},
            }
        )
        await handlers.ha_action(trigger, _event())
        assert _seen[0]["url"] == "http://localhost:8123/api/services/light/turn_on"
        assert _seen[0]["json"]["entity_id"] == "light.kitchen"
        assert _seen[0]["json"]["brightness"] == 128
        assert _seen[0]["headers"]["Authorization"] == "Bearer tok"

    @pytest.mark.asyncio
    async def test_no_entity_id_omits_field(self) -> None:
        trigger = _trigger(action_config={})
        await handlers.ha_action(trigger, _event())
        assert "entity_id" not in _seen[0]["json"]

    @pytest.mark.asyncio
    async def test_with_service_client(self) -> None:
        client = _FakeServiceClient()
        handlers.set_service_client(client)
        trigger = _trigger(action_config={})
        await handlers.ha_action(trigger, _event())
        assert client.calls[0]["url"] == "http://localhost:8123/api/services/automation/trigger"


class TestNtfyAction:
    @pytest.mark.asyncio
    async def test_missing_url_or_topic_logs_and_returns(self) -> None:
        trigger = _trigger(action_config={"ntfy_url": "", "topic": ""})
        await handlers.ntfy_action(trigger, _event())
        assert _seen == []

    @pytest.mark.asyncio
    async def test_missing_topic_only_returns(self) -> None:
        trigger = _trigger(action_config={"ntfy_url": "http://ntfy.local", "topic": ""})
        await handlers.ntfy_action(trigger, _event())
        assert _seen == []

    @pytest.mark.asyncio
    async def test_default_message_and_title(self) -> None:
        trigger = _trigger(action_config={"ntfy_url": "http://ntfy.local/", "topic": "alerts"})
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["url"] == "http://ntfy.local/alerts"
        assert _seen[0]["headers"]["Title"] == "my-trigger"
        assert b"my-trigger" in _seen[0]["content"]

    @pytest.mark.asyncio
    async def test_message_and_title_templates_rendered(self) -> None:
        trigger = _trigger(
            action_config={
                "ntfy_url": "http://ntfy.local",
                "topic": "alerts",
                "message": "Agent {agent_id} flagged",
                "title": "Alert for {agent_id}",
            }
        )
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["content"] == b"Agent abc flagged"
        assert _seen[0]["headers"]["Title"] == "Alert for abc"

    @pytest.mark.asyncio
    async def test_priority_in_range_and_not_default_is_set(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "priority": 5}
        )
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["headers"]["Priority"] == "5"

    @pytest.mark.asyncio
    async def test_priority_equal_to_default_three_is_omitted(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "priority": 3}
        )
        await handlers.ntfy_action(trigger, _event())
        assert "Priority" not in _seen[0]["headers"]

    @pytest.mark.asyncio
    async def test_priority_out_of_range_is_omitted(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "priority": 9}
        )
        await handlers.ntfy_action(trigger, _event())
        assert "Priority" not in _seen[0]["headers"]

    @pytest.mark.asyncio
    async def test_non_int_priority_is_omitted(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "priority": "high"}
        )
        await handlers.ntfy_action(trigger, _event())
        assert "Priority" not in _seen[0]["headers"]

    @pytest.mark.asyncio
    async def test_tags_list_joined(self) -> None:
        trigger = _trigger(
            action_config={
                "ntfy_url": "http://ntfy.local",
                "topic": "alerts",
                "tags": ["warning", "fire"],
            }
        )
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["headers"]["Tags"] == "warning,fire"

    @pytest.mark.asyncio
    async def test_empty_tags_list_omitted(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "tags": []}
        )
        await handlers.ntfy_action(trigger, _event())
        assert "Tags" not in _seen[0]["headers"]

    @pytest.mark.asyncio
    async def test_non_list_tags_omitted(self) -> None:
        trigger = _trigger(
            action_config={"ntfy_url": "http://ntfy.local", "topic": "alerts", "tags": "x"}
        )
        await handlers.ntfy_action(trigger, _event())
        assert "Tags" not in _seen[0]["headers"]

    @pytest.mark.asyncio
    async def test_click_url_set(self) -> None:
        trigger = _trigger(
            action_config={
                "ntfy_url": "http://ntfy.local",
                "topic": "alerts",
                "click": "http://example.com",
            }
        )
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["headers"]["Click"] == "http://example.com"

    @pytest.mark.asyncio
    async def test_access_token_sets_authorization(self) -> None:
        trigger = _trigger(
            action_config={
                "ntfy_url": "http://ntfy.local",
                "topic": "alerts",
                "access_token": "tok",
            }
        )
        await handlers.ntfy_action(trigger, _event())
        assert _seen[0]["headers"]["Authorization"] == "Bearer tok"


class TestLogAction:
    @pytest.mark.asyncio
    async def test_logs_without_error(self) -> None:
        trigger = _trigger()
        await handlers.log_action(trigger, _event(category=EventCategory.SECURITY))
        assert _seen == []


class TestBuiltinHandlers:
    def test_all_handlers_registered(self) -> None:
        assert set(handlers.BUILTIN_HANDLERS) == {
            "webhook",
            "conductor_chat",
            "coinswarm",
            "ha",
            "ntfy",
            "log",
        }
