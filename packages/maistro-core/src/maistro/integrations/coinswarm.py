"""CoinSwarm integration for the unified platform.

Talks to the Fast_Swarm API. Emits trading events (fitness, drawdown, evolution).
Can trigger CoinSwarm actions from other services (backtest, spawn agent, pause).
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.events.bus import Event, EventBus, EventCategory
from maistro.http import shared_client

logger = logging.getLogger("maistro.integrations.coinswarm")


class CoinSwarmIntegration:
    def __init__(
        self,
        url: str = "http://localhost:8080",
        event_bus: EventBus | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._bus = event_bus

    async def get_status(self) -> dict[str, Any]:
        async with shared_client(timeout=10) as client:
            r = await client.get(f"{self._url}/status")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def list_agents(self) -> list[dict[str, Any]]:
        async with shared_client(timeout=10) as client:
            r = await client.get(f"{self._url}/agents")
            r.raise_for_status()
            data: list[dict[str, Any]] = r.json()
            return data

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        async with shared_client(timeout=10) as client:
            r = await client.get(f"{self._url}/agents/{agent_id}")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def trigger_backtest(
        self, agent_id: str, config: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        async with shared_client(timeout=30) as client:
            r = await client.post(
                f"{self._url}/actions/backtest/canonical",
                json={"agent_id": agent_id, **(config or {})},
            )
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def trigger_evolution(self) -> dict[str, Any]:
        async with shared_client(timeout=60) as client:
            r = await client.post(f"{self._url}/system/evolution/trigger")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def pause_agent(self, agent_id: str) -> dict[str, Any]:
        async with shared_client(timeout=10) as client:
            r = await client.post(f"{self._url}/agents/{agent_id}/pause")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def resume_agent(self, agent_id: str) -> dict[str, Any]:
        async with shared_client(timeout=10) as client:
            r = await client.post(f"{self._url}/agents/{agent_id}/resume")
            r.raise_for_status()
            data: dict[str, Any] = r.json()
            return data

    async def emit_agent_fitness(self, agent_id: str) -> None:
        if self._bus is None:
            return

        agent = await self.get_agent(agent_id)
        await self._bus.emit(
            Event(
                category=EventCategory.TRADING,
                event_type="agent_fitness",
                source="coinswarm",
                payload={
                    "agent_id": agent_id,
                    "fitness": agent.get("fitness", 0.0),
                    "sortino": agent.get("sortino", 0.0),
                    "alpha": agent.get("alpha", 0.0),
                    "status": agent.get("status", "unknown"),
                },
            )
        )

    async def emit_evolution_result(self, result: dict[str, Any]) -> None:
        if self._bus is None:
            return

        await self._bus.emit(
            Event(
                category=EventCategory.TRADING,
                event_type="evolution_cycle_complete",
                source="coinswarm",
                payload={
                    "generation": result.get("generation", 0),
                    "best_fitness": result.get("best_fitness", 0.0),
                    "agents_created": result.get("agents_created", 0),
                    "agents_demoted": result.get("agents_demoted", 0),
                },
            )
        )

    async def poll_and_emit(self) -> int:
        if self._bus is None:
            return 0

        status = await self.get_status()
        count = 0

        if "agents" in status:
            for agent in status["agents"]:
                await self._bus.emit(
                    Event(
                        category=EventCategory.TRADING,
                        event_type="agent_status",
                        source="coinswarm",
                        payload={
                            "agent_id": agent.get("id", ""),
                            "fitness": agent.get("fitness", 0.0),
                            "sortino": agent.get("sortino", 0.0),
                            "status": agent.get("status", "unknown"),
                        },
                    )
                )
                count += 1

        return count
