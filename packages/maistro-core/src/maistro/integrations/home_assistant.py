"""Home Assistant integration for the unified platform.

Direct HTTP to HA REST API. Emits state_change events.
Can be triggered BY events (event → HA action) or fire events FROM HA (webhook → emit).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from maistro.events.bus import Event, EventBus, EventCategory
from maistro.http import shared_client

logger = logging.getLogger("maistro.integrations.ha")


class HomeAssistantIntegration:
    def __init__(
        self,
        url: str = "http://localhost:8123",
        token: str = "",  # nosec B107 — empty-string default; real tokens come from env / caller
        event_bus: EventBus | None = None,
    ) -> None:
        self._url = url.rstrip("/")
        self._token = token
        self._bus = event_bus
        self._controllable_domains: set[str] = {
            "light",
            "switch",
            "fan",
            "climate",
            "cover",
            "media_player",
            "lock",
            "vacuum",
            "input_boolean",
            "script",
            "automation",
            "scene",
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    async def get_states(self) -> list[dict[str, Any]]:
        async with shared_client(timeout=10) as client:
            r = await client.get(f"{self._url}/api/states", headers=self._headers())
            r.raise_for_status()
            states: list[dict[str, Any]] = r.json()
            return states

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        async with shared_client(timeout=10) as client:
            r = await client.get(
                f"{self._url}/api/states/{entity_id}",
                headers=self._headers(),
            )
            if r.status_code == 404:
                return None
            r.raise_for_status()
            state: dict[str, Any] = r.json()
            return state

    async def call_service(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        payload = service_data or {}
        async with shared_client(timeout=10) as client:
            r = await client.post(
                f"{self._url}/api/services/{domain}/{service}",
                json=payload,
                headers=self._headers(),
            )
            r.raise_for_status()
            result: list[dict[str, Any]] = r.json()
            return result

    async def control_device(
        self,
        entity_id: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> str:
        domain = entity_id.split(".")[0]
        if domain not in self._controllable_domains:
            return f"Error: domain '{domain}' not controllable"

        service = action
        data: dict[str, Any] = {"entity_id": entity_id}
        if params:
            data.update(params)

        try:
            await self.call_service(domain, service, data)
            return f"OK: {entity_id} → {action}"
        except httpx.HTTPError as exc:
            return f"Error: {exc}"

    async def emit_state_changes(self) -> int:
        if self._bus is None:
            return 0

        states = await self.get_states()
        count = 0
        for state in states:
            await self._bus.emit(
                Event(
                    category=EventCategory.SMART_HOME,
                    event_type="ha_state",
                    source="home_assistant",
                    payload={
                        "entity_id": state["entity_id"],
                        "state": state["state"],
                        "attributes": state.get("attributes", {}),
                    },
                )
            )
            count += 1
        return count

    async def handle_webhook(self, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return

        await self._bus.emit(
            Event(
                category=EventCategory.SMART_HOME,
                event_type=payload.get("event_type", "webhook"),
                source="home_assistant",
                payload=payload,
            )
        )

    async def list_devices(self) -> list[dict[str, str]]:
        states = await self.get_states()
        return [
            {
                "entity_id": s["entity_id"],
                "state": s["state"],
                "friendly_name": s.get("attributes", {}).get("friendly_name", ""),
            }
            for s in states
            if s["entity_id"].split(".")[0] in self._controllable_domains
        ]
