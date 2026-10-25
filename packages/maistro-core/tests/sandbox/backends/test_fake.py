"""Tests for maistro.sandbox.backends.fake — FakeSandboxBackend (dev/test only, no isolation)."""

from __future__ import annotations

import subprocess

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
    async def test_timeout_returns_124_and_timed_out_true(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        backend = FakeSandboxBackend()
        config = SandboxConfig()
        instance = await backend.spawn(config=config)

        def raise_timeout(*args: object, **kwargs: object) -> None:
            raise subprocess.TimeoutExpired(cmd="sleep", timeout=1)

        monkeypatch.setattr(subprocess, "run", raise_timeout)
        result = await backend.exec(instance, ["sleep", "5"], timeout_s=1)
        assert result.exit_code == 124
        assert result.stdout == ""
        assert result.stderr == "timeout"
        assert result.timed_out is True
        assert result.duration_ms == 1000


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
