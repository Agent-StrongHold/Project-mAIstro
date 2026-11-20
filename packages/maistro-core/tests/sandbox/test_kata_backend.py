"""Conformance for the shipped Tier-1 Kata backend and canonical wiring."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from maistro.sandbox import (
    BENCHMARK_EVAL,
    BROWSER_AUTOMATION,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    HostCapabilities,
    SandboxConfig,
    build_selector,
)
from maistro.sandbox.backends.kata import (
    OUTPUT_LIMIT_EXIT_CODE,
    KataSandboxBackend,
    KataUnavailableError,
)
from maistro.sandbox.fence import SandboxFence
from maistro.sandbox.network import EgressGrant, EgressMode
from maistro.sandbox.protocol import SandboxInstance


def _backend() -> KataSandboxBackend:
    return KataSandboxBackend(
        docker="/usr/bin/docker",
        kata_runtime="/usr/bin/kata-runtime",
        image="example/sandbox:locked",
    )


def test_kata_launch_has_vm_runtime_and_no_host_socket(tmp_path: Path) -> None:
    argv = _backend().build_run_argv(
        SandboxConfig(workspace_host=str(tmp_path)), "kata-test", tmp_path
    )

    assert "--runtime=kata" in argv
    assert "--network=none" in argv
    assert "/var/run/docker.sock" not in argv
    assert "--cap-drop=ALL" in argv
    assert f"{tmp_path}:/workspace:rw" in argv


def test_kata_host_network_requires_explicit_reason() -> None:
    config = SandboxConfig(
        egress=EgressGrant(mode=EgressMode.HOST, reason="approved first-party API")
    )
    argv = _backend().build_run_argv(config, "kata-test", Path("/tmp/work"))
    assert "--network=host" in argv
    assert "--network=none" not in argv


def test_kata_rejects_scoped_egress_instead_of_granting_host_network() -> None:
    config = SandboxConfig(
        egress=EgressGrant(
            mode=EgressMode.SCOPED,
            allow=("api.example.com",),
            reason="one API",
        )
    )
    with pytest.raises(ValueError, match="cannot filter"):
        _backend().build_run_argv(config, "kata-test", Path("/tmp/work"))


def test_kata_mounts_authorized_filesystem_grants(tmp_path: Path) -> None:
    granted = tmp_path / "granted"
    granted.mkdir()
    readable = tmp_path / "readonly-input"
    readable.mkdir()
    argv = KataSandboxBackend(
        docker="/usr/bin/docker",
        kata_runtime="/usr/bin/kata-runtime",
        allowed_writable_roots=(tmp_path,),
    ).build_run_argv(
        SandboxConfig(writable_paths=[str(granted)], read_paths=[str(readable)]),
        "kata-test",
        tmp_path,
    )

    assert f"{granted}:/work-extra-0:rw" in argv
    assert f"type=bind,src={readable},dst={readable},readonly" in argv


def test_kata_writable_grant_outside_host_roots_fails_closed(tmp_path: Path) -> None:
    config = SandboxConfig(writable_paths=[str(tmp_path)])
    with pytest.raises(ValueError, match="not authorized"):
        _backend().build_run_argv(config, "kata-test", tmp_path)


def test_vm_capability_selects_every_standard_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import maistro.sandbox.backends.kata as kata_module

    monkeypatch.setattr(kata_module, "KataSandboxBackend", _backend)
    selector = build_selector(capabilities=HostCapabilities(tiers=("vm",), notes={}))

    for policy in (UNTRUSTED_CODE, BENCHMARK_EVAL, TRUSTED_TOOL, BROWSER_AUTOMATION):
        tier, _backend_instance = selector.select(policy)
        assert tier == "vm"


def test_kata_backend_claims_only_the_protocol_vm_tier() -> None:
    assert _backend().tier == "vm"
    assert isinstance(_backend(), KataSandboxBackend)


@pytest.fixture
async def spawned(monkeypatch: pytest.MonkeyPatch):
    backend = _backend()
    monkeypatch.setattr(backend, "_run", AsyncMock(return_value=(b"container-id", b"", 0)))
    remove = AsyncMock()
    monkeypatch.setattr(backend, "_remove_container", remove)
    instance = await backend.spawn(
        config=SandboxConfig(timeout_s=10, max_stdout_bytes=8, max_stderr_bytes=8)
    )
    try:
        yield backend, instance, remove
    finally:
        await backend.destroy(instance)


@pytest.mark.parametrize("operation", ["read", "write"])
async def test_file_transfer_refuses_directory_swap(spawned, tmp_path, monkeypatch, operation):
    backend, instance, _remove = spawned
    root = Path(instance.metadata["workdir"])
    (root / "nested").mkdir()
    (root / "nested" / "marker").write_bytes(b"guest")
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_bytes(b"host-secret")
    original_to_thread = asyncio.to_thread

    async def swap_before_host_open(func, *args, **kwargs):
        (root / "nested").rename(root / "original")
        (root / "nested").symlink_to(outside, target_is_directory=True)
        return await original_to_thread(func, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(asyncio, "to_thread", swap_before_host_open)
        with pytest.raises((OSError, ValueError)):
            if operation == "write":
                await backend.write_file(instance, "/workspace/nested/marker", b"overwrite")
            else:
                await backend.read_file(instance, "/workspace/nested/marker")
    assert marker.read_bytes() == b"host-secret"


async def test_exec_enforces_no_new_privileges_on_guest_processes(spawned, monkeypatch):
    """Kata does not propagate no-new-privileges to exec'd processes (#76).

    The spawn pins --security-opt=no-new-privileges, so exec must re-assert
    the promise itself: a bare `docker exec` runs NoNewPrivs:0 inside the
    guest, which would let a compromise elevate through setuid in the rootfs.
    """
    backend, instance, _remove = spawned
    create = asyncio.create_subprocess_exec
    captured: dict[str, list[str]] = {}

    async def capturing_child(*argv, **kwargs):
        captured["argv"] = list(argv)
        return await create(sys.executable, "-c", "pass", **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capturing_child)
    result = await backend.exec(instance, ["python", "-c", "print('nnp')"])
    assert result.exit_code == 0
    argv = captured["argv"]
    exec_idx = argv.index("exec")
    assert argv[exec_idx + 1] == instance.id
    assert argv[exec_idx + 2 : exec_idx + 4] == ["setpriv", "--no-new-privs"]
    assert argv[exec_idx + 4 :] == ["python", "-c", "print('nnp')"]


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_real_child_output_is_bounded(spawned, monkeypatch, stream):
    backend, instance, remove = spawned
    create = asyncio.create_subprocess_exec

    async def real_child(*_argv, **kwargs):
        return await create(
            sys.executable,
            "-c",
            f"import os; os.write({1 if stream == 'stdout' else 2}, b'x'*4096)",
            **kwargs,
        )

    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_child)
    result = await backend.exec(instance, ["ignored"])
    assert result.exit_code == 125
    assert result.output_limit_exceeded
    assert getattr(result, f"{stream}_truncated")
    assert getattr(result, f"{stream}_bytes_retained") == 8
    assert len(getattr(result, stream).encode()) == 8
    remove.assert_awaited_once()


async def test_cancellation_reaps_child_and_removes_guest(spawned, monkeypatch):
    backend, instance, remove = spawned
    create = asyncio.create_subprocess_exec
    started = asyncio.Event()
    children = []

    async def real_child(*_argv, **kwargs):
        child = await create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        children.append(child)
        started.set()
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_child)
    task = asyncio.create_task(backend.exec(instance, ["ignored"]))
    await started.wait()
    # Let exec enter its capture scope before cancelling the task.
    await asyncio.sleep(0)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await task
        assert children[0].returncode is not None
        remove.assert_awaited_once()
    finally:
        if children[0].returncode is None:
            children[0].kill()
            await children[0].wait()


async def test_timeout_reaps_real_child_and_removes_guest(spawned, monkeypatch):
    backend, instance, remove = spawned
    create = asyncio.create_subprocess_exec
    children = []

    async def real_child(*_argv, **kwargs):
        child = await create(sys.executable, "-c", "import time; time.sleep(60)", **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(asyncio, "create_subprocess_exec", real_child)
    result = await backend.exec(instance, ["ignored"], timeout_s=0)
    assert result.exit_code == 124
    assert result.timed_out
    assert children[0].returncode is not None
    remove.assert_awaited_once()


async def test_failed_removal_does_not_discard_retryable_instance(spawned):
    backend, instance, remove = spawned
    fd = backend._require(instance)[3]
    remove.side_effect = [RuntimeError("daemon unavailable"), None]
    with pytest.raises(RuntimeError, match="daemon unavailable"):
        await backend.destroy(instance)
    os.fstat(fd)
    await backend.destroy(instance)
    await backend.destroy(instance)
    with pytest.raises(OSError):
        os.fstat(fd)
    assert not Path(instance.metadata["workdir"]).exists()


async def test_container_removal_failure_is_not_reported_as_success(monkeypatch):
    backend = _backend()
    run = AsyncMock(return_value=(b"", b"daemon unavailable", 1))
    monkeypatch.setattr(backend, "_run", run)
    with pytest.raises(RuntimeError, match="daemon unavailable"):
        await backend._remove_container("kata-test")
    run.return_value = (b"", b"No such container: kata-test", 1)
    await backend._remove_container("kata-test")


# --- construction and spawn failure paths (CI-runnable: no live VM needed) ---


def test_constructor_refuses_to_claim_vm_tier_without_its_toolchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No docker or no kata-runtime on PATH means no Tier-1 backend: the
    constructor must refuse rather than register something that cannot spawn."""
    import maistro.sandbox.backends.kata as kata_module

    monkeypatch.setattr(kata_module.shutil, "which", lambda _name: None)
    with pytest.raises(KataUnavailableError, match="refusing to claim a VM tier"):
        KataSandboxBackend()


