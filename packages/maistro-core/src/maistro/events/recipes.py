"""Pre-built trigger recipes for common cross-service integrations.

Service key auth handled by ServiceKeyClient (set via handlers.set_service_client).
Import and register what you need, or use as templates.
"""

from __future__ import annotations

from maistro.events.bus import Trigger, TriggerCondition


def coinswarm_fitness_alert(
    conductor_url: str = "http://localhost:8100",
    conductor_api_key: str = "",
    fitness_threshold: float = 0.3,
) -> Trigger:
    return Trigger(
        name="coinswarm-low-fitness",
        event_types=["agent_fitness"],
        conditions=[
            TriggerCondition(field="fitness", op="lt", value=fitness_threshold),
        ],
        action_type="conductor_chat",
        action_config={
            "conductor_url": conductor_url,
            "api_key": conductor_api_key,
            "message": (
                "CoinSwarm agent {agent_id} fitness dropped to {fitness:.2f}. "
                "Review and consider demotion or parameter adjustment."
            ),
        },
    )


def coinswarm_drawdown_alert(
    conductor_url: str = "http://localhost:8100",
    conductor_api_key: str = "",
    max_drawdown: float = 0.15,
) -> Trigger:
    return Trigger(
        name="coinswash-drawdown-warning",
        event_types=["drawdown"],
        conditions=[
            TriggerCondition(field="drawdown_pct", op="gt", value=max_drawdown),
        ],
        action_type="conductor_chat",
        action_config={
            "conductor_url": conductor_url,
            "api_key": conductor_api_key,
            "message": (
                "CoinSwarm drawdown alert: {drawdown_pct:.1%} on agent {agent_id}. "
                "Consider pausing or reducing position size."
            ),
        },
    )


def coinswarm_evolution_complete(
    ha_url: str = "http://localhost:8123",
    ha_token: str = "",  # nosec B107 — empty-string default; real token comes from caller
    entity_id: str = "sensor.coinswarm_evolution_status",
) -> Trigger:
    return Trigger(
        name="coinswarm-evolution-done",
        event_types=["evolution_cycle_complete"],
        conditions=[],
        action_type="ha",
        action_config={
            "ha_url": ha_url,
            "ha_token": ha_token,
            "domain": "input_number",
            "service": "set_value",
            "entity_id": entity_id,
            "service_data": {"value": "{best_fitness}"},
        },
    )


def ha_device_triggers_conductor(
    conductor_url: str = "http://localhost:8100",
    conductor_api_key: str = "",
    entity_id: str = "",
    message: str = "",
) -> Trigger:
    return Trigger(
        name=f"ha-{entity_id}-trigger",
        event_types=["state_changed"],
        conditions=[
            TriggerCondition(field="entity_id", op="eq", value=entity_id),
        ],
        action_type="conductor_chat",
        action_config={
            "conductor_url": conductor_url,
            "api_key": conductor_api_key,
            "message": message or f"Home Assistant: {entity_id} changed to {{new_state}}",
        },
    )


def turing_reflection_trigger(
    turing_url: str = "http://localhost:9101",
) -> Trigger:
    return Trigger(
        name="turing-daily-reflection",
        event_types=["daily_schedule"],
        conditions=[],
        action_type="webhook",
        action_config={
            "url": f"{turing_url}/api/reflect",
            "method": "POST",
        },
    )


def security_event_escalation(
    conductor_url: str = "http://localhost:8100",
    conductor_api_key: str = "",
) -> Trigger:
    return Trigger(
        name="security-warden-block",
        event_types=["warden_block"],
        conditions=[
            TriggerCondition(field="severity", op="eq", value="high"),
        ],
        action_type="conductor_chat",
        action_config={
            "conductor_url": conductor_url,
            "api_key": conductor_api_key,
            "message": (
                "SECURITY: Warden blocked input from {source}. "
                "Flags: {flags}. Input preview: {preview}"
            ),
        },
    )
