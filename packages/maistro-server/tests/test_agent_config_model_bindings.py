"""Production config-threading proof for `model_bindings` (#1079 Finding 1).

Codex flagged that `AgentConfig.model_bindings` -- the declared-authorization
surface `bootstrap_model_bindings()` reads -- had no shipped production path
that populated it: `MaistroYamlConfig` had no `model_bindings` field, and
`maistro_server.main._agent_config()` built `AgentConfig` without it, so the
server always reached `create_container()` with an empty, fail-closed list
regardless of what an operator wrote in `maistro.yaml`.

This is the real (non-fake) end-to-end proof of the fix: an actual YAML file
on disk, read by the real `load_yaml_config()` loader (not a `SimpleNamespace`
stand-in), fed through the real `_agent_config()`, and handed to a real
`create_container()` -- then the declared Binding is resolved through the
live Container the way a `llm.summarize` node would reach it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import maistro.config.settings as settings_module
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.config.loader import load_yaml_config
from maistro.config.settings import Settings
from maistro.container import create_container
from maistro_server import main


@pytest.fixture(autouse=True)
def _no_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep the Container fully in-memory -- this test proves config threading,
    # not persistence.
    monkeypatch.setattr(main, "resolve_database_url", lambda: "")
    monkeypatch.setattr(main, "_router_api_key", lambda: "test-key")


@pytest.fixture(autouse=True)
def _reset_yaml_config_singleton() -> None:
    """`load_yaml_config` sets a process-wide singleton; do not leak it."""
    yield
    settings_module.set_yaml_config(None)


def _write_yaml_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "maistro.yaml"
    config_path.write_text(
        "router_api_key: test-key\n"
        "model_bindings:\n"
        "  - binding_id: prod-summarize\n"
        "    project_id: proj-a\n"
        "    provider_name: gpt-4\n"
        "  - binding_id: prod-summarize-other-ws\n"
        "    project_id: proj-b\n"
        "    workspace_id: ws-explicit\n"
        "    provider_name: gpt-4-mini\n",
        encoding="utf-8",
    )
    return config_path


def test_without_a_yaml_file_model_bindings_is_the_empty_fail_closed_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings_module, "get_yaml_config", lambda: None)

    config = main._agent_config(Settings())

    assert config.model_bindings == []


def test_yaml_declared_bindings_reach_agent_config(tmp_path: Path) -> None:
    config_path = _write_yaml_config(tmp_path)

    load_yaml_config(config_path)
    config = main._agent_config(Settings())

    assert [b.binding_id for b in config.model_bindings] == [
        "prod-summarize",
        "prod-summarize-other-ws",
    ]
    assert config.model_bindings[0].project_id == "proj-a"
    assert config.model_bindings[0].provider_name == "gpt-4"
    assert config.model_bindings[1].workspace_id == "ws-explicit"


async def test_yaml_declared_bindings_are_resolvable_through_a_real_container(
    tmp_path: Path,
) -> None:
    """End to end: YAML file -> `_agent_config()` -> `create_container()` ->
    the Binding a `llm.summarize` node would actually resolve."""

    config_path = _write_yaml_config(tmp_path)
    load_yaml_config(config_path)
    config = main._agent_config(Settings())
    # This deployment's default Workspace, so the first Binding's blank
    # `workspace_id` inherits it.
    config = config.model_copy(update={"workspace_id": "default"})

    container = await create_container(config)

    inherited = await container.capability_effects.bindings.resolve(
        "prod-summarize",
        workspace_id="default",
        project_id="proj-a",
        node_id="summarize",
        capability=MODEL_CHAT_CAPABILITY,
    )
    explicit = await container.capability_effects.bindings.resolve(
        "prod-summarize-other-ws",
        workspace_id="ws-explicit",
        project_id="proj-b",
        node_id="summarize",
        capability=MODEL_CHAT_CAPABILITY,
    )

    assert inherited.workspace_id == "default"
    assert inherited.provider_name == "gpt-4"
    assert explicit.workspace_id == "ws-explicit"
    assert explicit.provider_name == "gpt-4-mini"