def test_network_args_map_only_the_modes_the_grant_can_name() -> None:
    """DENY pins the no-interface flag, HOST shares the host namespace, and
    every other mode contributes no docker flag of its own."""
    assert KataSandboxBackend._network_args(EgressMode.DENY) == ["--network=none"]
    assert KataSandboxBackend._network_args(EgressMode.HOST) == ["--network=host"]
    assert KataSandboxBackend._network_args(EgressMode.SCOPED) == []


def test_env_args_carry_the_attempt_fence_for_publish_proofs() -> None:
    """A fenced workload's identity reaches the guest as environment, sorted
    and merged after the caller's env so a collision cannot shadow it."""
    config = SandboxConfig(
        env={"TZ": "UTC"},
        fence=SandboxFence(
            attempt_id="att-1",
            node_run_id="node-9",
            lease_epoch=3,
            fencing_token="tok-abc",
        ),
    )

    args = KataSandboxBackend._env_args(config)

    # Sorted caller env first, then the fence identity, all as --env pairs.
    pairs = list(zip(args[::2], args[1::2], strict=True))
    assert all(flag == "--env" for flag, _value in pairs)
    values = [value for _flag, value in pairs]
    assert values[0] == "TZ=UTC"
    assert "MAISTRO_FENCE_ATTEMPT_ID=att-1" in values
    assert "MAISTRO_FENCE_NODE_RUN_ID=node-9" in values
    assert "MAISTRO_FENCE_LEASE_EPOCH=3" in values
    assert "MAISTRO_FENCE_TOKEN=tok-abc" in values


