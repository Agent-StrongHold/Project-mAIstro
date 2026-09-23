"""The container backend — the tier a Docker/Podman host actually gets (#76/#80).

`build_selector` registers the container tier whenever detection evidences a
reachable runtime, and the ladder prefers it over bubblewrap — so on the
deployment hosts this repository most often runs on, `ContainerSandboxBackend`
IS the production boundary for tool-sandbox code execution. A container tier
with no conformance coverage would mean the strongest registered tier on those
hosts is the one nothing has ever asked anything of.

Split like the rest of the conformance suite: what is a pure function of the
config is asserted against the constructed argv (any host, no daemon), and
what needs a runtime is asserted against the real daemon where one is
reachable — skipped with the probe's reason where it is not, the same honest
capability keying `test_real_backend.py` uses for bubblewrap.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

from maistro.sandbox import SandboxConfig, detect_host_capabilities
from maistro.sandbox.backends.container import (
    ContainerSandboxBackend,
    ContainerUnavailableError,
)
from maistro.sandbox.network import DENY_ALL, EgressGrant, EgressMode
from maistro.sandbox.paths import validate_host_root

_capabilities = detect_host_capabilities()
requires_daemon = pytest.mark.skipif(
    not _capabilities.supports("container"),
    reason=(
        f"no reachable container runtime: {_capabilities.notes.get('container', 'probe absent')}"
    ),
)


class _FakeProcess:
    """Minimal asyncio subprocess stand-in for spawn argv interception."""

    def __init__(self) -> None:
        self.returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"fake-container-id\n", b"")


@pytest.fixture
def launched_argv(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[list[str]]]:
    """Record every argv the backend would hand the container CLI."""
    captured: list[list[str]] = []

    async def _fake_exec(*command: Any, **_kwargs: Any) -> _FakeProcess:
        captured.append([str(part) for part in command])
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    yield captured


def _mounts(argv: list[str]) -> list[str]:
    return [argv[i + 1] for i, token in enumerate(argv) if token == "-v"]


def test_the_constructor_refuses_without_a_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("maistro.sandbox.backends.container.shutil.which", lambda _name: None)

    with pytest.raises(ContainerUnavailableError, match="no Docker or Podman"):
        ContainerSandboxBackend()


def test_the_backend_declares_its_tier_and_its_egress_honesty() -> None:
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")

    assert backend.tier == "container"
    # A container joined to the host network shares it whole; this backend
    # cannot permit one destination and refuse another, so it says so and the
    # selector refuses scoped grants rather than approximating them.
    assert backend.supports_scoped_egress is False


# --- the spawn argv IS the boundary; assert it on every host -----------------


async def test_the_sandbox_is_hardened_by_default(launched_argv) -> None:
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")
    instance = await backend.spawn(config=SandboxConfig(memory_mb=256, max_processes=64))

    argv = launched_argv[0]
    for expected in (
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--network=none",
    ):
        assert expected in argv, f"missing {expected} in {argv}"
    assert "--user" in argv and "65532:65532" in argv
    assert "--memory=256m" in argv
    assert "--pids-limit=64" in argv
    await backend.destroy(instance)


async def test_no_host_socket_is_ever_mounted(launched_argv) -> None:
    """ADR-093 decision 2: the socket mount is the prohibited shape."""
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")
    instance = await backend.spawn(config=SandboxConfig())

    mounts = _mounts(launched_argv[0])
    assert mounts, "workspace mount missing"
    assert not any("docker.sock" in mount for mount in mounts)
    await backend.destroy(instance)


async def test_the_writable_surface_is_exactly_the_workspace(launched_argv) -> None:
    workspace = validate_host_root("/tmp/maistro-workspace", create=True)
    subdir = workspace / "spawn-surface-test"
    subdir.mkdir(exist_ok=True)
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")
    instance = await backend.spawn(config=SandboxConfig(writable_paths=[str(subdir)]))

    assert _mounts(launched_argv[0]) == [f"{subdir.resolve()}:/work:rw"]
    await backend.destroy(instance)


async def test_an_unauthorized_writable_root_is_refused_before_any_container(
    tmp_path: Path,
) -> None:
    """A caller-supplied path is host authority: only allowlisted roots."""
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")

    with pytest.raises(ValueError, match="not authorized"):
        await backend.spawn(config=SandboxConfig(writable_paths=[str(tmp_path)]))


async def test_more_than_one_writable_root_is_refused(tmp_path: Path) -> None:
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")

    with pytest.raises(ValueError, match="one authorized workspace root"):
        await backend.spawn(config=SandboxConfig(writable_paths=[str(tmp_path), str(tmp_path)]))


async def test_the_environment_is_the_allowlisted_config_env_not_the_hosts(
    launched_argv,
) -> None:
    """#78: ambient credentials ride inherited environments. The backend
    starts from `sanitize_env`'s allowlist, so a secret-shaped variable in
    the config never reaches the container."""
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")
    instance = await backend.spawn(
        config=SandboxConfig(
            env={
                "TZ": "UTC",
                "OPENAI_API_KEY": "sk-abcdefghijklmnopqrstuvwxyz012345",
            }
        )
    )

    argv = launched_argv[0]
    env_pairs = [argv[i + 1] for i, token in enumerate(argv) if token == "-e"]
    assert any(pair.startswith("TZ=") for pair in env_pairs)
    assert not any(pair.startswith("OPENAI_API_KEY=") for pair in env_pairs)
    await backend.destroy(instance)


async def test_egress_follows_the_grant_not_a_boolean(launched_argv) -> None:
    """#77: the grant is decided by the policy; the argv follows it. Default
    deny means `--network=none`; an explicit HOST grant names its reason and
    shares the host namespace — there is no third, unlabelled state."""
    backend = ContainerSandboxBackend(binary="/usr/bin/docker")

    def _runs() -> list[list[str]]:
        return [argv for argv in launched_argv if len(argv) > 1 and argv[1] == "run"]

    denied = await backend.spawn(config=SandboxConfig(egress=DENY_ALL))
    assert "--network=none" in _runs()[0]
    await backend.destroy(denied)

    granted = await backend.spawn(
        config=SandboxConfig(
            egress=EgressGrant(
                mode=EgressMode.HOST,
                reason="first-party tool calls a named external API",
            )
        )
    )
    runs = _runs()
    assert "--network=host" in runs[1]
    assert "--network=none" not in runs[1]
    await backend.destroy(granted)


# --- and against the real daemon, that the boundary holds --------------------


@pytest.fixture
async def live_backend() -> AsyncIterator[ContainerSandboxBackend]:
    yield ContainerSandboxBackend()


@requires_daemon
async def test_a_real_sandbox_executes_and_reports_its_result(live_backend) -> None:
    instance = await live_backend.spawn(config=SandboxConfig())

    result = await live_backend.exec(instance, ["/bin/sh", "-c", "echo hello"], timeout_s=60)

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    await live_backend.destroy(instance)


@requires_daemon
async def test_a_real_sandbox_has_no_network_by_default(live_backend) -> None:
    """The `--network=none` flag, checked against the kernel rather than argv."""
    instance = await live_backend.spawn(config=SandboxConfig())

    result = await live_backend.exec(instance, ["/bin/sh", "-c", "cat /proc/net/dev"], timeout_s=60)

    interfaces = [line.split(":")[0].strip() for line in result.stdout.splitlines() if ":" in line]
    assert [name for name in interfaces if name and name != "lo"] == []
    await live_backend.destroy(instance)


@requires_daemon
async def test_the_environment_reaches_the_sandbox_and_secrets_do_not(
    live_backend,
) -> None:
    """#78 against the real path: the allowlisted variable arrives, the
    secret-shaped one never does."""
    instance = await live_backend.spawn(
        config=SandboxConfig(
            env={
                "TZ": "UTC",
                "OPENAI_API_KEY": "sk-abcdefghijklmnopqrstuvwxyz012345",
            }
        )
    )

    marker = await live_backend.exec(instance, ["/bin/sh", "-c", "echo $TZ"], timeout_s=60)
    secret = await live_backend.exec(
        instance, ["/bin/sh", "-c", "echo ${OPENAI_API_KEY:-absent}"], timeout_s=60
    )

    assert marker.stdout.strip() == "UTC"
    assert secret.stdout.strip() == "absent"
    await live_backend.destroy(instance)


@requires_daemon
async def test_files_round_trip_through_the_workspace_mount(live_backend) -> None:
    instance = await live_backend.spawn(config=SandboxConfig())

    await live_backend.write_file(instance, "/work/in.txt", b"payload")
    result = await live_backend.exec(instance, ["/bin/cat", "/work/in.txt"], timeout_s=60)
    content = await live_backend.read_file(instance, "/work/in.txt")

    assert result.stdout == "payload"
    assert content == b"payload"
    await live_backend.destroy(instance)


@requires_daemon
async def test_a_real_sandbox_bounds_stdout_overflow(live_backend) -> None:
    """#1197 on the production container path: overflow terminates the exec,
    retains only the bound, and tells the truth about it."""
    instance = await live_backend.spawn(
        config=SandboxConfig(max_stdout_bytes=1024, max_stderr_bytes=1024)
    )

    result = await live_backend.exec(
        instance,
        ["/bin/sh", "-c", "while :; do printf 'o%.0s' $(seq 1 4096); done"],
        timeout_s=30,
    )

    assert result.exit_code == 125
    assert result.output_limit_exceeded
    assert result.stdout_truncated
    assert result.stdout_bytes_retained <= 1024
    await live_backend.destroy(instance)


@requires_daemon
async def test_a_real_sandbox_times_out_rather_than_running_forever(live_backend) -> None:
    instance = await live_backend.spawn(config=SandboxConfig())

    result = await live_backend.exec(instance, ["/bin/sh", "-c", "sleep 30"], timeout_s=1)

    assert result.timed_out
    assert result.exit_code == 124
    await live_backend.destroy(instance)


@requires_daemon
async def test_destroy_is_idempotent_and_removes_the_workspace(live_backend) -> None:
    instance = await live_backend.spawn(config=SandboxConfig())
    workdir = Path(instance.metadata["workdir"])

    await live_backend.destroy(instance)
    await live_backend.destroy(instance)

    assert not workdir.exists()


@requires_daemon
async def test_a_destroyed_sandbox_cannot_be_used(live_backend) -> None:
    instance = await live_backend.spawn(config=SandboxConfig())
    await live_backend.destroy(instance)

    with pytest.raises(KeyError):
        await live_backend.read_file(instance, "/work/in.txt")
