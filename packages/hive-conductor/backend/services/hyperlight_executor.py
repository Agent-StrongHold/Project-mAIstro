"""Sandboxed code executor — defense-in-depth isolation with fail-closed semantics.

Fallback chain (highest isolation → lowest), per ADR-093 Decision 5:
1. Hyperlight  — hardware-enforced microVM (1-2ms cold start, hypervisor cage)   [tier 1: VM]
2. Firecracker — lightweight VM (kernel-level isolation, ~125ms cold start)      [tier 1: VM]
3. gVisor      — user-space kernel; syscalls terminate in the Sentry, not the
                 host kernel (no io_uring exposure)                              [tier 2: userspace kernel]
4. bubblewrap  — user-namespace sandbox (no root, no host FS, seccomp); still
                 exposes the full host syscall surface                           [tier 3: shared kernel]
5. Hardened container — OCI container, no-new-privs, read-only rootfs, seccomp   [tier 3: shared kernel]
6. FAIL CLOSED — refuse to execute if no sandbox is available

Execution-mode floors (ADR-093 Decision 6): the strongest available backend is
always used, but `autonomous` (unattended / "overnight" / full-auto) execution
requires tier 2 or better — on a host whose best backend is shared-kernel,
full-auto refuses to run while `interactive` (human-supervised) execution
proceeds with a warning.

The bare subprocess fallback is REMOVED. Untrusted code never runs without isolation.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from typing import Any

logger = logging.getLogger("hive.sandbox")

# ─── Isolation tiers and execution-mode floors (ADR-093) ─────────────────────

TIER_VM = 1  # hardware virtualization boundary
TIER_USERSPACE_KERNEL = 2  # gVisor Sentry between guest and host kernel
TIER_SHARED_KERNEL = 3  # namespaces + seccomp only — guardrail, not a boundary

BACKEND_TIERS: dict[str, int] = {
    "hyperlight": TIER_VM,
    "firecracker": TIER_VM,
    "gvisor": TIER_USERSPACE_KERNEL,
    "bubblewrap": TIER_SHARED_KERNEL,
    "hardened-container": TIER_SHARED_KERNEL,
}

# Weakest tier each mode may execute under. Unknown modes get the autonomous
# (stricter) floor — default deny.
MODE_FLOORS: dict[str, int] = {
    "interactive": TIER_SHARED_KERNEL,
    "autonomous": TIER_USERSPACE_KERNEL,
}

# ─── Backend availability detection ──────────────────────────────────────────


def _has_hyperlight() -> bool:
    try:
        r = subprocess.run(
            [sys.executable, "-c", "import hyperlight"], capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def _has_firecracker() -> bool:
    return shutil.which("firecracker") is not None and os.path.exists("/dev/kvm")


def _has_bubblewrap() -> bool:
    return shutil.which("bwrap") is not None


def _has_gvisor() -> bool:
    return shutil.which("runsc") is not None


def _has_hardened_container() -> bool:
    return shutil.which("docker") is not None or shutil.which("podman") is not None


# ─── Config encoding (fix #2 — no f-string templating of config values) ──────


def _encode_config(*, allow_network: bool, memory_mb: int, timeout_s: int) -> str:
    """Encode all config as base64 JSON. Never template values into source."""
    return base64.b64encode(
        json.dumps(
            {
                "allow_network": bool(allow_network),
                "memory_mb": int(memory_mb),
                "timeout_s": int(timeout_s),
            }
        ).encode()
    ).decode("ascii")


# ─── Executor ─────────────────────────────────────────────────────────────────


class SandboxExecutor:
    """Execute code with the strongest available isolation, or refuse."""

    def __init__(self):
        self._backend: str | None = None
        self._detect()

    def _detect(self):
        """Probe once at startup. Order = strongest isolation first (ADR-093)."""
        if _has_hyperlight():
            self._backend = "hyperlight"
        elif _has_firecracker():
            self._backend = "firecracker"
        elif _has_gvisor():
            self._backend = "gvisor"
        elif _has_bubblewrap():
            self._backend = "bubblewrap"
        elif _has_hardened_container():
            self._backend = "hardened-container"
        else:
            self._backend = None
        if self._backend:
            logger.info(
                "sandbox_backend=%s (isolation tier %d) — code execution enabled",
                self._backend,
                BACKEND_TIERS[self._backend],
            )
            if not self.allows_mode("autonomous"):
                logger.warning(
                    "sandbox_backend=%s is shared-kernel — autonomous/overnight "
                    "execution is BLOCKED (interactive only). Install gVisor (runsc) "
                    "or a microVM backend to enable full-auto.",
                    self._backend,
                )
        else:
            logger.critical(
                "╔══════════════════════════════════════════════════════════════╗\n"
                "║  NO SANDBOX BACKEND AVAILABLE — CODE EXECUTION WILL REFUSE  ║\n"
                "║  Install one of: bubblewrap, gVisor, Firecracker, Docker    ║\n"
                "║  Any DAG node requiring sandbox tier will fail closed.       ║\n"
                "╚══════════════════════════════════════════════════════════════╝"
            )

    @property
    def available(self) -> bool:
        return self._backend is not None

    @property
    def backend(self) -> str | None:
        return self._backend

    @property
    def tier(self) -> int | None:
        """Isolation tier of the selected backend (1=VM … 3=shared kernel)."""
        return BACKEND_TIERS[self._backend] if self._backend else None

    def allows_mode(self, mode: str) -> bool:
        """Whether the selected backend satisfies the isolation floor for `mode`.

        Lets schedulers/UI pre-check (and surface) that full-auto is blocked
        instead of discovering it node-by-node at run time.
        """
        if self._backend is None:
            return False
        floor = MODE_FLOORS.get(mode, MODE_FLOORS["autonomous"])
        return BACKEND_TIERS[self._backend] <= floor

    async def execute_node(
        self,
        code: str,
        env: dict[str, str] | None = None,
        timeout_s: int = 120,
        allow_network: bool = False,
        memory_mb: int = 256,
        mode: str = "autonomous",
    ) -> dict[str, Any]:
        if self._backend is None:
            return {
                "output": "",
                "error": "REFUSED: no sandbox backend available. Install bubblewrap, gVisor, or Firecracker.",
                "success": False,
                "isolation": "fail-closed",
                "duration_ms": 0,
            }
        if not self.allows_mode(mode):
            return {
                "output": "",
                "error": (
                    f"REFUSED: {mode!r} execution requires gVisor or microVM isolation; "
                    f"strongest available backend is '{self._backend}' (shared kernel). "
                    "Run interactively, or install gVisor (runsc) / Firecracker / Kata "
                    "to enable full-auto."
                ),
                "success": False,
                "isolation": "fail-closed",
                "duration_ms": 0,
            }

        start = time.monotonic()
        encoded_code = base64.b64encode(code.encode("utf-8")).decode("ascii")
        config_b64 = _encode_config(
            allow_network=allow_network, memory_mb=memory_mb, timeout_s=timeout_s
        )

        dispatch = {
            "hyperlight": self._run_hyperlight,
            "firecracker": self._run_firecracker,
            "bubblewrap": self._run_bubblewrap,
            "gvisor": self._run_gvisor,
            "hardened-container": self._run_hardened_container,
        }
        runner = dispatch[self._backend]
        result = await runner(encoded_code, config_b64, env, timeout_s)
        result["duration_ms"] = int((time.monotonic() - start) * 1000)
        result["isolation"] = self._backend
        return result

    # ─── Backend implementations ──────────────────────────────────────────

    async def _run_hyperlight(
        self, code_b64: str, config_b64: str, env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        wrapper = f"""
