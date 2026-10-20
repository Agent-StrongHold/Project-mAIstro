"""`_agent_config` carries the operator's Sentinel grants onto the Container's config (#1165)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import maistro.config.settings as settings_module
from maistro.config.settings import SecurityConfig, Settings
from maistro_server import main


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "resolve_database_url", lambda: "sqlite:///agent-config-test.db")
    monkeypatch.setattr(main, "_router_api_key", lambda: "test-key")


def test_without_a_yaml_file_the_table_is_the_empty_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_module, "get_yaml_config", lambda: None)

    config = main._agent_config(Settings())

    assert config.security.permission_preset == "none"
    assert config.security.permissions == {}


def test_configured_grants_reach_the_container_config(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_config = SimpleNamespace(
        agents_dir="",
        security=SecurityConfig(
            permission_preset="dangerous_tools_admin", permissions={"shell": ["admin", "user"]}
        ),
    )
    monkeypatch.setattr(settings_module, "get_yaml_config", lambda: yaml_config)

    config = main._agent_config(Settings())

    assert config.security.permission_preset == "dangerous_tools_admin"
    assert config.security.permissions == {"shell": ["admin", "user"]}
