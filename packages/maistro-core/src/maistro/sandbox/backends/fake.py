"""Fake sandbox backend — for unit tests and dev mode only.

No real isolation. Executes in-process. Exists so the selector has something
to register in tests and so dev mode doesn't require KVM.
"""

from __future__ import annotations

import asyncio
import time
from uuid import uuid4

from maistro.sandbox.capture import capture_process
from maistro.sandbox.protocol import (
    OUTPUT_LIMIT_EXIT_CODE,
    ExecResult,
    SandboxConfig,
    SandboxInstance,
)


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
        config = self._instances.get(instance.id)
        if config is None:
            raise KeyError(f"no live sandbox {instance.id!r}; it was destroyed or never spawned")
        start = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        captured = await capture_process(
            process,
            timeout_s=timeout_s,
            max_stdout_bytes=config.max_stdout_bytes,
            max_stderr_bytes=config.max_stderr_bytes,
        )
        exit_code = process.returncode if process.returncode is not None else -1
        if captured.timed_out:
            exit_code = 124
        elif captured.output_limit_exceeded:
            exit_code = OUTPUT_LIMIT_EXIT_CODE
        return ExecResult(
            exit_code=exit_code,
            stdout=captured.stdout.decode(errors="replace"),
            stderr=captured.stderr.decode(errors="replace"),
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=captured.timed_out,
            output_limit_exceeded=captured.output_limit_exceeded,
            stdout_truncated=captured.stdout_truncated,
            stderr_truncated=captured.stderr_truncated,
            stdout_bytes_retained=len(captured.stdout),
            stderr_bytes_retained=len(captured.stderr),
        )

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        import pathlib

        pathlib.Path(path).write_bytes(content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        import pathlib

        return pathlib.Path(path).read_bytes()

    async def destroy(self, instance: SandboxInstance) -> None:
        self._instances.pop(instance.id, None)