import base64, json, sys
cfg = json.loads(base64.b64decode("{config_b64}"))
code = base64.b64decode("{code_b64}").decode("utf-8")
import hyperlight
from hyperlight import Sandbox, SandboxConfig
sc = SandboxConfig(memory_mb=cfg["memory_mb"], timeout_ms=cfg["timeout_s"]*1000, allow_network=cfg["allow_network"])
with Sandbox(sc) as sb:
    r = sb.execute_python(code)
    print(r.stdout)
    if r.stderr: print(r.stderr, file=sys.stderr)
    exit(0 if r.returncode == 0 else 1)
"""
        return await self._subprocess(wrapper, env, timeout_s)

    async def _run_firecracker(
        self, code_b64: str, config_b64: str, env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        # Firecracker requires a rootfs + kernel — delegate to jailer
        # For now, use the firectl pattern
        return await self._subprocess_via_cmd(
            ["firecracker-containerd", "--code-b64", code_b64, "--config-b64", config_b64],
            env,
            timeout_s,
        )

    async def _run_bubblewrap(
        self, code_b64: str, config_b64: str, env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        wrapper = f'import base64,json,sys;cfg=json.loads(base64.b64decode("{config_b64}"));exec(base64.b64decode("{code_b64}").decode())'
        cmd = [
            "bwrap",
            "--ro-bind",
            "/usr",
            "/usr",
            "--ro-bind",
            "/lib",
            "/lib",
            "--ro-bind",
            "/lib64",
            "/lib64",
            "--symlink",
            "usr/bin",
            "/bin",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # nosec B108 — bwrap flag: mounts a fresh tmpfs INSIDE the sandbox, not host /tmp
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            sys.executable,
            "-c",
            wrapper,
        ]
        return await self._subprocess_via_cmd(cmd, env, timeout_s)

    async def _run_gvisor(
        self, code_b64: str, config_b64: str, env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        wrapper = f'import base64,json;cfg=json.loads(base64.b64decode("{config_b64}"));exec(base64.b64decode("{code_b64}").decode())'
        runtime = "podman" if shutil.which("podman") else "docker"
        cmd = [
            runtime,
            "run",
            "--rm",
            "--runtime=runsc",
            "--read-only",
            "--network=none",
            f"--memory={256}m",
            f"--timeout={timeout_s}",
            "python:3.12-slim",
            "python",
            "-c",
            wrapper,
        ]
        return await self._subprocess_via_cmd(cmd, env, timeout_s)

    async def _run_hardened_container(
        self, code_b64: str, config_b64: str, env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        wrapper = f'import base64,json;cfg=json.loads(base64.b64decode("{config_b64}"));exec(base64.b64decode("{code_b64}").decode())'
        runtime = "podman" if shutil.which("podman") else "docker"
        cmd = [
            runtime,
            "run",
            "--rm",
            "--read-only",
            "--network=none",
            "--security-opt=no-new-privileges",
            "--cap-drop=ALL",
            "--memory=256m",
            "--pids-limit=64",
            "python:3.12-slim",
            "python",
            "-c",
            wrapper,
        ]
        return await self._subprocess_via_cmd(cmd, env, timeout_s)

    # ─── Helpers ──────────────────────────────────────────────────────────

    async def _subprocess(self, code: str, env: dict | None, timeout_s: int) -> dict[str, Any]:
        run_env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
        }
        if env:
            run_env.update(env)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._sync_run, [sys.executable, "-c", code], run_env, timeout_s
        )

    async def _subprocess_via_cmd(
        self, cmd: list[str], env: dict | None, timeout_s: int
    ) -> dict[str, Any]:
        run_env = dict(os.environ)
        if env:
            run_env.update(env)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_run, cmd, run_env, timeout_s)

    def _sync_run(self, cmd: list[str], env: dict, timeout_s: int) -> dict[str, Any]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=env)
            return {
                "output": r.stdout,
                "error": r.stderr[:500] if r.stderr else "",
                "success": r.returncode == 0,
            }
        except subprocess.TimeoutExpired:
            return {"output": "", "error": "timeout", "success": False}
        except Exception as e:
            return {"output": "", "error": str(e)[:200], "success": False}


# ─── Singleton + public API ───────────────────────────────────────────────────

_executor = SandboxExecutor()


def get_executor() -> SandboxExecutor:
    return _executor


async def execute_in_sandbox(
    code: str,
    env: dict[str, str] | None = None,
    allow_network: bool = False,
    mode: str = "autonomous",
) -> dict[str, Any]:
    """Execute code in the strongest available sandbox, or refuse.

    `mode` is "interactive" (human-supervised) or "autonomous" (unattended);
    autonomous requires gVisor-or-better isolation (ADR-093 Decision 6).
    """
    return await _executor.execute_node(code, env=env, allow_network=allow_network, mode=mode)


# Backward compat alias
execute_in_microvm = execute_in_sandbox
