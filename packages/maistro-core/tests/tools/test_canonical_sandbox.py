"""Production compatibility wiring must not widen untrusted-code policy."""

from unittest.mock import AsyncMock

import pytest

from maistro.config.settings import SandboxSettings
from maistro.sandbox import (
    ExecResult,
    SandboxInstance,
    SandboxSelector,
)
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


# --- the facade surface agents actually call (#76 clarification) -------------


def _facade_backend() -> AsyncMock:
    backend = AsyncMock()
    backend.tier = "vm"
    backend.supports_scoped_egress = False
    backend.spawn.return_value = SandboxInstance(
        id="facade", backend="recording", isolation_tier="vm"
    )
    backend.exec.return_value = ExecResult(exit_code=0, stdout="out", stderr="err", duration_ms=1)
    backend.read_file.return_value = b"file-bytes"
    return backend


async def _facade(
    backend: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> canonical.CanonicalSandboxContainer:
    selector = SandboxSelector()
    selector.register("vm", backend)
    monkeypatch.setattr(canonical, "build_selector", lambda: selector)
    return await canonical.create_sandbox(
        "/tmp/maistro-workspace/issue-76",
        SandboxSettings(timeout=60),
    )


async def test_facade_exec_runs_safe_commands_and_blocks_dangerous_ones(monkeypatch):
    backend = _facade_backend()
    container = await _facade(backend, monkeypatch)

    code, output = await container.exec("ls -la")

    assert (code, output) == (0, "outerr")
    argv = backend.exec.call_args.args[1]
    assert argv == ["/bin/bash", "-lc", "ls -la"]
    assert backend.exec.call_args.kwargs["timeout_s"] == 60

    backend.exec.reset_mock()
    code, output = await container.exec("sudo rm -rf /")

    assert code == 1
    assert "blocked by safety filter" in output
    backend.exec.assert_not_awaited()
    await container.destroy()


async def test_facade_file_transfers_are_confined_to_the_canonical_workspace(monkeypatch):
    backend = _facade_backend()
    container = await _facade(backend, monkeypatch)

    assert await container.read_file("sub/report.txt") == "file-bytes"
    assert backend.read_file.call_args.args[1] == "/workspace/sub/report.txt"

    await container.write_file("sub/report.txt", "hello")
    assert backend.write_file.call_args.args[1] == "/workspace/sub/report.txt"
    assert backend.write_file.call_args.args[2] == b"hello"
    await container.destroy()


def test_facade_paths_refuse_everything_outside_the_canonical_workspace():
    with pytest.raises(ValueError, match="canonical sandbox paths must use /workspace"):
        canonical.CanonicalSandboxContainer._safe_path("/elsewhere", "file.txt")
    with pytest.raises(ValueError, match="Absolute paths are not allowed"):
        canonical.CanonicalSandboxContainer._safe_path(canonical.CONTAINER_WORKSPACE, "/etc/shadow")
    with pytest.raises(ValueError, match="Path traversal detected"):
        canonical.CanonicalSandboxContainer._safe_path(
            canonical.CONTAINER_WORKSPACE, "../../etc/shadow"
        )


async def test_facade_context_manager_destroys_and_ttl_expires(monkeypatch):
    backend = _facade_backend()
    container = await _facade(backend, monkeypatch)

    async with container as entered:
        assert entered is container
        assert not container.expired
        # Age the facade past its TTL without waiting for it.
        container.created_at -= container.ttl + 1
        assert container.expired

    backend.destroy.assert_awaited_once()
