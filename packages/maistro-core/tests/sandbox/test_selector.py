"""Tests for sandbox selector — fail-closed, tier ordering, policy enforcement."""

import pytest

from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.policy import (
    BENCHMARK_EVAL,
    DEV_ONLY,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    tier_satisfies,
)
from maistro.sandbox.protocol import SandboxProtocol
from maistro.sandbox.selector import NoSuitableBackendError, SandboxSelector


class _StubBackend(FakeSandboxBackend):
    """A backend that declares the tier it is registered at.

    These tests build multi-tier registries, and the old way to do that was
    `register("vm", FakeSandboxBackend())` — which is the fail-open #76 closed:
    a fake that satisfies `UNTRUSTED_CODE`. The scenarios are still the right
    ones, so they keep them and stop borrowing the hole to set them up.
    """

    def __init__(self, tier: str) -> None:
        super().__init__()
        self.tier = tier


def _backend(tier: str) -> SandboxProtocol:
    return _StubBackend(tier)


class TestTierSatisfies:
    def test_vm_satisfies_vm(self):
        assert tier_satisfies("vm", "vm") is True

    def test_vm_satisfies_container(self):
        assert tier_satisfies("vm", "container") is True

    def test_container_does_not_satisfy_vm(self):
        assert tier_satisfies("container", "vm") is False

    def test_fake_satisfies_fake(self):
        assert tier_satisfies("fake", "fake") is True

    def test_fake_does_not_satisfy_anything_real(self):
        assert tier_satisfies("fake", "container") is False
        assert tier_satisfies("fake", "vm") is False


class TestSelectorFailClosed:
    def test_empty_registry_refuses_any_workload(self):
        sel = SandboxSelector()
        with pytest.raises(NoSuitableBackendError):
            sel.select(UNTRUSTED_CODE)

    def test_fake_backend_refuses_untrusted_code(self):
        sel = SandboxSelector()
        sel.register("fake", FakeSandboxBackend())
        with pytest.raises(NoSuitableBackendError, match="min_tier='vm'"):
            sel.select(UNTRUSTED_CODE)

    def test_fake_backend_refuses_benchmark_eval(self):
        sel = SandboxSelector()
        sel.register("fake", FakeSandboxBackend())
        with pytest.raises(NoSuitableBackendError):
            sel.select(BENCHMARK_EVAL)

    def test_container_backend_refuses_vm_requirement(self):
        sel = SandboxSelector()
        sel.register("container", _backend("container"))
        with pytest.raises(NoSuitableBackendError):
            sel.select(UNTRUSTED_CODE)


class TestSelectorSelection:
    def test_fake_backend_accepts_dev_only(self):
        sel = SandboxSelector()
        sel.register("fake", FakeSandboxBackend())
        tier, _ = sel.select(DEV_ONLY)
        assert tier == "fake"

    def test_vm_backend_accepts_untrusted_code(self):
        sel = SandboxSelector()
        vm_backend = _backend("vm")
        sel.register("vm", vm_backend)
        tier, backend = sel.select(UNTRUSTED_CODE)
        assert tier == "vm"
        assert backend is vm_backend

    def test_strongest_available_is_chosen(self):
        sel = SandboxSelector()
        sel.register("container", _backend("container"))
        sel.register("vm", _backend("vm"))
        # For a TRUSTED_TOOL (min_tier=container), the VM is still chosen (strongest)
        tier, _ = sel.select(TRUSTED_TOOL)
        assert tier == "vm"

    def test_container_satisfies_trusted_tool(self):
        sel = SandboxSelector()
        sel.register("container", _backend("container"))
        tier, _ = sel.select(TRUSTED_TOOL)
        assert tier == "container"

    def test_available_tiers_ordered_strongest_first(self):
        sel = SandboxSelector()
        sel.register("fake", FakeSandboxBackend())
        sel.register("vm", _backend("vm"))
        sel.register("container", _backend("container"))
        assert sel.available_tiers == ["vm", "container", "fake"]


class TestNoSilentDowngrade:
    """The core security property: no workload ever silently runs at a weaker tier."""

    def test_no_downgrade_from_vm_to_container(self):
        sel = SandboxSelector()
        sel.register("container", _backend("container"))
        sel.register("bubblewrap", _backend("bubblewrap"))
        # UNTRUSTED_CODE requires vm — having container+bubblewrap is NOT enough
        with pytest.raises(NoSuitableBackendError):
            sel.select(UNTRUSTED_CODE)

    def test_explicit_error_message_names_the_gap(self):
        sel = SandboxSelector()
        sel.register("container", _backend("container"))
        with pytest.raises(NoSuitableBackendError, match="requires min_tier='vm'"):
            sel.select(UNTRUSTED_CODE)


class TestBuildConfigClamping:
    """`WorkloadPolicy` names its fields `max_memory_mb`, `max_timeout_s` and
    `network_allowed` — ceilings and a permission. They were being used as
    defaults that any override replaced, which let a caller hand
    model-generated code a networked sandbox against a policy that forbids it.
    Overrides may only tighten.
    """

    def test_network_override_cannot_defeat_a_no_network_policy(self) -> None:
        cfg = SandboxSelector().build_config(UNTRUSTED_CODE, network=True)
        assert cfg.network is False

    def test_network_override_can_still_drop_network(self) -> None:
        assert TRUSTED_TOOL.network_allowed is True
        cfg = SandboxSelector().build_config(TRUSTED_TOOL, network=False)
        assert cfg.network is False

    def test_memory_override_above_the_ceiling_is_clamped(self) -> None:
        cfg = SandboxSelector().build_config(UNTRUSTED_CODE, memory_mb=999_999)
        assert cfg.memory_mb == UNTRUSTED_CODE.max_memory_mb

    def test_memory_override_below_the_ceiling_is_honoured(self) -> None:
        cfg = SandboxSelector().build_config(UNTRUSTED_CODE, memory_mb=128)
        assert cfg.memory_mb == 128

    def test_timeout_override_above_the_ceiling_is_clamped(self) -> None:
        cfg = SandboxSelector().build_config(UNTRUSTED_CODE, timeout_s=86_400)
        assert cfg.timeout_s == UNTRUSTED_CODE.max_timeout_s

    def test_no_overrides_yields_the_policy_limits(self) -> None:
        cfg = SandboxSelector().build_config(BENCHMARK_EVAL)
        assert cfg.memory_mb == BENCHMARK_EVAL.max_memory_mb
        assert cfg.timeout_s == BENCHMARK_EVAL.max_timeout_s
        assert cfg.network is False
        assert cfg.min_isolation == BENCHMARK_EVAL.min_tier
