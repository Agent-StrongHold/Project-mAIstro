"""Run conformance against the selected production VM, never a replacement fixture.

Missing Kata/KVM is an explicit skip, not evidence of VM containment. A host
advertising the supported profile must actually launch all declared policies.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from maistro.sandbox import (
    BENCHMARK_EVAL,
    BROWSER_AUTOMATION,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    build_selector,
    detect_host_capabilities,
)


@pytest.fixture
def vm_selector():
    caps = detect_host_capabilities()
    if not caps.supports("vm"):
        pytest.skip(f"Kata deployment profile unavailable: {caps.notes.get('vm')}")
    return build_selector(capabilities=caps)


@pytest.fixture
async def live_vm(vm_selector):
    tier, backend = vm_selector.select(UNTRUSTED_CODE)
    assert tier == "vm"
    config = replace(
        vm_selector.build_config(UNTRUSTED_CODE, memory_mb=128, timeout_s=60),
        max_file_mb=1,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        env={"MAISTRO_CONFORMANCE_MARKER": "explicit-guest-value"},
    )
    instance = await backend.spawn(config=config)
    try:
        yield backend, instance
    finally:
        await backend.destroy(instance)
        await backend.destroy(instance)


@pytest.mark.parametrize(
    "policy", [UNTRUSTED_CODE, BENCHMARK_EVAL, TRUSTED_TOOL, BROWSER_AUTOMATION]
)
async def test_supported_policy_launches_real_work(vm_selector, policy):
    _tier, backend = vm_selector.select(policy)
    instance = await backend.spawn(config=vm_selector.build_config(policy))
    try:
        result = await backend.exec(instance, ["python", "-c", "print('real-vm-work')"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "real-vm-work"
    finally:
        await backend.destroy(instance)


async def test_selected_vm_denies_host_files_sockets_network_and_privilege(live_vm, tmp_path):
    backend, instance = live_vm
    marker = tmp_path / "host-only-secret"
    marker.write_text("must-never-enter-guest")
    script = f"""
import os, socket
from pathlib import Path
assert not Path({str(marker)!r}).exists()
assert not Path('/var/run/docker.sock').exists()
assert not Path('/run/containerd/containerd.sock').exists()
assert not Path('/dev/kvm').exists()
status = Path('/proc/self/status').read_text()
assert 'CapEff:\\t0000000000000000' in status
assert 'NoNewPrivs:\\t1' in status
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    pass
else:
    raise AssertionError('default-deny allowed external egress')
print('contained')
"""
    result = await backend.exec(instance, ["python", "-c", script])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.strip() == "contained"


async def test_selected_vm_transfers_files_and_only_explicit_environment(live_vm):
    backend, instance = live_vm
    await backend.write_file(instance, "/workspace/nested/value", b"input")
    result = await backend.exec(
        instance,
        [
            "python",
            "-c",
            """
import os
from pathlib import Path
assert os.environ['MAISTRO_CONFORMANCE_MARKER'] == 'explicit-guest-value'
assert 'AWS_SECRET_ACCESS_KEY' not in os.environ
assert Path('/workspace/nested/value').read_bytes() == b'input'
Path('/workspace/output').write_bytes(b'result')
""",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert await backend.read_file(instance, "/workspace/output") == b"result"


async def test_selected_vm_enforces_file_budget(live_vm):
    backend, instance = live_vm
    result = await backend.exec(
        instance,
        [
            "python",
            "-c",
            """
from pathlib import Path
Path('/workspace/too-big').write_bytes(b'x' * (2 * 1024 * 1024))
""",
        ],
    )
    assert result.exit_code != 0
    assert not result.timed_out


async def test_selected_vm_output_overflow_removes_guest(live_vm):
    backend, instance = live_vm
    result = await backend.exec(instance, ["python", "-c", "print('x' * 100000)"])
    assert result.exit_code == 125
    assert result.output_limit_exceeded
    assert result.stdout_truncated
    assert result.stdout_bytes_retained == 1024
    stopped = await backend.exec(instance, ["python", "-c", "print('still-running')"])
    assert stopped.exit_code != 0
    assert "still-running" not in stopped.stdout


async def test_selected_vm_timeout_removes_guest(live_vm):
    backend, instance = live_vm
    result = await backend.exec(
        instance, ["python", "-c", "import time; time.sleep(60)"], timeout_s=1
    )
    assert result.timed_out
    assert result.exit_code == 124
    stopped = await backend.exec(instance, ["python", "-c", "print('still-running')"])
    assert stopped.exit_code != 0


async def test_selected_vm_cancellation_removes_guest(live_vm):
    backend, instance = live_vm
    # A workspace handshake proves the command really entered the VM before
    # cancellation; do not confuse cancelling an unstarted coroutine with cleanup.
    task = asyncio.create_task(
        backend.exec(
            instance,
            [
                "python",
                "-c",
                """
import time
from pathlib import Path
Path('/workspace/started').touch()
time.sleep(60)
""",
            ],
        )
    )
    try:
        async with asyncio.timeout(20):
            while not (Path(instance.metadata["workdir"]) / "started").exists():
                await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        stopped = await backend.exec(instance, ["python", "-c", "print('still-running')"])
        assert stopped.exit_code != 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
