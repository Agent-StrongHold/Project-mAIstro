"""Production compatibility wiring must not widen untrusted-code policy."""

from unittest.mock import AsyncMock

import pytest

from maistro.config.settings import SandboxSettings
from maistro.sandbox import SandboxInstance, SandboxSelector
from maistro.sandbox.network import EgressMode
from maistro.tools.sandbox import canonical


async def test_requested_deny_and_resource_limits_reach_selected_backend(monkeypatch):
    backend = AsyncMock()
    backend.tier = "vm"
    backend.supports_scoped_egress = False
    backend.spawn.return_value = SandboxInstance(
        id="test", backend="recording", isolation_tier="vm"
    )
    selector = SandboxSelector()
    selector.register("vm", backend)
    monkeypatch.setattr(canonical, "build_selector", lambda: selector)
    settings = SandboxSettings(memory_limit="256m", timeout=17, network_disabled=True)
    container = await canonical.create_sandbox("/tmp/maistro-workspace/issue-76", settings)
    try:
        config = backend.spawn.call_args.kwargs["config"]
        assert config.egress.mode is EgressMode.DENY
        assert config.min_isolation == "vm"
        assert config.memory_mb == 256
        assert config.timeout_s == 17
    finally:
        await container.destroy()


async def test_settings_cannot_enable_network_without_a_policy_grant(monkeypatch):
    monkeypatch.setattr(canonical, "build_selector", lambda: SandboxSelector())
    with pytest.raises(ValueError, match="egress"):
        await canonical.create_sandbox(
            "/tmp/maistro-workspace/issue-76",
            SandboxSettings(network_disabled=False),
        )
