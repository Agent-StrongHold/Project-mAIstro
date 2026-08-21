"""Tests for maistro.integrations.coinswarm — CoinSwarm trading-agent integration."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from maistro.events.bus import Event, EventCategory
from maistro.http import set_test_transport
from maistro.integrations.coinswarm import CoinSwarmIntegration


def _patched_client(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    transport = httpx.MockTransport(handler)
    set_test_transport(transport)


class TestInit:
    def test_strips_trailing_slash(self) -> None:
        integration = CoinSwarmIntegration(url="http://localhost:8080/")
        assert integration._url == "http://localhost:8080"

    def test_no_event_bus_by_default(self) -> None:
        integration = CoinSwarmIntegration()
        assert integration._bus is None


class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/status"
            return httpx.Response(200, json={"agents": []})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.get_status()
        assert result == {"agents": []}

    @pytest.mark.asyncio
    async def test_raises_on_error_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        with pytest.raises(httpx.HTTPStatusError):
            await integration.get_status()


class TestListAgents:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/agents"
            return httpx.Response(200, json=[{"id": "a1"}])

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.list_agents()
        assert result == [{"id": "a1"}]


class TestGetAgent:
    @pytest.mark.asyncio
    async def test_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/agents/a1"
            return httpx.Response(200, json={"id": "a1", "fitness": 0.9})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.get_agent("a1")
        assert result == {"id": "a1", "fitness": 0.9}


class TestTriggerBacktest:
    @pytest.mark.asyncio
    async def test_posts_with_agent_id_and_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"ok": True})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.trigger_backtest("a1", config={"window": 30})
        assert result == {"ok": True}
        assert captured["url"] == "http://sw/actions/backtest/canonical"
        assert captured["body"] == {"agent_id": "a1", "window": 30}

    @pytest.mark.asyncio
    async def test_defaults_config_to_empty_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["body"] = json.loads(request.read())
            return httpx.Response(200, json={"ok": True})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        await integration.trigger_backtest("a1")
        assert captured["body"] == {"agent_id": "a1"}


class TestTriggerEvolution:
    @pytest.mark.asyncio
    async def test_posts_and_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/system/evolution/trigger"
            return httpx.Response(200, json={"generation": 5})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.trigger_evolution()
        assert result == {"generation": 5}


class TestPauseAgent:
    @pytest.mark.asyncio
    async def test_posts_and_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/agents/a1/pause"
            return httpx.Response(200, json={"status": "paused"})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.pause_agent("a1")
        assert result == {"status": "paused"}


class TestResumeAgent:
    @pytest.mark.asyncio
    async def test_posts_and_returns_json(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "http://sw/agents/a1/resume"
            return httpx.Response(200, json={"status": "resumed"})

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        result = await integration.resume_agent("a1")
        assert result == {"status": "resumed"}


class TestEmitAgentFitness:
    @pytest.mark.asyncio
    async def test_noop_when_no_bus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call get_agent when bus is None")

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        await integration.emit_agent_fitness("a1")

    @pytest.mark.asyncio
    async def test_emits_event_with_agent_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"fitness": 0.7, "sortino": 1.2, "alpha": 0.05, "status": "active"},
            )

        _patched_client(monkeypatch, handler)
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        await integration.emit_agent_fitness("a1")

        bus.emit.assert_awaited_once()
        event: Event = bus.emit.await_args.args[0]
        assert event.category == EventCategory.TRADING
        assert event.event_type == "agent_fitness"
        assert event.source == "coinswarm"
        assert event.payload == {
            "agent_id": "a1",
            "fitness": 0.7,
            "sortino": 1.2,
            "alpha": 0.05,
            "status": "active",
        }

    @pytest.mark.asyncio
    async def test_defaults_missing_agent_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        _patched_client(monkeypatch, handler)
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        await integration.emit_agent_fitness("a1")

        event: Event = bus.emit.await_args.args[0]
        assert event.payload == {
            "agent_id": "a1",
            "fitness": 0.0,
            "sortino": 0.0,
            "alpha": 0.0,
            "status": "unknown",
        }


class TestEmitEvolutionResult:
    @pytest.mark.asyncio
    async def test_noop_when_no_bus(self) -> None:
        integration = CoinSwarmIntegration(url="http://sw")
        await integration.emit_evolution_result({"generation": 1})

    @pytest.mark.asyncio
    async def test_emits_event_with_result_fields(self) -> None:
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        await integration.emit_evolution_result(
            {
                "generation": 3,
                "best_fitness": 0.95,
                "agents_created": 2,
                "agents_demoted": 1,
            }
        )

        event: Event = bus.emit.await_args.args[0]
        assert event.category == EventCategory.TRADING
        assert event.event_type == "evolution_cycle_complete"
        assert event.source == "coinswarm"
        assert event.payload == {
            "generation": 3,
            "best_fitness": 0.95,
            "agents_created": 2,
            "agents_demoted": 1,
        }

    @pytest.mark.asyncio
    async def test_defaults_missing_result_fields(self) -> None:
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        await integration.emit_evolution_result({})

        event: Event = bus.emit.await_args.args[0]
        assert event.payload == {
            "generation": 0,
            "best_fitness": 0.0,
            "agents_created": 0,
            "agents_demoted": 0,
        }


class TestPollAndEmit:
    @pytest.mark.asyncio
    async def test_returns_zero_when_no_bus(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("should not call get_status when bus is None")

        _patched_client(monkeypatch, handler)
        integration = CoinSwarmIntegration(url="http://sw")
        assert await integration.poll_and_emit() == 0

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_agents_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        _patched_client(monkeypatch, handler)
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        assert await integration.poll_and_emit() == 0
        bus.emit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_emits_one_event_per_agent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "agents": [
                        {"id": "a1", "fitness": 0.5, "sortino": 1.0, "status": "active"},
                        {"id": "a2"},
                    ]
                },
            )

        _patched_client(monkeypatch, handler)
        bus = AsyncMock()
        integration = CoinSwarmIntegration(url="http://sw", event_bus=bus)
        count = await integration.poll_and_emit()

        assert count == 2
        assert bus.emit.await_count == 2
        first_event: Event = bus.emit.await_args_list[0].args[0]
        assert first_event.payload == {
            "agent_id": "a1",
            "fitness": 0.5,
            "sortino": 1.0,
            "status": "active",
        }
        second_event: Event = bus.emit.await_args_list[1].args[0]
        assert second_event.payload == {
            "agent_id": "a2",
            "fitness": 0.0,
            "sortino": 0.0,
            "status": "unknown",
        }