async def test_spawn_with_an_explicit_workspace_bind_keeps_host_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-supplied workspace is bound, not owned: the backend neither
    creates nor deletes it, and destroy leaves it in place."""
    backend = _backend()
    monkeypatch.setattr(backend, "_run", AsyncMock(return_value=(b"container-id", b"", 0)))
    bind_root = Path(tempfile.gettempdir()) / "maistro-workspace"
    bind_root.mkdir(parents=True, exist_ok=True)
    config = SandboxConfig(timeout_s=10, workspace_host=str(bind_root / "bound-ws"))

    instance = await backend.spawn(config=config)

    assert Path(instance.metadata["workdir"]) == bind_root / "bound-ws"
    assert (bind_root / "bound-ws").is_dir()
    await backend.destroy(instance)
    assert (bind_root / "bound-ws").is_dir()


async def test_spawn_cleans_up_the_owned_workdir_when_the_bind_root_cannot_be_opened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the no-follow descriptor open of the bind root fails, the tempdir is
    reclaimed and the spawn failure propagates — no orphaned host directory."""
    backend = _backend()
    monkeypatch.setattr(backend, "_run", AsyncMock(return_value=(b"container-id", b"", 0)))
    opened: list[str] = []
    real_open = os.open
    attempts = {"n": 0}

    def _failing_open(path: object, *args: object, **kwargs: object) -> int:
        attempts["n"] += 1
        if attempts["n"] == 1:
            # The spawn-time no-follow open of the bind root is the one that
            # fails; later opens belong to cleanup and must work.
            opened.append(str(path))
            raise OSError("bind root vanished")
        return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", _failing_open)
    with pytest.raises(OSError, match="bind root vanished"):
        await backend.spawn(config=SandboxConfig(timeout_s=10))

    monkeypatch.setattr(os, "open", real_open)
    assert opened and len(set(opened)) == 1  # only the bind root was ever opened
    assert not Path(opened[0]).exists()


