"""Conformance for the shipped Tier-1 Kata backend and canonical wiring."""

from __future__ import annotations

import asyncio
import os
import sys
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
from maistro.sandbox.backends.kata import KataSandboxBackend
from maistro.sandbox.network import EgressGrant, EgressMode


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
