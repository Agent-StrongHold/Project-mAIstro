"""Bubblewrap sandbox backend — a real Tier-3 boundary (ADR-093, #76).

The first backend in this subsystem that actually isolates anything. It drives
the `bwrap` binary, so the containment is the kernel's user-namespace, mount-
namespace and seccomp machinery rather than this module's good intentions.

**What this is and is not.** ADR-093 is explicit that Tier 3 is "a guardrail
against accidents and prompt-injection mistakes, **not** a security boundary
against hostile code": a user-namespace sandbox still exposes the full host
syscall surface. So this backend is deliberately *not* registered as satisfying
`UNTRUSTED_CODE` (Tier 1) or the autonomous floor (Tier 2). It is the honest
bottom of the ladder, and the ladder refuses rather than silently landing here
when a workload needs more.

Every sandbox gets its own root: a private tmpfs `/tmp`, a read-only bind of
the host's runtime directories, no network namespace unless the config asks for
one, `--unshare-all`, `--die-with-parent` and `--new-session`. `--new-session`
matters more than its name suggests -- without a fresh session the sandboxed
process keeps the caller's controlling terminal and can push characters back
into it with `TIOCSTI`, which is an escape from a sandbox that otherwise looks
airtight.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from pathlib import Path
from uuid import uuid4

from maistro.sandbox.detect import BUBBLEWRAP_BINARY
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance

logger = logging.getLogger("maistro.sandbox.bubblewrap")

#: Host paths every sandbox needs read-only to run an interpreter at all.
_RO_BINDS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc/alternatives")

#: Exit code convention shared with the other backends: 124 is `timeout(1)`'s.
TIMEOUT_EXIT_CODE = 124


class BubblewrapUnavailableError(RuntimeError):
    """Raised when the backend is constructed on a host without `bwrap`."""


class BubblewrapSandboxBackend:
    """Tier-3 OS-sandbox backend built on `bwrap`."""

    tier = "bubblewrap"

    def __init__(self, *, root: Path | None = None, bwrap: str | None = None) -> None:
        resolved = bwrap or shutil.which(BUBBLEWRAP_BINARY)
        if resolved is None:
            raise BubblewrapUnavailableError(
                f"{BUBBLEWRAP_BINARY!r} is not on PATH; refusing to construct a sandbox backend "
                "that cannot isolate. Install bubblewrap or let the selector fail closed."
            )
        self._bwrap = resolved
        self._root = root
        self._instances: dict[str, tuple[SandboxConfig, Path]] = {}

    # --- lifecycle ---------------------------------------------------------

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        sid = f"bwrap-{uuid4().hex[:8]}"
        workdir = await asyncio.to_thread(self._make_workdir, sid)
        self._instances[sid] = (config, workdir)
        logger.info("sandbox_spawned id=%s tier=%s network=%s", sid, self.tier, config.network)
        return SandboxInstance(
            id=sid,
            backend="bubblewrap",
            isolation_tier=self.tier,
            metadata={"workdir": str(workdir)},
        )

    def _make_workdir(self, sid: str) -> Path:
        import tempfile

        parent = self._root
        if parent is None:
            return Path(tempfile.mkdtemp(prefix=f"{sid}-"))
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=f"{sid}-", dir=str(parent)))

    async def destroy(self, instance: SandboxInstance) -> None:
        """Idempotent, as the protocol requires."""
        entry = self._instances.pop(instance.id, None)
        if entry is None:
            return
        _config, workdir = entry
        await asyncio.to_thread(shutil.rmtree, workdir, True)
        logger.info("sandbox_destroyed id=%s", instance.id)

    # --- execution ---------------------------------------------------------

    def build_argv(self, config: SandboxConfig, workdir: Path, command: list[str]) -> list[str]:
        """The exact `bwrap` invocation, as a value.

        Separated from `exec` so the flags are assertable without a host that
        has bubblewrap installed. The security of this backend is almost
        entirely *which flags are passed*, so those flags are the thing worth
        testing, and a test that can only run where `bwrap` exists would leave
        them unverified on every other machine.
        """
        argv = [
            self._bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        for path in _RO_BINDS:
            if Path(path).exists():
                argv += ["--ro-bind", path, path]
        # The sandbox's writable surface is exactly its own workdir, mounted at
        # a fixed path so a command does not need to know the host layout.
        argv += ["--bind", str(workdir), "/work", "--chdir", "/work"]
        for extra in config.writable_paths:
            argv += ["--bind", extra, extra]
        if config.network:
            # `--unshare-all` already removed the network namespace; sharing it
            # back is the only way to grant egress, and it is only reachable
            # through a policy whose `network_allowed` is true.
            argv += ["--share-net"]
        argv += ["--clearenv"]
        for key, value in sorted(config.env.items()):
            argv += ["--setenv", key, value]
        return [*argv, "--", *command]

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        config, workdir = self._require(instance)
        argv = self.build_argv(config, workdir, command)
        start = time.monotonic()

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except TimeoutError:
            # `--die-with-parent` makes the kill reach the whole sandbox rather
            # than only the `bwrap` process, so a timeout cannot leave the
            # sandboxed work running unsupervised.
            process.kill()
            await process.wait()
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

    # --- files -------------------------------------------------------------

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        target = self._resolve(instance, path)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        target = self._resolve(instance, path)
        return await asyncio.to_thread(target.read_bytes)

    def _resolve(self, instance: SandboxInstance, path: str) -> Path:
        """Map a sandbox path onto the host, refusing to escape the workdir.

        The file operations run on the *host* side — they are how a caller gets
        work in and results out — so a sandbox path of `../../etc/passwd` would
        otherwise be a host write with no sandbox involved at all.
        """
        _config, workdir = self._require(instance)
        relative = Path(path)
        if relative.is_absolute():
            try:
                relative = relative.relative_to("/work")
            except ValueError:
                raise ValueError(
                    f"path {path!r} is outside the sandbox; writable root is '/work'"
                ) from None
        resolved = (workdir / relative).resolve()
        if not resolved.is_relative_to(workdir.resolve()):
            raise ValueError(f"path {path!r} escapes the sandbox workdir")
        return resolved

    def _require(self, instance: SandboxInstance) -> tuple[SandboxConfig, Path]:
        entry = self._instances.get(instance.id)
        if entry is None:
            raise KeyError(f"no live sandbox {instance.id!r}; it was destroyed or never spawned")
        return entry


__all__ = ["TIMEOUT_EXIT_CODE", "BubblewrapSandboxBackend", "BubblewrapUnavailableError"]
