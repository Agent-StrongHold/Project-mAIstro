"""Docker container lifecycle management for sandbox execution.

Creates isolated containers for code execution, with resource limits,
network isolation, and environment sanitization.
"""

from __future__ import annotations

import asyncio
import base64
import posixpath
import shlex
import subprocess
import time
import uuid

import structlog

from maistro.config.settings import SandboxSettings
from maistro.security.dangerous_tools import is_dangerous_command
from maistro.tools.sandbox.env_sanitize import sanitize_env
from maistro.tools.sandbox.workspace import CONTAINER_WORKSPACE, ensure_workspace

logger = structlog.get_logger()

# Upper bound on the docker CLI lifecycle subprocesses that have no timeout of
# their own (``docker run`` at creation, ``docker rm -f`` at destroy; ``exec``
# already carries a per-call timeout). Without it a stalled daemon — a slow
# registry pull on a cold CI runner, a hung daemon mid-restart — blocks the
# caller forever: every caller-visible timeout in this module keys off these
# subprocesses completing, so an unbounded wait defeats them all. Observed in
# CI (#965 repair, quality.yml coverage-unit): a swebench evaluator test died
# on the 30s pytest-timeout with the event loop parked in selector.poll while
# ``docker run`` never returned. 120s comfortably covers a cold registry pull
# of the default image while still failing callers within bounded time.
_LIFECYCLE_CLI_TIMEOUT_SECONDS = 120.0


def _shell_quote(s: str) -> str:
    """Shell-quote a string for safe interpolation into bash commands."""
    return shlex.quote(s)


class SandboxContainer:
    """Manages a Docker container for sandboxed code execution.

    Supports use as an async context manager for automatic cleanup.
    """

    def __init__(
        self,
        container_id: str,
        workspace_host: str,
        workspace_container: str = CONTAINER_WORKSPACE,
        ttl: int = 3600,
    ) -> None:
        self.container_id = container_id
        self.workspace_host = workspace_host
        self.workspace_container = workspace_container
        self.created_at = time.monotonic()
        self.ttl = ttl

    @property
    def expired(self) -> bool:
        """Check if container has exceeded its TTL."""
        return (time.monotonic() - self.created_at) > self.ttl

    async def __aenter__(self) -> SandboxContainer:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        """Execute a command in the container. Returns (exit_code, output)."""
        # Check for dangerous commands before execution
        dangers = is_dangerous_command(command)
        if dangers:
            await logger.awarn(
                "dangerous_command_blocked",
                command=command[:200],
                patterns=dangers,
                container=self.container_id[:12],
            )
            return 1, f"Command blocked by safety filter: {', '.join(dangers[:3])}"

        try:
            proc = await asyncio.create_subprocess_exec(
                "docker",
                "exec",
                self.container_id,
                "bash",
                "-c",
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode("utf-8", errors="replace") if stdout else ""
            return proc.returncode or 0, output
        except TimeoutError:
            return 124, f"Command timed out after {timeout}s"
        except FileNotFoundError:
            raise  # Docker binary not installed
        except PermissionError:
            raise  # Docker socket inaccessible
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, f"Exec error: {exc}"

    @staticmethod
    def _safe_path(workspace: str, path: str) -> str:
        """Resolve a path safely within the workspace, blocking escapes."""
        if posixpath.isabs(path):
            raise ValueError(f"Absolute paths are not allowed: {path}")
        normalized = posixpath.normpath(path)
        if normalized.startswith("..") or "/../" in f"/{normalized}/":
            raise ValueError(f"Path traversal detected: {path}")
        return f"{workspace}/{normalized}"

    async def read_file(self, path: str) -> str:
        """Read a file from the container workspace."""
        full_path = self._safe_path(self.workspace_container, path)
        exit_code, output = await self.exec(f"cat -- {_shell_quote(full_path)}")
        if exit_code != 0:
            raise FileNotFoundError(f"Cannot read {path}: {output}")
        return output

    async def write_file(self, path: str, content: str) -> None:
        """Write a file in the container workspace."""
        full_path = self._safe_path(self.workspace_container, path)
        parent = "/".join(full_path.rsplit("/", 1)[:-1])
        if parent:
            await self.exec(f"mkdir -p -- {_shell_quote(parent)}")
        # Use base64 encoding to safely transfer arbitrary content
        encoded = base64.b64encode(content.encode()).decode()
        exit_code, output = await self.exec(
            f"echo {_shell_quote(encoded)} | base64 -d > {_shell_quote(full_path)}"
        )
        if exit_code != 0:
            raise OSError(f"Cannot write {path}: {output}")

    async def destroy(self) -> None:
        """Stop and remove the container."""
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "-f",
            self.container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=_LIFECYCLE_CLI_TIMEOUT_SECONDS
            )
        except TimeoutError:
            # Cleanup is best-effort: a daemon too stalled to answer rm must
            # not turn the context-manager exit (or any caller's cleanup path)
            # into a hang. The container is leaked by design here — the same
            # stall would defeat any in-process retry — so record it and move
            # on; the TTL/expired machinery and external reapers own the rest.
            await logger.awarn(
                "sandbox_destroy_timeout",
                container_id=self.container_id[:12],
                timeout_s=_LIFECYCLE_CLI_TIMEOUT_SECONDS,
            )
            return
        rc = proc.returncode or 0
        if rc != 0:
            err = stderr.decode() if stderr else ""
            await logger.awarning(
                "sandbox_destroy_error",
                container_id=self.container_id[:12],
                exit_code=rc,
                error=err[:200],
            )
        else:
            await logger.ainfo("sandbox_destroyed", container_id=self.container_id[:12])


