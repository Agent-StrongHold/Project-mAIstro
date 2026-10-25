"""Fake sandbox backend — for unit tests and dev mode only.

No real isolation. Executes in-process. Exists so the selector has something
to register in tests and so dev mode doesn't require KVM.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from uuid import uuid4

from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance


class FakeSandboxBackend:
    """In-process fake. No isolation. Dev/test only."""

    tier = "fake"

    def __init__(self) -> None:
        self._instances: dict[str, SandboxConfig] = {}

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        sid = f"fake-{uuid4().hex[:8]}"
        self._instances[sid] = config
        return SandboxInstance(id=sid, backend="fake", isolation_tier="fake")

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        start = time.monotonic()
        try:
            r = await asyncio.to_thread(
                subprocess.run, command, capture_output=True, text=True, timeout=timeout_s
            )
            return ExecResult(
                exit_code=r.returncode,
                stdout=r.stdout,
                stderr=r.stderr,
                duration_ms=int((time.monotonic() - start) * 1000),
            )
        except subprocess.TimeoutExpired:
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr="timeout",
                duration_ms=timeout_s * 1000,
                timed_out=True,
            )

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        import pathlib

        pathlib.Path(path).write_bytes(content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        import pathlib

        return pathlib.Path(path).read_bytes()

    async def destroy(self, instance: SandboxInstance) -> None:
        self._instances.pop(instance.id, None)
