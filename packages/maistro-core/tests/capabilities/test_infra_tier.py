from __future__ import annotations

import pytest

from maistro.capabilities.slots.infra import ActionTier, tier_for


@pytest.mark.parametrize(
    "action,params,expected",
    [
        ("docker_logs", {}, ActionTier.READ),
        ("ollama_list", {}, ActionTier.READ),
        ("snapraid_status", {}, ActionTier.READ),
        ("restart_container", {"name": "x"}, ActionTier.REVERSIBLE),
        ("restart_service", {"name": "ollama"}, ActionTier.REVERSIBLE),
        ("ollama_pull", {"model": "qwen"}, ActionTier.REVERSIBLE),
        ("vm_control", {"action": "start", "vmid": "102"}, ActionTier.REVERSIBLE),
        ("vm_control", {"action": "status", "vmid": "102"}, ActionTier.READ),
        ("vm_control", {"action": "stop", "vmid": "102"}, ActionTier.DESTRUCTIVE),
        ("vm_control", {"action": "reboot", "vmid": "102"}, ActionTier.DESTRUCTIVE),
        ("restart_stack", {"name": "traefik"}, ActionTier.DESTRUCTIVE),
        ("docker_prune", {}, ActionTier.DESTRUCTIVE),
    ],
)
def test_tier_for(action, params, expected):
    assert tier_for(action, params) == expected


def test_unknown_action_is_destructive_by_default():
    assert tier_for("rm_rf_everything", {}) == ActionTier.DESTRUCTIVE
