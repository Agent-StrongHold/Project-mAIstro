"""Tests for maistro.graph.pm_domain."""

from __future__ import annotations

from maistro.graph.pm_domain import (
    PM_ROLES,
    build_capability_prompt,
    build_pm_graph_config,
)
from maistro.graph.types import AgentRole, GraphConfig


class TestBuildCapabilityPrompt:
    def test_known_capability_fills_payload_placeholder(self) -> None:
        prompt = build_capability_prompt("create_initiative", {"title": "x"})
        assert "Capability: create_initiative" in prompt
        assert '"title": "x"' in prompt

    def test_unknown_capability_falls_back_to_generic_template(self) -> None:
        prompt = build_capability_prompt("not_a_real_capability", {"foo": "bar"})
        assert "Capability: not_a_real_capability (no template registered)" in prompt
        assert '"foo": "bar"' in prompt


class TestBuildPmGraphConfig:
    def test_default_config_has_expected_topology(self) -> None:
        config = build_pm_graph_config()
        assert isinstance(config, GraphConfig)
        assert config.entry == AgentRole.INTAKE
        assert config.hyperagent == AgentRole.INTAKE
        assert config.max_cycles == 1
        assert config.use_llm_routing is False
        assert config.run_scout is False
        assert set(config.nodes) == set(PM_ROLES)
        assert len(config.edges) == 7

    def test_per_role_temperature_override_applies_to_node_config(self) -> None:
        config = build_pm_graph_config(
            max_cycles=3,
            per_role_temperature={AgentRole.INTAKE: 0.9},
        )
        assert config.max_cycles == 3
        assert config.node_configs[AgentRole.INTAKE].temperature == 0.9
        assert config.node_configs[AgentRole.PROGRAM_MANAGER].temperature == 0.2
