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

from maistro.sandbox.capture import capture_process
from maistro.sandbox.network import EgressMode, resolve_grant
from maistro.sandbox.paths import make_beneath_guest_readable, read_beneath, write_beneath
from maistro.sandbox.protocol import (
    OUTPUT_LIMIT_EXIT_CODE,
    ExecResult,
    SandboxConfig,
    SandboxInstance,
)
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
        self._instances: dict[str, tuple[SandboxConfig, Path, bool, int]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

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
        # Kata's virtiofs share enforces the host's mode bits against the
        # guest's id mapping, and this backend's guests run with every
        # capability dropped: a 0700 mkdtemp bind root owned by the host uid
        # is neither traversable nor writable even by guest root, which makes
        # the /workspace transfer contract unusable in both directions. The
        # bind is the workload's scratch by definition, so the root gets
        # /tmp semantics (sticky, world-writable); written contents are
        # widened per-write by make_beneath_guest_readable, and the bind's
        # parent keeps the host-side permissions that fence the mount.
        workdir.chmod(0o1777)

        command = self.build_run_argv(config, sid, workdir)
        try:
            workdir_fd = os.open(workdir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError:
            await self._cleanup_workdir(workdir, owned)
            raise
        try:
            stdout, stderr, returncode = await self._run(command)
        except BaseException:
            # Cancellation can arrive after Docker created the guest but before
            # its id was returned. The deterministic name lets cleanup reclaim
            # that guest without relying on a host process hook.
            os.close(workdir_fd)
            await self._remove_container(sid)
            await self._cleanup_workdir(workdir, owned)
            raise
        if returncode != 0:
            os.close(workdir_fd)
            await self._remove_container(sid)
            await self._cleanup_workdir(workdir, owned)
            detail = stderr.decode(errors="replace").strip() or "unknown error"
            raise RuntimeError(f"failed to start Kata sandbox: {detail}")
        container_id = stdout.decode(errors="replace").strip()
        if not container_id:
            os.close(workdir_fd)
            await self._remove_container(sid)
            await self._cleanup_workdir(workdir, owned)
            raise RuntimeError("Kata runtime returned no container id")
        self._instances[sid] = (config, workdir, owned, workdir_fd)
        self._locks[sid] = asyncio.Lock()
        logger.info("sandbox_spawned id=%s tier=vm runtime=kata", sid)
        return SandboxInstance(
            id=sid,
            backend="kata",
            isolation_tier=self.tier,
            metadata={"container_id": container_id, "workdir": str(workdir)},
        )

    @staticmethod
    async def _cleanup_workdir(workdir: Path, owned: bool) -> None:
        """Release ephemeral scratch only; never remove a caller-owned bind."""
        if owned:
            await asyncio.to_thread(shutil.rmtree, workdir, True)

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
        async with self._lock(instance):
            config, _workdir, _owned, _fd = self._require(instance)
            start = time.monotonic()
            try:
                process = await asyncio.create_subprocess_exec(
                    self._docker or "docker",
                    "exec",
                    instance.id,
                    *self._exec_argv(command),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
                captured = await capture_process(
                    process,
                    timeout_s=min(timeout_s, config.timeout_s),
                    max_stdout_bytes=config.max_stdout_bytes,
                    max_stderr_bytes=config.max_stderr_bytes,
                )
            except BaseException:
                # Killing the host Docker client alone does not stop guest exec.
                await self._remove_container(instance.id)
                raise
            exit_code = process.returncode if process.returncode is not None else -1
            if captured.timed_out or captured.output_limit_exceeded:
                await self._remove_container(instance.id)
                exit_code = (
                    OUTPUT_LIMIT_EXIT_CODE if captured.output_limit_exceeded else TIMEOUT_EXIT_CODE
                )
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

    async def destroy(self, instance: SandboxInstance) -> None:
        lock = self._locks.get(instance.id)
        if lock is None:
            return
        async with lock:
            entry = self._instances.get(instance.id)
            if entry is None:
                return
            _config, workdir, owned, fd = entry
            await self._remove_container(instance.id)
            # Keep the instance retryable if removal is cancelled.
            self._instances.pop(instance.id)
            os.close(fd)
            await self._cleanup_workdir(workdir, owned)
            self._locks.pop(instance.id, None)

    @staticmethod
    def _exec_argv(command: list[str]) -> list[str]:
        """Enforce the spawn-time no-new-privileges promise on `docker exec`.

        Kata's guest agent applies the container's no-new-privileges flag to
        the init process but *not* to processes created by a later exec, so a
        bare `docker exec` would run with ``NoNewPrivs: 0`` inside a guest
        whose spawn advertised ``--security-opt=no-new-privileges``. The
        promise is the backend's, not the agent's, so exec re-asserts it via
        util-linux ``setpriv`` (present in the shipped guest image; a guest
        image without it fails the exec closed instead of silently weaker).
        """
        return ["setpriv", "--no-new-privs", *command]

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        async with self._lock(instance):
            _config, _workdir, _owned, fd = self._require(instance)
            await asyncio.to_thread(write_beneath, fd, path, content, mount="/workspace")
            # Kata's virtiofs share enforces host mode bits against the guest's
            # id mapping, so the 0700/0600 transfer defaults are invisible to
            # guest root. Widen the written chain without giving up the
            # no-follow walk (see make_beneath_guest_readable).
            await asyncio.to_thread(make_beneath_guest_readable, fd, path, mount="/workspace")

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        async with self._lock(instance):
            _config, _workdir, _owned, fd = self._require(instance)
            return await asyncio.to_thread(read_beneath, fd, path, mount="/workspace")

    async def _remove_container(self, container_id: str) -> None:
        try:
            _stdout, stderr, code = await self._run(
                [self._docker or "docker", "rm", "-f", container_id]
            )
        except OSError as exc:
            raise RuntimeError(f"cannot remove Kata sandbox {container_id}") from exc
        if code != 0 and b"No such container" not in stderr:
            raise RuntimeError(
                f"cannot remove Kata sandbox {container_id}: {stderr.decode(errors='replace')}"
            )

    async def _run(self, argv: list[str]) -> tuple[bytes, bytes, int]:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        captured = await capture_process(process, timeout_s=30)
        code = process.returncode if process.returncode is not None else -1
        if captured.timed_out or captured.output_limit_exceeded:
            code = OUTPUT_LIMIT_EXIT_CODE if captured.output_limit_exceeded else TIMEOUT_EXIT_CODE
        return captured.stdout, captured.stderr, code

    def _lock(self, instance: SandboxInstance) -> asyncio.Lock:
        lock = self._locks.get(instance.id)
        if lock is None:
            raise KeyError(f"no live sandbox {instance.id!r}")
        return lock

    def _require(self, instance: SandboxInstance) -> tuple[SandboxConfig, Path, bool, int]:
        entry = self._instances.get(instance.id)
        if entry is None:
            raise KeyError(f"no live sandbox {instance.id!r}")
        return entry


__all__ = ["KataSandboxBackend", "KataUnavailableError"]
