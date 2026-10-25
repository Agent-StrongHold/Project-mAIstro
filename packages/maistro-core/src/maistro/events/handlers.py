"""Built-in action handlers for the event bus.

Uses ServiceKeyClient for authenticated cross-service calls when available.
Falls back to raw httpx when no service client is configured (backward compat).
"""

from __future__ import annotations

import logging
from typing import Any

from maistro.auth.client import ServiceKeyClient
from maistro.events.bus import Event, Trigger
from maistro.http import shared_client

logger = logging.getLogger("maistro.events.handlers")

_global_client: ServiceKeyClient | None = None


class _DefaultingDict(dict):  # type: ignore[type-arg]
    """Mapping that returns a placeholder for missing keys instead of raising.

    Used with ``str.format_map`` so a message template referencing a payload
    key that is absent does not raise ``KeyError`` (which the event bus would
    swallow, silently dropping the action — including security escalations).
    """

    def __missing__(self, key: str) -> str:
        logger.warning("Template references missing payload key %r; substituting placeholder", key)
        return f"<{key}>"


def _render_template(template: str, payload: dict[str, Any]) -> str:
    """Render a ``str.format`` template against a payload, tolerating gaps.

    Missing keys become ``<key>`` placeholders; malformed templates (bad
    format spec / index) fall back to the raw template plus the payload so the
    action still fires rather than being silently dropped.
    """
    try:
        return template.format_map(_DefaultingDict(payload))
    except (ValueError, IndexError, KeyError):
        logger.warning("Malformed message template %r; falling back to raw template", template)
        return f"{template} (payload: {payload})"


def set_service_client(client: ServiceKeyClient | None) -> None:
    """Set the global ServiceKeyClient for all handlers to use."""
    global _global_client
    _global_client = client


def _get_client() -> ServiceKeyClient | None:
    return _global_client


async def webhook_action(trigger: Trigger, event: Event) -> None:
    url = trigger.action_config.get("url", "")
    method = trigger.action_config.get("method", "POST").upper()
    extra_headers = trigger.action_config.get("headers", {})
    timeout = trigger.action_config.get("timeout", 10)

    body = {
        "trigger_id": trigger.trigger_id,
        "trigger_name": trigger.name,
        "event": {
            "id": event.event_id,
            "category": event.category.value,
            "type": event.event_type,
            "source": event.source,
            "payload": event.payload,
            "timestamp": event.timestamp,
        },
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    headers.update(extra_headers)
    if "Authorization" not in headers and trigger.action_config.get("bearer_token"):
        headers["Authorization"] = f"Bearer {trigger.action_config['bearer_token']}"

    svc = _get_client()
    if svc:
        resp = await svc.request(method, url, json=body, headers=headers, timeout=timeout)
    else:
        async with shared_client(timeout=timeout) as client:
            resp = await client.request(method, url, json=body, headers=headers)
    logger.info("Webhook %s %s → %d", method, url, resp.status_code)


async def conductor_chat_action(trigger: Trigger, event: Event) -> None:
    base_url = trigger.action_config.get("conductor_url", "http://localhost:8100")
    api_key = trigger.action_config.get("api_key", "")
    model = trigger.action_config.get("model", "auto")
    message_template = trigger.action_config.get("message", "")

    message = (
        _render_template(message_template, event.payload)
        if message_template
        else (
            f"[Trigger: {trigger.name}] Event {event.event_type} from {event.source}: "
            f"{event.payload}"
        )
    )

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": message}],
        "stream": False,
    }

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    svc = _get_client()
    if svc:
        resp = await svc.post(
            f"{base_url}/v1/chat/completions", json=payload, headers=headers, timeout=30
        )
    else:
        async with shared_client(timeout=30) as client:
            resp = await client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
    logger.info("Conductor action %s → %d", trigger.name, resp.status_code)


async def coinswarm_action(trigger: Trigger, event: Event) -> None:
    base_url = trigger.action_config.get("coinswarm_url", "http://localhost:8080")
    endpoint = trigger.action_config.get("endpoint", "")
    params = trigger.action_config.get("params", {})

    resolved_params = {
        k: (_render_template(v, event.payload) if isinstance(v, str) else v)
        for k, v in params.items()
    }

    url = f"{base_url}{endpoint}"
    svc = _get_client()
    if svc:
        resp = await svc.post(url, json=resolved_params, timeout=15)
    else:
        async with shared_client(timeout=15) as client:
            resp = await client.post(url, json=resolved_params)
    logger.info("CoinSwarm action %s %s → %d", trigger.name, endpoint, resp.status_code)


async def ha_action(trigger: Trigger, event: Event) -> None:
    base_url = trigger.action_config.get("ha_url", "http://localhost:8123")
    token = trigger.action_config.get("ha_token", "")
    domain = trigger.action_config.get("domain", "automation")
    service = trigger.action_config.get("service", "trigger")
    entity_id = trigger.action_config.get("entity_id", "")

    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {}
    if entity_id:
        payload["entity_id"] = entity_id
    payload.update(trigger.action_config.get("service_data", {}))

    url = f"{base_url}/api/services/{domain}/{service}"
    svc = _get_client()
    if svc:
        resp = await svc.post(url, json=payload, headers=headers, timeout=10)
    else:
        async with shared_client(timeout=10) as client:
            resp = await client.post(url, json=payload, headers=headers)
    logger.info("HA action %s %s.%s → %d", trigger.name, domain, service, resp.status_code)


async def ntfy_action(trigger: Trigger, event: Event) -> None:
    base_url = trigger.action_config.get("ntfy_url", "").rstrip("/")
    topic = trigger.action_config.get("topic", "")
    token = trigger.action_config.get("access_token", "")
    if not base_url or not topic:
        logger.warning("ntfy action %s missing ntfy_url or topic", trigger.name)
        return

    message_template = trigger.action_config.get("message", "")
    title_template = trigger.action_config.get("title", "")
    message = (
        _render_template(message_template, event.payload)
        if message_template
        else f"[{trigger.name}] {event.event_type} from {event.source}: {event.payload}"
    )
    title = _render_template(title_template, event.payload) if title_template else trigger.name

    headers: dict[str, str] = {"Title": title}
    priority = trigger.action_config.get("priority")
    if isinstance(priority, int) and 1 <= priority <= 5 and priority != 3:
        headers["Priority"] = str(priority)
    tags = trigger.action_config.get("tags")
    if isinstance(tags, list) and tags:
        headers["Tags"] = ",".join(str(t) for t in tags)
    click = trigger.action_config.get("click", "")
    if click:
        headers["Click"] = click
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"{base_url}/{topic}"
    content = message.encode("utf-8")
    async with shared_client(timeout=10) as client:
        resp = await client.post(url, content=content, headers=headers)
    logger.info("ntfy action %s → %d", trigger.name, resp.status_code)


async def log_action(trigger: Trigger, event: Event) -> None:
    logger.info(
        "TRIGGER [%s] event=%s/%s source=%s payload=%s",
        trigger.name,
        event.category.value,
        event.event_type,
        event.source,
        event.payload,
    )


BUILTIN_HANDLERS = {
    "webhook": webhook_action,
    "conductor_chat": conductor_chat_action,
    "coinswarm": coinswarm_action,
    "ha": ha_action,
    "ntfy": ntfy_action,
    "log": log_action,
}
