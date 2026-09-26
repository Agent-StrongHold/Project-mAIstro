"""Coverage for tools/sandbox/docker.py — the legacy facade over `maistro.sandbox`.

The module used to be a second launcher and these tests pinned its private
argv. It is now a facade (#18): selection, policy, egress and containment live
in `maistro.sandbox`, so the tests pin the *translation* — the legacy call
signature maps onto the canonical ladder, default-deny egress, and a cleared
environment, and it fails closed when no backend meets the unattended floor.
A stub vm-tier backend is registered with the real `SandboxSelector`, so the
ladder, tier guard and config clamping all run for real; no daemon required.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from maistro.config.settings import SandboxSettings
from maistro.sandbox import (
    ExecResult,
    NoSuitableBackendError,
    SandboxInstance,
    SandboxSelector,
)
from maistro.sandbox.network import EgressMode
from maistro.tools.sandbox import docker
from maistro.tools.sandbox.docker import create_sandbox


class _StubVmBackend:
    """Records what the facade actually asks the canonical layer to do."""

    tier = "vm"
    supports_scoped_egress = False

    def __init__(self) -> None:
        self.spawn_configs: list[Any] = []
        self.exec_calls: list[tuple[SandboxInstance, list[str], int]] = []
        self.read_calls: list[str] = []
        self.write_calls: list[tuple[str, bytes]] = []
        self.destroyed = 0

    async def spawn(self, *, config: Any) -> SandboxInstance:
        self.spawn_configs.append(config)
        return SandboxInstance(id="stub-1", backend="stub", isolation_tier="vm")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        self.exec_calls.append((instance, command, timeout_s))
        return ExecResult(exit_code=0, stdout="hello\n", stderr="", duration_ms=1)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        self.read_calls.append(path)
        return b"file-bytes"

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        self.write_calls.append((path, content))

    async def destroy(self, instance: SandboxInstance) -> None:
        self.destroyed += 1


def _authorized_root() -> str:
    """A workspace under the authorized temp root (#1198 allowlist)."""
    root = Path(tempfile.gettempdir()) / "maistro-workspace" / "facade-tests"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


@pytest.fixture
def stub_backend() -> _StubVmBackend:
    return _StubVmBackend()


@pytest.fixture
def patched_selector(
    monkeypatch: pytest.MonkeyPatch, stub_backend: _StubVmBackend
) -> SandboxSelector:
    """Real selector with only the vm backend stubbed; detection bypassed."""
    selector = SandboxSelector()
    selector.register("vm", stub_backend)
    monkeypatch.setattr(docker, "build_selector", lambda: selector)
    return selector


async def test_create_sandbox_selects_through_the_ladder_and_forwards(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    workspace = _authorized_root()
    container = await create_sandbox(workspace, env={"FOO": "bar"})

    # The policy that reached the ladder demanded the unattended/untrusted floor.
    config = stub_backend.spawn_configs[0]
    assert config.min_isolation == "vm"
    assert config.env == {"FOO": "bar"}
    assert config.writable_paths == [workspace]
    # Default-deny egress (#77): default settings deny networking.
    assert config.egress.mode is EgressMode.DENY

    # exec/read/write/destroy cross as protocol calls; code is argv data.
    code, output = await container.exec("python check.py", timeout=7)
    assert (code, output) == (0, "hello\n")
    _instance, argv, timeout_s = stub_backend.exec_calls[0]
    assert argv == ["/bin/sh", "-c", "python check.py"]
    assert timeout_s == 7

    assert await container.read_file("src/x.py") == "file-bytes"
    assert stub_backend.read_calls == ["src/x.py"]
    await container.write_file("out/answer.txt", "42")
    assert stub_backend.write_calls == [("out/answer.txt", b"42")]

    await container.destroy()
    assert stub_backend.destroyed == 1


async def test_default_settings_produce_default_deny_egress(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    await create_sandbox(_authorized_root())
    config = stub_backend.spawn_configs[0]
    assert config.egress.mode is EgressMode.DENY


async def test_explicit_network_opt_in_becomes_a_host_grant(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    await create_sandbox(_authorized_root(), settings=SandboxSettings(network_disabled=False))
    config = stub_backend.spawn_configs[0]
    assert config.egress.mode is EgressMode.HOST
    assert config.egress.reason  # an audited grant names its reason


async def test_settings_cross_as_policy_ceilings(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    await create_sandbox(
        _authorized_root(),
        settings=SandboxSettings(memory_limit="256m", timeout=90),
    )
    config = stub_backend.spawn_configs[0]
    assert config.memory_mb == 256
    assert config.timeout_s == 90


async def test_fails_closed_without_a_qualifying_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No registered backend at the vm tier → refusal, never a downgrade."""
    monkeypatch.setattr(docker, "build_selector", SandboxSelector)  # bare: nothing registered
    with pytest.raises(NoSuitableBackendError):
        await create_sandbox(_authorized_root())


async def test_unauthorized_workspace_root_is_refused(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    """An arbitrary path can never become a sandbox mount via the legacy seam."""
    with pytest.raises(ValueError, match="not authorized"):
        await create_sandbox("/etc")
    assert stub_backend.spawn_configs == []  # refused before any spawn


async def test_exec_blocks_dangerous_command_without_touching_backend(
    patched_selector: SandboxSelector, stub_backend: _StubVmBackend
) -> None:
    container = await create_sandbox(_authorized_root())
    with patch("maistro.tools.sandbox.docker.is_dangerous_command", return_value=["rm -rf"]):
        code, output = await container.exec("rm -rf /")

    assert code == 1
    assert "blocked by safety filter" in output
    assert stub_backend.exec_calls == []  # never reached the boundary


async def test_ttl_expiry_and_context_manager_destroy(
    patched_selector: SandboxSelector,
    stub_backend: _StubVmBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = await create_sandbox(_authorized_root(), settings=SandboxSettings(timeout=10))
    assert container.ttl == 10
    assert container.expired is False
    monkeypatch.setattr(
        "maistro.tools.sandbox.docker.time.monotonic", lambda: container._created + 20
    )
    assert container.expired is True

    async with container:
        pass
    assert stub_backend.destroyed == 1
