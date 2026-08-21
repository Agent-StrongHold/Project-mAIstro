"""Tests for the static task_type -> agent_name intent registry."""

from __future__ import annotations

import pytest

from maistro.agents.intents import (
    IntentRegistry,
    build_intent_registry,
    poc_mode_from_env,
)


@pytest.fixture(autouse=True)
def _clear_poc_mode_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAISTRO_POC_MODE", raising=False)


class TestPocModeFromEnv:
    def test_unset_returns_empty_string(self) -> None:
        assert poc_mode_from_env() == ""

    def test_strips_and_lowercases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_POC_MODE", "  PM  ")
        assert poc_mode_from_env() == "pm"


class TestBuildIntentRegistry:
    def test_pm_mode_explicit_arg_uses_pm_routing(self) -> None:
        registry = build_intent_registry("pm")
        assert registry.get_agent_for_intent("intake") == "intake"
        assert registry.get_agent_for_intent("code") is None

    def test_default_mode_uses_engineering_routing(self) -> None:
        registry = build_intent_registry("engineering")
        assert registry.get_agent_for_intent("code") == "artificer"
        assert registry.get_agent_for_intent("intake") is None

    def test_none_mode_falls_back_to_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        registry = build_intent_registry(None)
        assert registry.get_agent_for_intent("program_management") == "program_manager"

    def test_no_arg_no_env_uses_engineering_default(self) -> None:
        registry = build_intent_registry()
        assert registry.get_agent_for_intent("search") == "ranger"

    def test_mode_arg_is_stripped_and_lowercased(self) -> None:
        registry = build_intent_registry("  PM  ")
        assert registry.get_agent_for_intent("risk") == "risk_dependency"


class TestIntentRegistry:
    def test_default_table_is_engineering_routing(self) -> None:
        registry = IntentRegistry()
        assert registry.get_agent_for_intent("creative") == "scribe"

    def test_custom_table_used_when_provided(self) -> None:
        registry = IntentRegistry({"custom": "agent-x"})
        assert registry.get_agent_for_intent("custom") == "agent-x"
        assert registry.get_agent_for_intent("code") is None

    def test_get_agent_for_intent_unknown_returns_none(self) -> None:
        registry = IntentRegistry({})
        assert registry.get_agent_for_intent("unknown") is None

    def test_resolve_known_task_type(self) -> None:
        registry = IntentRegistry({"code": "artificer"})
        assert registry.resolve("code") == "artificer"

    def test_resolve_unknown_defaults_to_artificer_in_engineering_mode(self) -> None:
        registry = IntentRegistry({})
        assert registry.resolve("unknown") == "artificer"

    def test_resolve_unknown_defaults_to_intake_in_pm_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAISTRO_POC_MODE", "pm")
        registry = IntentRegistry({})
        assert registry.resolve("unknown") == "intake"

    def test_register_adds_new_mapping(self) -> None:
        registry = IntentRegistry({})
        registry.register("new_type", "new_agent")
        assert registry.get_agent_for_intent("new_type") == "new_agent"

    def test_register_overwrites_existing_mapping(self) -> None:
        registry = IntentRegistry({"code": "artificer"})
        registry.register("code", "mason")
        assert registry.get_agent_for_intent("code") == "mason"
