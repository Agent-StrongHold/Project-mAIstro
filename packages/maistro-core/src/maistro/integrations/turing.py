"""Project Turing integration for the unified platform.

Talks to the Turing runtime. Emits self-model events (mood shifts, reflections, writings).
Can trigger Turing actions from other services (reflect, write, daydream).
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.events.bus import Event, EventBus, EventCategory
from maistro.http import shared_client

logger = logging.getLogger("maistro.integrations.turing")


class TuringIntegration:
    def __init__(
        self,
        chat_url: str = "http://localhost:9101",
        metrics_url: str = "http://localhost:9100",
        event_bus: EventBus | None = None,
    ) -> None:
        self._chat_url = chat_url.rstrip("/")
        self._metrics_url = metrics_url.rstrip("/")
        self._bus = event_bus

    async def chat(self, message: str, user: str = "system") -> str:
        async with shared_client(timeout=30) as client:
            r = await client.post(
                f"{self._chat_url}/api/chat",
                json={"message": message, "user": user},
            )
            r.raise_for_status()
            data = r.json()
            return str(data.get("response", ""))

    async def trigger_reflection(self, topic: str = "") -> str:
        return await self.chat(
            f"[System trigger] Please reflect on: {topic or 'your recent experiences and growth'}"
        )

    async def trigger_daydream(self) -> str:
        return await self.chat("[System trigger] Enter daydream mode. Let your mind wander.")

    async def trigger_writing(self, prompt: str) -> str:
        return await self.chat(f"[Writing trigger] {prompt}")

    async def get_metrics(self) -> dict[str, Any]:
        async with shared_client(timeout=10) as client:
            r = await client.get(f"{self._metrics_url}/metrics")
            r.raise_for_status()
            metrics: dict[str, Any] = r.json()
            return metrics

    async def emit_mood_event(self, mood_data: dict[str, Any]) -> None:
        if self._bus is None:
            return
        await self._bus.emit(
            Event(
                category=EventCategory.TURING,
                event_type="mood_shift",
                source="turing",
                payload=mood_data,
            )
        )

    async def emit_writing_event(self, writing_type: str, title: str, preview: str = "") -> None:
        if self._bus is None:
            return
        await self._bus.emit(
            Event(
                category=EventCategory.TURING,
                event_type="writing_complete",
                source="turing",
                payload={
                    "writing_type": writing_type,
                    "title": title,
                    "preview": preview[:200],
                },
            )
        )

    async def handle_coinswarm_event(self, event: Event) -> None:
        if event.event_type == "agent_fitness":
            fitness = event.payload.get("fitness", 0.0)
            agent_id = event.payload.get("agent_id", "")
            await self.chat(
                f"[Cross-service: CoinSwarm] Agent {agent_id} fitness is {fitness:.2f}. "
                f"What do you think about this? Any observations about the trading system?"
            )
        elif event.event_type == "evolution_cycle_complete":
            best = event.payload.get("best_fitness", 0.0)
            gen = event.payload.get("generation", 0)
            await self.chat(
                f"[Cross-service: CoinSwarm] Evolution cycle {gen} complete. "
                f"Best fitness: {best:.2f}. Reflect on what this means."
            )

    async def handle_ha_event(self, event: Event) -> None:
        entity_id = event.payload.get("entity_id", "")
        state = event.payload.get("state", "")
        friendly = event.payload.get("attributes", {}).get("friendly_name", entity_id)
        if entity_id.startswith(("sensor.", "binary_sensor.", "weather.")):
            await self.chat(
                f"[Cross-service: Home Assistant] {friendly} is now {state}. "
                f"Any thoughts or observations?"
            )
