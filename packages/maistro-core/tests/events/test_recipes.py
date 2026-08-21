"""Tests for maistro.events.recipes pre-built trigger factories."""

from __future__ import annotations

from maistro.events.recipes import (
    ha_device_triggers_conductor,
    turing_reflection_trigger,
)


class TestHaDeviceTriggersConductor:
    def test_builds_trigger_named_after_entity_id(self) -> None:
        trigger = ha_device_triggers_conductor(entity_id="sensor.front_door")
        assert trigger.name == "ha-sensor.front_door-trigger"
        assert trigger.conditions[0].value == "sensor.front_door"

    def test_default_message_references_entity_id_when_not_provided(self) -> None:
        trigger = ha_device_triggers_conductor(entity_id="sensor.front_door")
        assert "sensor.front_door" in trigger.action_config["message"]

    def test_explicit_message_overrides_default(self) -> None:
        trigger = ha_device_triggers_conductor(entity_id="sensor.front_door", message="custom")
        assert trigger.action_config["message"] == "custom"


class TestTuringReflectionTrigger:
    def test_builds_webhook_trigger_with_url(self) -> None:
        trigger = turing_reflection_trigger(turing_url="http://turing.local")
        assert trigger.action_type == "webhook"
        assert trigger.action_config["url"] == "http://turing.local/api/reflect"
        assert trigger.action_config["method"] == "POST"
