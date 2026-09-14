"""Kata Containers backend for the canonical sandbox authority.

Kata runs an OCI container in a hardware-backed VM while retaining the small
lifecycle surface needed by :class:`SandboxProtocol`. Docker is only the OCI
transport here; callers cannot select it independently or change the policy
that led to this backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from pathlib import Path
from uuid import uuid4

from maistro.sandbox.network import EgressMode, resolve_grant
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance
from maistro.tools.sandbox.workspace import validate_workspace_path

logger = logging.getLogger("maistro.sandbox.kata")
TIMEOUT_EXIT_CODE = 124


class KataUnavailableError(RuntimeError):
    """Raised when the configured host cannot launch a Kata workload."""


class KataSandboxBackend:
    """A real Tier-1 backend using Docker's configured Kata runtime.

    The Docker daemon is an implementation detail of this backend. No daemon
    socket, host credential, or host root is mounted into the guest.
    """

    tier = "vm"
    supports_scoped_egress = False

    def __init__(
        self,
        *,
        docker: str | None = None,
        kata_runtime: str | None = None,
        image: str | None = None,
    ) -> None:
        self._docker = docker or shutil.which("docker")
        self._kata_runtime = kata_runtime or shutil.which("kata-runtime")
        if self._docker is None or self._kata_runtime is None:
            raise KataUnavailableError(
                "Kata requires both docker and kata-runtime on PATH; refusing to claim a VM tier"
            )
        self._image = image or os.environ.get("SANDBOX_IMAGE", "python:3.12-slim")
        self._instances: dict[str, tuple[SandboxConfig, Path, bool]] = {}

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        sid = f"kata-{uuid4().hex[:12]}"
        resolve_grant(
            config.egress,
            backend_name=type(self).__name__,
            supports_scoped_egress=self.supports_scoped_egress,
            sandbox_id=sid,
        )
        if config.workspace_host is None:
            import tempfile

            workdir = Path(tempfile.mkdtemp(prefix=f"{sid}-"))
            owned = True
        else:
            # The host-side bind is an authority boundary too; do not let a
            # protocol caller turn it into an arbitrary host-path reader.
            workdir = validate_workspace_path(config.workspace_host)
            workdir.mkdir(parents=True, exist_ok=True)
            owned = False

        command = self.build_run_argv(config, sid, workdir)
        try:
            stdout, stderr, returncode = await self._run(command)
        except BaseException:
            # Cancellation can arrive after Docker created the guest but before
            # its id was returned. The deterministic name lets cleanup reclaim
            # that guest without relying on a host process hook.
            await self._remove_container(sid)
            if owned:
                await asyncio.to_thread(shutil.rmtree, workdir, True)
            raise
        if returncode != 0:
            if owned:
                await asyncio.to_thread(shutil.rmtree, workdir, True)
            detail = stderr.decode(errors="replace").strip() or "unknown error"
            raise RuntimeError(f"failed to start Kata sandbox: {detail}")
        container_id = stdout.decode(errors="replace").strip()
        if not container_id:
            if owned:
                await asyncio.to_thread(__import__("shutil").rmtree, workdir, True)
            raise RuntimeError("Kata runtime returned no container id")
        self._instances[sid] = (config, workdir, owned)
        logger.info("sandbox_spawned id=%s tier=vm runtime=kata", sid)
        return SandboxInstance(
            id=sid,
            backend="kata",
            isolation_tier=self.tier,
            metadata={"container_id": container_id, "workdir": str(workdir)},
        )

    def build_run_argv(self, config: SandboxConfig, name: str, workdir: Path) -> list[str]:
        """Build the locked-down OCI launch command without executing it."""
        network = config.egress.mode
        if network is EgressMode.SCOPED:
            raise ValueError("Kata backend cannot filter scoped egress destinations")
        argv = [
            self._docker or "docker",
            "run",
            "-d",
            "--runtime=kata",
            "--name",
            name,
            f"--memory={max(config.memory_mb, 1)}m",
            f"--cpus={max(config.cpu_cores, 0.01)}",
            f"--pids-limit={max(config.max_processes, 1)}",
            f"--ulimit=fsize={max(config.max_file_mb, 1) * 1024 * 1024}:{max(config.max_file_mb, 1) * 1024 * 1024}",
            f"--ulimit=cpu={max(1, int(config.timeout_s * max(config.cpu_cores, 0.01)))}:{max(1, int(config.timeout_s * max(config.cpu_cores, 0.01)))}",
            f"--ulimit=nproc={max(config.max_processes, 1)}:{max(config.max_processes, 1)}",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--read-only",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--volume",
            f"{workdir}:/workspace:rw",
            "--workdir",
            "/workspace",
        ]
        if network is EgressMode.DENY:
            argv.append("--network=none")
        elif network is EgressMode.HOST:
            argv.append("--network=host")
        for key, value in sorted(config.env.items()):
            argv += ["--env", f"{key}={value}"]
        if config.fence is not None:
            for key, value in sorted(config.fence.to_env().items()):
                argv += ["--env", f"{key}={value}"]
        argv += [config.image or self._image, "sleep", str(max(config.timeout_s, 1))]
        return argv

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        config, _workdir, _owned = self._require(instance)
        container_id = str(instance.metadata["container_id"])
        start = time.monotonic()
        process = await asyncio.create_subprocess_exec(
            self._docker or "docker",
            "exec",
            container_id,
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=min(timeout_s, config.timeout_s)
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            await self._remove_container(container_id)
            return ExecResult(
                exit_code=TIMEOUT_EXIT_CODE,
                stdout="",
                stderr=f"sandbox timed out after {timeout_s}s",
                duration_ms=int((time.monotonic() - start) * 1000),
                timed_out=True,
            )
        return ExecResult(
            exit_code=process.returncode if process.returncode is not None else -1,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def destroy(self, instance: SandboxInstance) -> None:
        entry = self._instances.pop(instance.id, None)
        if entry is None:
            return
        _config, workdir, owned = entry
        await self._remove_container(str(instance.metadata["container_id"]))
        if owned:
            await asyncio.to_thread(shutil.rmtree, workdir, True)

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        await asyncio.to_thread(self._resolve(instance, path).write_bytes, content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        return await asyncio.to_thread(self._resolve(instance, path).read_bytes)

    async def _remove_container(self, container_id: str) -> None:
        try:
            process = await asyncio.create_subprocess_exec(
                self._docker or "docker",
                "rm",
                "-f",
                container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            return
        await process.communicate()

    async def _run(self, argv: list[str]) -> tuple[bytes, bytes, int]:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        return stdout, stderr, process.returncode if process.returncode is not None else -1

    def _resolve(self, instance: SandboxInstance, path: str) -> Path:
        _config, workdir, _owned = self._require(instance)
        relative = Path(path)
        if relative.is_absolute():
            try:
                relative = relative.relative_to("/workspace")
            except ValueError:
                raise ValueError(f"path {path!r} is outside the sandbox") from None
        target = (workdir / relative).resolve()
        if not target.is_relative_to(workdir.resolve()):
            raise ValueError(f"path {path!r} escapes the sandbox workspace")
        return target

    def _require(self, instance: SandboxInstance) -> tuple[SandboxConfig, Path, bool]:
        entry = self._instances.get(instance.id)
        if entry is None:
            raise KeyError(f"no live sandbox {instance.id!r}")
        return entry


__all__ = ["KataSandboxBackend", "KataUnavailableError"]
