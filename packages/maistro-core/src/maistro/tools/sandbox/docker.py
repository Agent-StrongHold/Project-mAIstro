"""Docker container lifecycle management for sandbox execution.

Creates isolated containers for code execution, with resource limits,
network isolation, and environment sanitization.
"""

from __future__ import annotations

import asyncio
import posixpath
import shlex
import subprocess
import time
import uuid
from collections.abc import Sequence

import structlog

from maistro.config.settings import SandboxSettings
from maistro.security.dangerous_tools import is_dangerous_command
from maistro.tools.sandbox.env_sanitize import sanitize_env
from maistro.tools.sandbox.workspace import CONTAINER_WORKSPACE, ensure_workspace

logger = structlog.get_logger()


class CommandContractError(ValueError):
    """The command is outside the structured sandbox command language."""


_SHELL_OPERATOR_CHARS = frozenset(";&|<>`$")
_SHELL_INTERPRETERS = frozenset({"sh", "bash", "zsh", "fish"})


def _argv_from_string(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise CommandContractError("invalid command quoting") from exc


def _validate_argv(argv: list[str]) -> None:
    if not argv or any(not isinstance(part, str) or not part for part in argv):
        raise CommandContractError("command argv must contain non-empty strings")


def _reject_shell_syntax(argv: list[str], *, from_string: bool) -> None:
    if from_string and any(any(char in part for char in _SHELL_OPERATOR_CHARS) for part in argv):
        raise CommandContractError("shell operators are not allowed; provide structured argv")
    if argv[0].rsplit("/", 1)[-1] in _SHELL_INTERPRETERS or "-c" in argv[1:]:
        raise CommandContractError("shell interpreters are not allowed")


def parse_command(command: str | Sequence[str]) -> list[str]:
    """Parse the narrow command language used by the Docker backend.

    Strings remain a compatibility input for existing callers, but are parsed
    into argv and never passed to a shell. Shell operators and shell launchers
    are rejected rather than treated as an isolation boundary.
    """
    argv = _argv_from_string(command) if isinstance(command, str) else list(command)
    _validate_argv(argv)
    _reject_shell_syntax(argv, from_string=isinstance(command, str))
    return argv


async def _run_argv(
    container_id: str,
    argv: list[str],
    *,
    timeout: int,
    input_data: str | bytes | None,
) -> tuple[int, str]:
    """Run argv via ``docker exec`` and collect output; no shell involved."""
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "exec",
        container_id,
        *argv,
        stdin=asyncio.subprocess.PIPE if input_data is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    payload = input_data.encode() if isinstance(input_data, str) else input_data
    communicate = proc.communicate() if payload is None else proc.communicate(payload)
    stdout, _ = await asyncio.wait_for(communicate, timeout=timeout)
    output = stdout.decode("utf-8", errors="replace") if stdout else ""
    return proc.returncode or 0, output


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

    async def exec(
        self,
        command: str | Sequence[str],
        timeout: int = 60,
        input_data: str | bytes | None = None,
    ) -> tuple[int, str]:
        """Execute validated argv in the container; never invoke a shell."""
        try:
            argv = parse_command(command)
        except CommandContractError as exc:
            return 1, f"Command blocked: {exc}"
        dangers = is_dangerous_command(" ".join(shlex.quote(part) for part in argv))
        if dangers:
            await logger.awarn(
                "dangerous_command_blocked",
                command=command[:200],
                patterns=dangers,
                container=self.container_id[:12],
            )
            return 1, f"Command blocked by safety filter: {', '.join(dangers[:3])}"

        try:
            return await _run_argv(self.container_id, argv, timeout=timeout, input_data=input_data)
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
        exit_code, output = await self.exec(["cat", "--", full_path])
        if exit_code != 0:
            raise FileNotFoundError(f"Cannot read {path}: {output}")
        return output

    async def write_file(self, path: str, content: str) -> None:
        """Write a file in the container workspace."""
        full_path = self._safe_path(self.workspace_container, path)
        parent = posixpath.dirname(full_path)
        if parent:
            exit_code, output = await self.exec(["mkdir", "-p", "--", parent])
            if exit_code != 0:
                raise OSError(f"Cannot write {path}: {output}")
        exit_code, output = await self.exec(["tee", "--", full_path], input_data=content)
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
        _, stderr = await proc.communicate()
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
    stdout, stderr = await proc.communicate()

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
