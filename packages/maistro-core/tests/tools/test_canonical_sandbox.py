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


async def test_facade_ttl_never_exceeds_launch_lifetime(monkeypatch):
    """The guest's init process dies at config.timeout_s (post-clamp), so the
    cached facade must expire no later than that, policy clamp included."""
    backend = AsyncMock()
    backend.tier = "vm"
    backend.supports_scoped_egress = False
    backend.spawn.return_value = SandboxInstance(
        id="test", backend="recording", isolation_tier="vm"
    )
    selector = SandboxSelector()
    selector.register("vm", backend)
    monkeypatch.setattr(canonical, "build_selector", lambda: selector)

    # Default policy, no settings: the 3,600s default TTL must clamp to the
    # effective launch lifetime (UNTRUSTED_CODE caps timeout_s at 300s).
    container = await canonical.create_sandbox("/tmp/maistro-workspace/issue-76")
    config = backend.spawn.call_args.kwargs["config"]
    assert config.timeout_s == 300
    assert container.ttl == 300
    await container.destroy()

    # A requested timeout above the policy ceiling keeps the clamped lifetime.
    backend.spawn.reset_mock()
    clamped = await canonical.create_sandbox(
        "/tmp/maistro-workspace/issue-76", SandboxSettings(timeout=10_000)
    )
    assert backend.spawn.call_args.kwargs["config"].timeout_s == 300
    assert clamped.ttl == 300
    await clamped.destroy()


async def test_settings_cannot_enable_network_without_a_policy_grant(monkeypatch):
    monkeypatch.setattr(canonical, "build_selector", lambda: SandboxSelector())
    with pytest.raises(ValueError, match="egress"):
        await canonical.create_sandbox(
            "/tmp/maistro-workspace/issue-76",
            SandboxSettings(network_disabled=False),
        )


async def test_env_is_sanitized_and_trusted_env_passes_verbatim(monkeypatch):
    """Ambient/request-derived `env` is allowlist-sanitized before it reaches
    the guest (Codex, #262); explicit `trusted_env` is the only channel for
    intentionally provisioned credentials."""
    backend = AsyncMock()
    backend.tier = "vm"
    backend.supports_scoped_egress = False
    backend.spawn.return_value = SandboxInstance(
        id="test", backend="recording", isolation_tier="vm"
    )
    selector = SandboxSelector()
    selector.register("vm", backend)
    monkeypatch.setattr(canonical, "build_selector", lambda: selector)

    container = await canonical.create_sandbox(
        "/tmp/maistro-workspace/issue-76",
        env={"TZ": "UTC", "AWS_SECRET_ACCESS_KEY": "leak", "OPENAI_API_KEY": "sk-x"},
        trusted_env={"HARNESS_PROVIDER_KEY": "intentional"},
    )
    config = backend.spawn.call_args.kwargs["config"]
    assert config.env == {"TZ": "UTC", "HARNESS_PROVIDER_KEY": "intentional"}
    await container.destroy()
