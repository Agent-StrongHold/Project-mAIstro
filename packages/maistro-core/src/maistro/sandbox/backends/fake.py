"""Fake sandbox backend — for unit tests and dev mode only.

No real isolation. Executes in-process. Exists so the selector has something
to register in tests and so dev mode doesn't require KVM.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from maistro.sandbox.protocol import (
    ExecResult,
    SandboxConfig,
    SandboxInstance,
    clamped_output_limit,
)
from maistro.tools.sandbox._capture import run_bounded

logger = logging.getLogger("maistro.sandbox.backends.fake")


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
        # Same contract as the real backends: an unknown/destroyed instance is
        # a KeyError, and the retention bound comes from the spawned config.
        config = self._instances[instance.id]
        # Bounded capture (#1197): the fake runs without isolation, which is
        # exactly why its host-side capture must obey the same bound as the
        # real backends — the workload is untrusted in dev mode too.
        r = await asyncio.to_thread(
            run_bounded,
            command,
            limit=clamped_output_limit(config.max_output_bytes),
            timeout=timeout_s,
        )
        if r.timed_out:
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr="timeout",
                duration_ms=timeout_s * 1000,
                timed_out=True,
            )
        result = ExecResult(
            exit_code=r.exit_code,
            stdout=r.stdout.data.decode(errors="replace"),
            stderr=r.stderr.data.decode(errors="replace"),
            duration_ms=int((time.monotonic() - start) * 1000),
            stdout_bytes=len(r.stdout.data),
            stderr_bytes=len(r.stderr.data),
            stdout_truncated=r.stdout.truncated,
            stderr_truncated=r.stderr.truncated,
        )
        # Same audit contract as the real backends (#1197): a dev-mode fake
        # runs untrusted workloads too, so partial evidence is declared where
        # it happens, not silently passed upstream.
        if note := result.truncation_summary():
            logger.warning(
                "sandbox_exec_output_truncated id=%s exit_code=%s: %s",
                instance.id,
                result.exit_code,
                note,
            )
        return result

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        import pathlib

        pathlib.Path(path).write_bytes(content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        import pathlib

        return pathlib.Path(path).read_bytes()

    async def destroy(self, instance: SandboxInstance) -> None:
        self._instances.pop(instance.id, None)
