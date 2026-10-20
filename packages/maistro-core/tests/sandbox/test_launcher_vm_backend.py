"""The launcher-backed vm-tier backend registers behind the canonical selector.

#76's cutover invariant is one sandbox authority: a harness that wires a VMM
launcher (SPEC-205) must not become a second, provider-private sandbox path.
These tests pin the three halves of that:

* the backend registers at the tier it declares, and the *selector* — not the
  caller — admits the workload (`UNTRUSTED_CODE` selects it);
* egress stays the policy's decision: deny passes, scoped is refused for a
  non-filtering backend, and host is refused because no shipped launcher
  provides a networked guest profile — deny-only, stated, never approximated;
* execution really flows through the launcher seam (command verbatim for the
  harness shell-line shape, joined for argv), with the dangerous-command
  screen still in front of the VMM.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import uuid4

import pytest

from maistro.sandbox import (
    DENY_ALL,
    UNTRUSTED_CODE,
    EgressGrant,
    EgressMode,
    SandboxConfig,
    SandboxInstance,
    SandboxSelector,
    TierMismatchError,
    WorkloadPolicy,
)
from maistro.sandbox.backends.launcher_vm import (
    LauncherVMSandboxBackend,
    LauncherVMUnavailableError,
)
from maistro.sandbox.network import EgressNotEnforceableError
from maistro.tools.sandbox.microvm import MicroVMConfig, MicroVMRunSpec

_WORKSPACE_ROOT = Path("/tmp/maistro-workspace")  # nosec B108 — allowlisted root


class _FakeLauncher:
    def __init__(self, result: tuple[int, str] = (0, "vm-ran")) -> None:
        self.result = result
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        return self.result


def _workspace(name: str) -> str:
    return str(_WORKSPACE_ROOT / f"launcher-vm-{name}-{uuid4().hex[:8]}")


def _backend(name: str, **kwargs: object) -> LauncherVMSandboxBackend:
    return LauncherVMSandboxBackend(_FakeLauncher(), workspace=_workspace(name), **kwargs)  # type: ignore[arg-type]


def _select(backend: LauncherVMSandboxBackend, policy: WorkloadPolicy) -> SandboxInstance:
    selector = SandboxSelector()
    selector.register("vm", backend)
    _tier, selected = selector.select(policy)
    return _spawn(selected, policy)


def _spawn(backend: LauncherVMSandboxBackend, policy: WorkloadPolicy) -> SandboxInstance:
    import asyncio

    return asyncio.run(backend.spawn(config=SandboxConfig(egress=policy.egress)))


def test_registers_at_vm_tier_and_selector_admits_untrusted_code() -> None:
    backend = _backend("tier")

    selector = SandboxSelector()
    selector.register("vm", backend)
    tier, selected = selector.select(UNTRUSTED_CODE)

    assert tier == "vm"
    assert selected is backend


def test_a_backend_cannot_be_registered_at_a_tier_it_does_not_declare() -> None:
    backend = _backend("mismatch")

    selector = SandboxSelector()
    with pytest.raises(TierMismatchError):
        selector.register("container", backend)


def test_selector_refuses_a_scoped_grant_for_a_non_filtering_substrate() -> None:
    backend = _backend("scoped")
    scoped = WorkloadPolicy(
        min_tier="vm",
        egress=EgressGrant(mode=EgressMode.SCOPED, allow=("api.anthropic.com",), reason="test"),
        reason="test policy",
    )

    selector = SandboxSelector()
    selector.register("vm", backend)
    with pytest.raises(EgressNotEnforceableError):
        selector.select(scoped)


def test_a_networked_grant_is_refused_not_approximated() -> None:
    backend = _backend("host")
    host = WorkloadPolicy(
        min_tier="vm",
        egress=EgressGrant(mode=EgressMode.HOST, reason="test grant"),
        reason="test policy",
    )

    with pytest.raises(LauncherVMUnavailableError, match="deny-only"):
        _select(backend, host)


def test_the_policy_not_the_substrate_config_decides_network() -> None:
    # A caller wiring `network="restricted"` substrate config must not widen
    # what the (default-deny) policy granted: spawn forces the effective
    # substrate to "none".
    launcher = _FakeLauncher()
    backend = LauncherVMSandboxBackend(
        launcher,
        config=MicroVMConfig(network="restricted"),
        workspace=_workspace("substrate"),
    )
    instance = _spawn(backend, UNTRUSTED_CODE)

    import asyncio

    asyncio.run(backend.exec(instance, ["echo hi"]))

    assert launcher.specs[-1].config.network == "none"


async def test_a_shell_command_line_reaches_the_launcher_verbatim() -> None:
    launcher = _FakeLauncher(result=(0, "patched 2 files"))
    backend = LauncherVMSandboxBackend(launcher, workspace=_workspace("verbatim"))
    instance = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))

    result = await backend.exec(instance, ["opencode run --auto 'fix it'"], timeout_s=45)

    assert (result.exit_code, result.stdout) == (0, "patched 2 files")
    assert launcher.specs[-1].command == "opencode run --auto 'fix it'"
    assert launcher.specs[-1].timeout == 45


async def test_argv_is_shell_joined_for_the_launcher() -> None:
    launcher = _FakeLauncher()
    backend = LauncherVMSandboxBackend(launcher, workspace=_workspace("argv"))
    instance = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))

    await backend.exec(instance, ["pytest", "-q", "pkg tests"])

    assert launcher.specs[-1].command == "pytest -q 'pkg tests'"


async def test_dangerous_commands_never_reach_the_vmm() -> None:
    launcher = _FakeLauncher()
    backend = LauncherVMSandboxBackend(launcher, workspace=_workspace("screen"))
    instance = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))

    result = await backend.exec(instance, ["rm -rf /"])

    assert result.exit_code == 126
    assert launcher.specs == []


async def test_trusted_env_reaches_the_guest_and_file_ops_stay_in_the_workspace() -> None:
    workspace = Path(_workspace("files"))
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "repo.txt").write_text("inside", encoding="utf-8")
    backend = LauncherVMSandboxBackend(
        _FakeLauncher(),
        workspace=str(workspace),
        trusted_env={"OPENCODE_API_KEY": "k"},
    )
    instance = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))

    content = await backend.read_file(instance, "/workspace/repo.txt")
    assert content == b"inside"
    await backend.write_file(instance, "/workspace/new/pkg.py", b"x = 1\n")
    assert (workspace / "new" / "pkg.py").read_bytes() == b"x = 1\n"

    with pytest.raises(ValueError, match="escapes"):
        await backend.read_file(instance, "/workspace/../../etc/passwd")
    with pytest.raises(ValueError, match="outside the sandbox"):
        await backend.write_file(instance, "/etc/passwd", b"bad")


def test_a_workspace_outside_the_allowlist_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="not in an allowed location"):
        LauncherVMSandboxBackend(_FakeLauncher(), workspace=str(PurePosixPath("/etc")))


async def test_destroy_is_an_idempotent_noop() -> None:
    # One VM per exec (SPEC-205): there is no persistent resource, so destroy
    # must simply never raise — including twice.
    backend = _backend("destroy")
    instance = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))

    await backend.destroy(instance)
    await backend.destroy(instance)

    with pytest.raises(KeyError):
        await backend.exec(instance, ["true"])
