"""Tests for maistro.sandbox.backends.fake — FakeSandboxBackend (dev/test only, no isolation)."""

from __future__ import annotations

import sys

import pytest

from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.protocol import SandboxConfig


class TestSpawn:
    @pytest.mark.asyncio
    async def test_returns_instance_with_fake_backend_and_tier(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        assert instance.backend == "fake"
        assert instance.isolation_tier == "fake"
        assert instance.id.startswith("fake-")

    @pytest.mark.asyncio
    async def test_stores_config_under_instance_id(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig(memory_mb=512)
        instance = await backend.spawn(config=config)
        assert backend._instances[instance.id] is config


class TestExec:
    @pytest.mark.asyncio
    async def test_success_returns_exit_code_and_stdout(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        result = await backend.exec(instance, ["python3", "-c", "print('hi')"])
        assert result.exit_code == 0
        assert result.stdout.strip() == "hi"
        assert result.timed_out is False
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_nonzero_exit_code_propagated(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        result = await backend.exec(instance, ["python3", "-c", "import sys; sys.exit(3)"])
        assert result.exit_code == 3
        assert result.timed_out is False

    @pytest.mark.asyncio
    async def test_timeout_returns_124_and_timed_out_true(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)

        result = await backend.exec(
            instance,
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout_s=0.05,
        )
        assert result.exit_code == 124
        assert result.stdout == ""
        assert result.timed_out is True
        assert result.duration_ms >= 0

    async def test_simultaneous_output_overflow_is_bounded_and_terminates(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig(max_stdout_bytes=1024, max_stderr_bytes=1024)
        instance = await backend.spawn(config=config)
        script = (
            "import os, threading\n"
            "def flood(fd, value):\n"
            "    while True: os.write(fd, value * 4096)\n"
            "threading.Thread(target=flood, args=(1, b'o'), daemon=True).start()\n"
            "threading.Thread(target=flood, args=(2, b'e'), daemon=True).start()\n"
            "threading.Event().wait()\n"
        )

        result = await backend.exec(instance, [sys.executable, "-c", script], timeout_s=5)

        assert result.exit_code == 125
        assert result.output_limit_exceeded is True
        assert result.output_truncated is True
        assert result.stdout_bytes_retained <= config.max_stdout_bytes
        assert result.stderr_bytes_retained <= config.max_stderr_bytes
        assert result.stdout_truncated or result.stderr_truncated
        assert len(result.stdout.encode()) == result.stdout_bytes_retained
        assert len(result.stderr.encode()) == result.stderr_bytes_retained

    @pytest.mark.parametrize(
        ("fd", "truncated_field"),
        [(1, "stdout_truncated"), (2, "stderr_truncated")],
    )
    async def test_each_stream_overflow_is_reported(self, fd: int, truncated_field: str) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig(max_stdout_bytes=1024, max_stderr_bytes=1024)
        instance = await backend.spawn(config=config)
        script = f"import os\nwhile True: os.write({fd}, b'x' * 4096)"

        result = await backend.exec(instance, [sys.executable, "-c", script], timeout_s=5)

        assert result.output_limit_exceeded is True
        assert getattr(result, truncated_field) is True
        assert result.stdout_bytes <= config.max_stdout_bytes
        assert result.stderr_bytes <= config.max_stderr_bytes

    async def test_workload_cannot_raise_host_capture_ceiling(self) -> None:
        from maistro.sandbox import MAX_OUTPUT_CAPTURE_BYTES

        config = SandboxConfig(
            max_stdout_bytes=MAX_OUTPUT_CAPTURE_BYTES * 100,
            max_stderr_bytes=MAX_OUTPUT_CAPTURE_BYTES * 100,
        )

        assert config.max_stdout_bytes == MAX_OUTPUT_CAPTURE_BYTES
        assert config.max_stderr_bytes == MAX_OUTPUT_CAPTURE_BYTES


class TestWriteReadFile:
    @pytest.mark.asyncio
    async def test_write_then_read_round_trips_bytes(self, tmp_path: object) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        path = str(tmp_path) + "/out.bin"  # type: ignore[operator]
        await backend.write_file(instance, path, b"hello bytes")
        content = await backend.read_file(instance, path)
        assert content == b"hello bytes"


class TestDestroy:
    @pytest.mark.asyncio
    async def test_removes_instance(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        assert instance.id in backend._instances
        await backend.destroy(instance)
        assert instance.id not in backend._instances

    @pytest.mark.asyncio
    async def test_destroy_unknown_instance_does_not_raise(self) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)
        await backend.destroy(instance)
        await backend.destroy(instance)

        assert backend._instances == {}