async def test_spawn_reclaims_the_guest_when_the_run_dies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend()
    remove = AsyncMock()
    monkeypatch.setattr(backend, "_run", AsyncMock(side_effect=RuntimeError("daemon died")))
    monkeypatch.setattr(backend, "_remove_container", remove)
    with pytest.raises(RuntimeError, match="daemon died"):
        await backend.spawn(config=SandboxConfig(timeout_s=10))
    remove.assert_awaited_once()


async def test_spawn_fails_closed_when_docker_rejects_the_guest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend()
    remove = AsyncMock()
    monkeypatch.setattr(backend, "_run", AsyncMock(return_value=(b"", b"boom", 1)))
    monkeypatch.setattr(backend, "_remove_container", remove)
    with pytest.raises(RuntimeError, match="failed to start Kata sandbox: boom"):
        await backend.spawn(config=SandboxConfig(timeout_s=10))
    remove.assert_awaited_once()


async def test_spawn_fails_closed_on_an_empty_container_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend()
    remove = AsyncMock()
    monkeypatch.setattr(backend, "_run", AsyncMock(return_value=(b"", b"", 0)))
    monkeypatch.setattr(backend, "_remove_container", remove)
    with pytest.raises(RuntimeError, match="no container id"):
        await backend.spawn(config=SandboxConfig(timeout_s=10))
    remove.assert_awaited_once()


async def test_run_flags_output_overflow_as_the_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child that floods its pipes is reported as the output-limit exit, so
    spawn failure paths see a failure signal instead of a truncated success."""
    backend = _backend()
    _stdout, _stderr, code = await backend._run(
        ["/bin/sh", "-c", "dd if=/dev/zero bs=1024 count=128 2>/dev/null"]
    )
    assert code == OUTPUT_LIMIT_EXIT_CODE


async def test_operations_on_an_unknown_instance_raise_keyerror(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend()
    ghost = SandboxInstance(id="kata-absent", backend="kata", isolation_tier="vm")

    # Not in _locks: the per-instance lock lookup refuses first.
    with pytest.raises(KeyError, match="no live sandbox"):
        await backend.exec(ghost, ["true"])

    # In _locks but not _instances (a cancelled destroy between the two):
    # the lock is taken, then the instance lookup refuses.
    backend._locks["kata-half"] = asyncio.Lock()
    half = SandboxInstance(id="kata-half", backend="kata", isolation_tier="vm")
    with pytest.raises(KeyError, match="no live sandbox"):
        await backend.exec(half, ["true"])


def test_remove_container_escalates_a_lost_daemon_to_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = _backend()
    monkeypatch.setattr(backend, "_run", AsyncMock(side_effect=OSError("no daemon")))
    with pytest.raises(RuntimeError, match="cannot remove Kata sandbox"):
        asyncio.run(backend._remove_container("kata-test"))
