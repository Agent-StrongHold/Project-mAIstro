"""Regression evidence for the shipped Agent roster contract (#840)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from maistro.agents.factory import (
    _build_identity_from_manifest,
    _load_preamble,
    _render_preamble,
    create_agents,
)
from maistro.types.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[4]
SHIPPED_AGENTS = REPO_ROOT / "agents"


class _PromptManager:
    async def upsert(self, name: str, body: str, label: str = "") -> None:
        del name, body, label


def _create_kwargs(agents_dir: Path, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "agents_dir": agents_dir,
        "prompt_manager": _PromptManager(),
        "llm": None,
        "context_builder": None,
        "warden": None,
        "sentinel": None,
        "learning_store": None,
        "learning_extractor": None,
        "outcome_store": None,
        "session_store": None,
        "quota_tracker": None,
        "tracer": None,
    }
    values.update(overrides)
    return values


def test_shipped_manifest_consumes_nested_delegation() -> None:
    manifest = yaml.safe_load((SHIPPED_AGENTS / "intake" / "agent.yaml").read_text())
    identity = _build_identity_from_manifest(manifest)
    assert identity.sub_agents == ("program_manager",)


def test_conflicting_legacy_and_canonical_delegation_fails_closed() -> None:
    manifest = {
        "name": "router",
        "delegation": {"sub_agents": ["canonical"]},
        "sub_agents": ["legacy"],
    }
    with pytest.raises(ConfigError, match="conflicts"):
        _build_identity_from_manifest(manifest)


def test_missing_preamble_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"PREAMBLE\.md"):
        _load_preamble(tmp_path)


def test_empty_preamble_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "PREAMBLE.md").write_text("\n")
    with pytest.raises(ConfigError, match="empty"):
        _load_preamble(tmp_path)


def test_shipped_preamble_renders_safety_context() -> None:
    template = _load_preamble(SHIPPED_AGENTS)
    rendered = _render_preamble(template, {"name": "intake", "description": "front door"})
    assert "approved tools only" in rendered
    assert "No cross-tenant data access" in rendered
    assert "governed dispatch and policy controls" in rendered


@pytest.mark.asyncio
async def test_required_roster_missing_is_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="required agents directory"):
        await create_agents(**_create_kwargs(tmp_path / "missing", require_agents=True))
