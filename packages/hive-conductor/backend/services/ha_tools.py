from __future__ import annotations

import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger(__name__)

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")

CONTROLLABLE = {
    "light",
    "switch",
    "fan",
    "lock",
    "cover",
    "climate",
    "input_boolean",
    "media_player",
}

_device_cache: list[dict] | None = None


def ha_available() -> bool:
    return bool(HA_URL and HA_TOKEN)


async def fetch_devices() -> list[dict]:
    global _device_cache
    if _device_cache is not None:
        return _device_cache
    if not ha_available():
        return []
    try:
        async with shared_client(timeout=10.0) as c:
            r = await c.get(
                f"{HA_URL}/api/states",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
            )
            r.raise_for_status()
            devices = [
                {
                    "entity_id": s["entity_id"],
                    "state": s["state"],
                    "name": s["attributes"].get("friendly_name", s["entity_id"]),
                    "domain": s["entity_id"].split(".")[0],
                }
                for s in r.json()
                if s["entity_id"].split(".")[0] in CONTROLLABLE
            ]
            _device_cache = devices
            return devices
    except Exception:
        logger.warning("Failed to fetch HA devices", exc_info=True)
        return []


def get_tool_definitions() -> list[dict]:
    if not ha_available():
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": "ha_control",
                "description": "Control Home Assistant devices. Use to turn on/off lights, fans, switches, locks, etc. For fans, use set_percentage with a value 0-100 to set speed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": [
                                "turn_on",
                                "turn_off",
                                "toggle",
                                "get_state",
                                "set_percentage",
                            ],
                            "description": "The action to perform. Use set_percentage for fan speed control.",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "The HA entity ID, e.g. 'fan.smartceilingfan', 'light.living_room'",
                        },
                        "percentage": {
                            "type": "integer",
                            "description": "For set_percentage: speed 0-100",
                            "minimum": 0,
                            "maximum": 100,
                        },
                    },
                    "required": ["action", "entity_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_announce",
                "description": "Announce a message on an Alexa/Echo device. Requires alexa_media_player integration.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "The text to speak"},
                        "target": {
                            "type": "string",
                            "description": "The Alexa device name, e.g. 'living_room'",
                        },
                    },
                    "required": ["message", "target"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "wait",
                "description": "Wait for a specified number of seconds before continuing. Use when the user asks to wait or delay between actions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type": "integer",
                            "description": "Number of seconds to wait",
                            "minimum": 1,
                            "maximum": 300,
                        },
                    },
                    "required": ["seconds"],
                },
            },
        },
    ]


async def execute_ha_tool(args: dict[str, Any]) -> dict[str, Any]:  # noqa: C901
    action = args.get("action", "")
    entity_id = args.get("entity_id", "")
    domain = entity_id.split(".")[0]

    if not entity_id or not action:
        return {"error": "missing action or entity_id"}

    if action == "get_state":
        try:
            async with shared_client(timeout=10.0) as c:
                r = await c.get(
                    f"{HA_URL}/api/states/{entity_id}",
                    headers={"Authorization": f"Bearer {HA_TOKEN}"},
                )
                r.raise_for_status()
                state = r.json()
                return {
                    "entity_id": state["entity_id"],
                    "state": state["state"],
                    "name": state["attributes"].get("friendly_name", ""),
                }
        except Exception as e:
            return {"error": str(e)}

    if action == "set_percentage":
        pct = args.get("percentage", 100)
        preset = {"low": "low", "medium": "medium", "high": "high"}.get(args.get("preset", ""))
        if not preset and pct <= 33:
            preset = "low"
        elif not preset and pct <= 66:
            preset = "medium"
        elif not preset:
            preset = "high"
        try:
            async with shared_client(timeout=10.0) as c:
                r = await c.post(
                    f"{HA_URL}/api/services/fan/set_preset_mode",
                    headers={
                        "Authorization": f"Bearer {HA_TOKEN}",
                        "Content-Type": "application/json",
                    },
                    json={"entity_id": entity_id, "preset_mode": preset},
                )
                r.raise_for_status()
                return {
                    "success": True,
                    "entity_id": entity_id,
                    "action": action,
                    "preset_mode": preset,
                    "percentage_requested": pct,
                }
        except Exception as e:
            return {"error": str(e), "entity_id": entity_id}

    service = action
    if action == "toggle":
        service = "toggle"
    elif action in ("turn_on", "turn_off"):
        service = action

    try:
        async with shared_client(timeout=10.0) as c:
            r = await c.post(
                f"{HA_URL}/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
                json={"entity_id": entity_id},
            )
            r.raise_for_status()
            return {"success": True, "entity_id": entity_id, "action": action}
    except Exception as e:
        return {"error": str(e), "entity_id": entity_id}
