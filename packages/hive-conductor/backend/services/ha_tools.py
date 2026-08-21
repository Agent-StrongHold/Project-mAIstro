from __future__ import annotations

import logging
import os
from typing import Any

from maistro.http import shared_client

logger = logging.getLogger(__name__)

HA_URL = os.environ.get("HA_URL", "").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
HC_EXTERNAL_URL = os.environ.get("HC_EXTERNAL_URL", "http://localhost:8101").rstrip("/")

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
                "name": "ha_confirm",
                "description": "Send an approve/deny confirmation prompt to a phone via Home Assistant push notification. Returns once the user responds or after timeout.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "The question or action to confirm",
                        },
                        "target": {
                            "type": "string",
                            "enum": ["blake", "bella", "lilly"],
                            "description": "Which person to send to",
                        },
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Seconds to wait for response (default 120)",
                            "minimum": 10,
                            "maximum": 600,
                        },
                    },
                    "required": ["message", "target"],
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


_TARGET_MAP = {
    "blake": "notify.mobile_app_blakes_iphone",
    "bella": "notify.mobile_app_bellas_iphone",
    "lilly": "notify.mobile_app_lillys_iphone",
}


_CONFIRM_RESULTS: dict[str, str] = {}

_PENDING_CONFIRMS: dict[str, dict] = {}


def get_pending_confirms() -> list[dict]:
    return [
        {**v, "confirm_id": k} for k, v in _PENDING_CONFIRMS.items() if v.get("status") == "pending"
    ]


def get_all_confirms() -> list[dict]:
    results = []
    for k, v in _PENDING_CONFIRMS.items():
        results.append({**v, "confirm_id": k})
    for k, v in _CONFIRM_RESULTS.items():
        if k not in _PENDING_CONFIRMS:
            results.append({"confirm_id": k, "status": "resolved", "result": v})
    return results


async def respond_confirm(confirm_id: str, response: str) -> dict:
    if response not in ("approved", "denied"):
        return {"error": "response must be approved or denied"}
    if confirm_id not in _PENDING_CONFIRMS:
        if confirm_id in _CONFIRM_RESULTS:
            return {"error": "already resolved", "result": _CONFIRM_RESULTS[confirm_id]}
        return {"error": "unknown confirm_id"}
    entry = _PENDING_CONFIRMS[confirm_id]
    state_entity = entry.get("state_entity", "")
    if state_entity:
        await _set_state(state_entity, response)
    _CONFIRM_RESULTS[confirm_id] = response
    entry["status"] = "resolved"
    entry["result"] = response
    return {"result": response, "confirm_id": confirm_id}


async def _fire_event(event_type: str, event_data: dict) -> None:
    try:
        async with shared_client(timeout=5.0) as c:
            await c.post(
                f"{HA_URL}/api/events/{event_type}",
                headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
                json=event_data,
            )
    except Exception:
        logger.debug("Failed to fire HA event %s", event_type, exc_info=True)


async def _set_state(entity_id: str, state: str, attributes: dict | None = None) -> None:
    try:
        async with shared_client(timeout=5.0) as c:
            await c.post(
                f"{HA_URL}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
                json={"state": state, "attributes": attributes or {}},
            )
    except Exception:
        logger.debug("Failed to set HA state %s", entity_id, exc_info=True)


async def _get_state(entity_id: str) -> str | None:
    try:
        async with shared_client(timeout=5.0) as c:
            r = await c.get(
                f"{HA_URL}/api/states/{entity_id}",
                headers={"Authorization": f"Bearer {HA_TOKEN}"},
            )
            if r.status_code == 200:
                return r.json().get("state")
    except Exception as _exc:
        __import__("logging").getLogger("hive.services.ha_tools").warning(
            "error_swallowed file=%s line=%d: %s",
            "packages/hive-conductor/backend/services/ha_tools.py",
            258,
            _exc,
        )
        pass
    return None


async def _ensure_confirm_helper_automation() -> bool:
    return True


async def send_confirm(message: str, target: str, timeout_seconds: int = 120) -> dict:
    import asyncio

    notify_service = _TARGET_MAP.get(target.lower())
    if not notify_service:
        return {"error": f"unknown target: {target}. Use blake, bella, or lilly."}

    confirm_id = f"hc_{os.urandom(4).hex()}"
    domain, service = notify_service.split(".", 1)
    state_entity = f"input_text.hc_confirm_{confirm_id}"

    _PENDING_CONFIRMS[confirm_id] = {
        "status": "pending",
        "message": message,
        "target": target,
        "state_entity": state_entity,
        "created_at": __import__("time").time(),
        "timeout_seconds": timeout_seconds,
    }

    await _set_state(
        state_entity,
        "pending",
        {"friendly_name": f"HC Confirm {confirm_id}", "confirm_id": confirm_id},
    )

    try:
        async with shared_client(timeout=10.0) as c:
            await c.post(
                f"{HA_URL}/api/services/{domain}/{service}",
                headers={"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"},
                json={
                    "title": "Hive Conductor",
                    "message": message,
                    "data": {
                        "url": f"{HC_EXTERNAL_URL}/#/dashboard",
                        "actions": [
                            {"action": f"{confirm_id}_APPROVE", "title": "Approve"},
                            {"action": f"{confirm_id}_DENY", "title": "Deny"},
                        ],
                        "push": {"sound": {"name": "default", "critical": 0}},
                    },
                },
            )
    except Exception as e:
        return {"error": f"failed to send notification: {e}"}

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(3)
        current = await _get_state(state_entity)
        if current in ("approved", "denied"):
            try:
                async with shared_client(timeout=5.0) as _c:
                    await _c.delete(
                        f"{HA_URL}/api/states/{state_entity}",
                        headers={"Authorization": f"Bearer {HA_TOKEN}"},
                    )
            except Exception as exc:
                import logging as _logging

                _logging.getLogger("hive.ha_tools").warning(
                    "ha_state_cleanup_failed entity=%s: %s",
                    state_entity,
                    exc,
                )
            return {"result": current, "confirm_id": confirm_id}

        try:
            async with shared_client(timeout=5.0) as _c:
                r = await _c.get(
                    f"{HA_URL}/api/events/mobile_app_notification_action",
                    headers={"Authorization": f"Bearer {HA_TOKEN}"},
                    params={"timeout": 1},
                )
                if r.status_code == 200:
                    for event in r.json():
                        ed = event.get("data", {})
                        action_name = ed.get("action", "")
                        if confirm_id in action_name:
                            result = "approved" if "APPROVE" in action_name.upper() else "denied"
                            await _set_state(state_entity, result)
                            _CONFIRM_RESULTS[confirm_id] = result
                            return {"result": result, "confirm_id": confirm_id}
        except Exception as exc:
            import logging as _logging

            _logging.getLogger("hive.ha_tools").warning(
                "ha_event_poll_failed: %s",
                exc,
            )

    return {"result": "timeout", "confirm_id": confirm_id}
