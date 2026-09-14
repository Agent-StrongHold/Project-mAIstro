"""Socket-less container backend behind the canonical sandbox protocol.

This is a transitional Tier-3 backend, not a second policy authority.  The
Docker/Podman CLI is used only to launch the backend; no container receives a
host socket, ambient environment, or an unvalidated host mount.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from maistro.config.settings import SandboxSettings
from maistro.sandbox.capture import capture_process
from maistro.sandbox.network import EgressMode, resolve_grant
from maistro.sandbox.paths import read_beneath, validate_host_root, write_beneath
from maistro.sandbox.protocol import (
    OUTPUT_LIMIT_EXIT_CODE,
    ExecResult,
    SandboxConfig,
    SandboxInstance,
)
from maistro.tools.sandbox.env_sanitize import sanitize_env

TIMEOUT_EXIT_CODE = 124


class ContainerUnavailableError(RuntimeError):
    """The configured container CLI is not available."""


@dataclass
class _LiveContainer:
    config: SandboxConfig
    root: Path
    remove_root: bool


class ContainerSandboxBackend:
    """Run one ephemeral, hardened, socket-less container per sandbox."""

    tier = "container"
    supports_scoped_egress = False

    def __init__(
        self,
        *,
        binary: str | None = None,
        settings: SandboxSettings | None = None,
        root: Path | None = None,
    ) -> None:
        self._binary = binary or shutil.which("docker") or shutil.which("podman")
        if self._binary is None:
            raise ContainerUnavailableError("no Docker or Podman CLI is available")
        self._settings = settings or SandboxSettings()
        self._root = validate_host_root(root, create=True) if root is not None else None
        self._instances: dict[str, _LiveContainer] = {}

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        sid = f"container-{uuid4().hex[:8]}"
        resolve_grant(
            config.egress,
            backend_name=type(self).__name__,
            supports_scoped_egress=self.supports_scoped_egress,
            sandbox_id=sid,
        )
        if len(config.writable_paths) > 1:
            raise ValueError("container backend accepts one authorized workspace root")
        if config.writable_paths:
            workdir = validate_host_root(config.writable_paths[0], create=True)
            remove_root = False
        else:
            parent = self._root
            if parent is None:
                parent = validate_host_root("/tmp/maistro-workspace", create=True)
            workdir = Path(tempfile.mkdtemp(prefix=f"{sid}-", dir=parent))
            remove_root = True

        env = sanitize_env(config.env)
        if config.fence is not None:
            env.update(config.fence.to_env())
        command = [
            self._binary,
            "run",
            "-d",
            "--name",
            sid,
            "--workdir",
            "/work",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            f"--memory={max(config.memory_mb, 1)}m",
            f"--cpus={max(config.cpu_cores, 0.01)}",
            f"--pids-limit={max(config.max_processes, 1)}",
            "--user",
            "65532:65532",
            "--network=none",
            "-v",
            f"{workdir}:/work:rw",
        ]
        if config.egress.mode is EgressMode.HOST:
            command[command.index("--network=none")] = "--network=host"
        for key, value in sorted(env.items()):
            command.extend(["-e", f"{key}={value}"])
        command.extend([self._settings.image, "sleep", "infinity"])

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            if remove_root:
                await asyncio.to_thread(shutil.rmtree, workdir, True)
            detail = stderr.decode(errors="replace")[-4000:]
            raise RuntimeError(f"container backend failed to start: {detail}")
        container_id = stdout.decode(errors="replace").strip()
        self._instances[sid] = _LiveContainer(config, workdir, remove_root)
        return SandboxInstance(
            id=sid,
            backend="container",
            isolation_tier=self.tier,
            metadata={"container_id": container_id, "workdir": str(workdir)},
        )

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        live = self._require(instance)
        if not command:
            raise ValueError("sandbox command cannot be empty")
        start = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            self._binary,
            "exec",
            "-i",
            instance.id,
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        captured = await capture_process(
            process,
            timeout_s=min(timeout_s, live.config.timeout_s),
            max_stdout_bytes=live.config.max_stdout_bytes,
            max_stderr_bytes=live.config.max_stderr_bytes,
        )
        exit_code = process.returncode if process.returncode is not None else -1
        if captured.timed_out:
            exit_code = TIMEOUT_EXIT_CODE
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
        live = self._require(instance)
        await asyncio.to_thread(write_beneath, live.root, path, content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        live = self._require(instance)
        return await asyncio.to_thread(read_beneath, live.root, path)

    async def destroy(self, instance: SandboxInstance) -> None:
        live = self._instances.pop(instance.id, None)
        if live is None:
            return
        process = await asyncio.create_subprocess_exec(
            self._binary,
            "rm",
            "-f",
            instance.id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await process.communicate()
        if live.remove_root:
            await asyncio.to_thread(shutil.rmtree, live.root, True)

    def _require(self, instance: SandboxInstance) -> _LiveContainer:
        live = self._instances.get(instance.id)
        if live is None:
            raise KeyError(f"no live sandbox {instance.id!r}")
        return live


__all__ = ["ContainerSandboxBackend", "ContainerUnavailableError"]
