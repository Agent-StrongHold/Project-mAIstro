"""Tests for the microVM sandbox backend (SPEC-190)."""

from __future__ import annotations

from maistro.config.settings import SandboxSettings
from maistro.tools.sandbox.microvm import (
    MicroVMConfig,
    MicroVMRunSpec,
    MicroVMSandbox,
    _parse_mib,
)


class _FakeLauncher:
    def __init__(self, result: tuple[int, str] = (0, "ok")) -> None:
        self.result = result
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        return self.result


async def test_exec_runs_command_in_microvm():
    launcher = _FakeLauncher(result=(0, "hello from vm"))
    sandbox = MicroVMSandbox(
        launcher,
        config=MicroVMConfig(memory_mib=256, vcpus=1),
        workspace="/tmp/maistro-workspace/t1",
    )
    code, out = await sandbox.exec("echo hi", timeout=30)

    assert (code, out) == (0, "hello from vm")
    spec = launcher.specs[-1]
    assert spec.command == "echo hi"
    assert spec.config.network == "none"  # default-deny
    assert spec.config.memory_mib == 256 and spec.config.vcpus == 1
    assert spec.timeout == 30  # min(call, config.timeout=300)
    assert sandbox.config.vcpus == 1  # config is exposed for introspection


async def test_call_timeout_capped_by_config():
    launcher = _FakeLauncher()
    sandbox = MicroVMSandbox(
        launcher, config=MicroVMConfig(timeout=10), workspace="/tmp/maistro-workspace/t2"
    )
    await sandbox.exec("echo hi", timeout=999)
    assert launcher.specs[-1].timeout == 10  # capped by the config ceiling


async def test_dangerous_command_is_blocked_before_launch():
    launcher = _FakeLauncher()
    sandbox = MicroVMSandbox(launcher, workspace="/tmp/maistro-workspace/t3")
    code, out = await sandbox.exec("rm -rf /")
    assert code == 126 and "blocked" in out
    assert launcher.specs == []  # never reached the VMM


async def test_plain_async_function_is_a_valid_launcher():
    seen: list[MicroVMRunSpec] = []

    async def launch(spec: MicroVMRunSpec) -> tuple[int, str]:
        seen.append(spec)
        return (7, "fn-launcher")

    sandbox = MicroVMSandbox(launch, workspace="/tmp/maistro-workspace/t4")
    code, out = await sandbox.exec("echo hi")
    assert (code, out) == (7, "fn-launcher")
    assert seen[-1].workspace == "/tmp/maistro-workspace/t4"


def test_config_from_settings_parses_memory_and_network():
    settings = SandboxSettings(memory_limit="1g", cpu_count=4, network_disabled=False)
    config = MicroVMConfig.from_settings(settings)
    assert config.memory_mib == 1024
    assert config.vcpus == 4
    assert config.network == "restricted"


async def test_env_is_sanitized_before_launch():
    """Ambient/request-derived secrets must not cross the VM boundary."""
    launcher = _FakeLauncher()
    sandbox = MicroVMSandbox(
        launcher,
        workspace="/tmp/maistro-workspace/t1",
        env={"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "leak", "OPENAI_API_KEY": "leak"},
    )
    await sandbox.exec("echo hi")
    passed = launcher.specs[-1].env
    assert "PATH" in passed  # allowlisted
    assert "AWS_SECRET_ACCESS_KEY" not in passed
    assert "OPENAI_API_KEY" not in passed


async def test_trusted_env_bypasses_the_allowlist_but_env_does_not():
    """The two channels differ in trust, and only `trusted_env` is verbatim.

    A harness provider must be able to provision its own credential into the
    guest (opencode's provider key), while request-derived or ambient values
    stay allowlist-filtered. Collapsing these into one dict forces a choice
    between leaking secrets and breaking the harness.
    """
    launcher = _FakeLauncher()
    sandbox = MicroVMSandbox(
        launcher,
        workspace="/tmp/maistro-workspace/t1",
        env={"AWS_SECRET_ACCESS_KEY": "leak"},
        trusted_env={"OPENCODE_API_KEY": "wired-by-operator"},
    )
    await sandbox.exec("echo hi")
    passed = launcher.specs[-1].env
    assert passed["OPENCODE_API_KEY"] == "wired-by-operator"
    assert "AWS_SECRET_ACCESS_KEY" not in passed


def test_from_settings_uses_vm_rootfs_not_docker_image():
    """Firecracker cannot boot an OCI ref: rootfs/kernel are VM-specific settings."""
    settings = SandboxSettings(image="python:3.12-slim")
    config = MicroVMConfig.from_settings(settings)
    assert config.rootfs_image == "rootfs.ext4"
    assert config.kernel_image == "vmlinux"
    assert config.rootfs_image != settings.image


def test_parse_mib_units():
    assert _parse_mib("512m") == 512
    assert _parse_mib("2g") == 2048
    assert _parse_mib("1024k") == 1
    assert _parse_mib("2097152") == 2  # bare bytes -> MiB
    assert _parse_mib("500") == 1  # rounds up to a 1 MiB floor


def test_workspace_outside_allowlist_is_refused():
    """The harness API's request body controls workdir, and the launcher
    mounts it into the guest: /etc or the service checkout must be refused at
    construction, mirroring the Docker backend's ensure_workspace posture."""
    import pytest

    async def launch(spec):
        return 0, ""

    for hostile in ("/etc", "/", "/home", "."):
        with pytest.raises(ValueError):
            MicroVMSandbox(launch, workspace=hostile)