async def create_sandbox(
    workspace: str,
    settings: SandboxSettings | None = None,
    env: dict[str, str] | None = None,
) -> SandboxContainer:
    """Create and start a new sandbox container."""
    if settings is None:
        settings = SandboxSettings()

    host_path = ensure_workspace(workspace)
    safe_env = sanitize_env(env or {})

    # Use UUID for unique, unpredictable container names
    container_name = f"maistro-sandbox-{uuid.uuid4().hex[:12]}"

    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        container_name,
        f"--memory={settings.memory_limit}",
        f"--cpus={settings.cpu_count}",
        # Security hardening
        "--security-opt=no-new-privileges",
        "--cap-drop=ALL",
        "--cap-add=CHOWN",
        "--cap-add=SETUID",
        "--cap-add=SETGID",
        "--pids-limit=256",
        "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
        # Filesystem
        "-v",
        f"{host_path}:{CONTAINER_WORKSPACE}",
        "-w",
        CONTAINER_WORKSPACE,
    ]

    # Network isolation
    if settings.network_disabled:
        cmd.append("--network=none")

    for k, v in safe_env.items():
        cmd.extend(["-e", f"{k}={v}"])

    cmd.extend([settings.image, "sleep", str(settings.timeout)])

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_LIFECYCLE_CLI_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        # RuntimeError so callers that already fail closed on a failed
        # ``docker run`` (e.g. benchmarks/sandbox_exec.run_function_checks)
        # treat an unresponsive daemon exactly like a refused one.
        raise RuntimeError(
            f"Failed to create sandbox: docker run did not complete within "
            f"{_LIFECYCLE_CLI_TIMEOUT_SECONDS:.0f}s (daemon stalled or image "
            f"{settings.image} pull too slow)"
        ) from exc

    if proc.returncode != 0:
        error = stderr.decode() if stderr else "Unknown error"
        raise RuntimeError(f"Failed to create sandbox: {error}")

    container_id = stdout.decode().strip()
    await logger.ainfo("sandbox_created", container_id=container_id[:12], image=settings.image)

    return SandboxContainer(
        container_id=container_id,
        workspace_host=str(host_path),
        ttl=settings.timeout,
    )
