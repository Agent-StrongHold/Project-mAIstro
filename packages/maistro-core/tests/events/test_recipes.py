"""Tests for maistro.events.recipes pre-built trigger factories."""

from __future__ import annotations

from maistro.events.bus import EventBus
from maistro.events.recipes import (
    BUILTIN_RECIPE_BUILDERS,
    ha_device_triggers_conductor,
    install_builtin_recipes,
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


class TestInstallBuiltinRecipes:
    def test_catalog_lands_disabled_by_default(self) -> None:
        bus = EventBus()
        installed = install_builtin_recipes(bus)
        assert len(installed) == len(BUILTIN_RECIPE_BUILDERS)
        assert all(not trigger.enabled for trigger in installed)
        assert all(not row["enabled"] for row in bus.list_triggers())

    def test_enabled_flag_arms_the_catalog(self) -> None:
        bus = EventBus()
        installed = install_builtin_recipes(bus, enabled=True)
        assert all(trigger.enabled for trigger in installed)
