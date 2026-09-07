"""Local passthrough ``MicroVmSandbox`` — for when the RSI cycle already runs
*inside* an isolated microVM.

When maistro-rsi is launched as a Docker Sandboxes (``sbx``) agent, ``sbx`` has
already booted an isolated microVM (own kernel, ephemeral FS, deny-by-default
egress) and runs the RSI entrypoint inside it. Creating a *nested*
``DockerMicroVmSandbox`` there would be redundant Docker-in-Docker: the microVM
is the isolation boundary. ``LocalSandbox`` satisfies the same ``MicroVmSandbox``
protocol by running the cycle's commands directly against the (already-isolated)
local workspace.

Everything downstream of the sandbox is unchanged — the RSI quarantine gate
(Warden + adversarial review) still governs what may leave the sandbox as a PR,
so "run directly on the local FS" is safe precisely because that FS is the
disposable microVM ``sbx`` handed us.

Credential boundary (#78): candidate commands get exactly
:func:`maistro.sandbox.credential_boundary.candidate_env` — the fixed minimal
base plus explicit constructor grants — and never the harness's environment.
This matters *inside* the microVM too: the RSI process itself holds the
gateway key (``LITELLM_MASTER_KEY``/``LITELLM_PROXY_KEY``, see
``maistro_rsi.gateway``), and before the boundary a candidate's ``bash -c``
inherited it whole. Secrets a candidate legitimately needs cross only as
Provider-mediated grants (``grant_from_credential`` off a CredentialRouter
acquisition), and the sbx posture needs none of those — provider endpoints are
proxied host-side by the sbx kit, keys never enter the sandbox.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import uuid
from collections.abc import Mapping
from pathlib import Path

import structlog

from maistro.sandbox.credential_boundary import candidate_env

logger = structlog.get_logger()

_TIMEOUT_EXIT_CODE = 124
#: Cap on how long we wait to reap a killed process after a timeout, so `exec`
#: never blocks unboundedly if the host is slow to reap (SIGKILL is already sent).
_REAP_GRACE_SECONDS = 1.0


class LocalSandbox:
    """Run RSI commands on the local filesystem (already inside an sbx microVM)."""

    def __init__(self, workspace: str, *, grants: Mapping[str, str] | None = None) -> None:
        self._workspace = workspace
        self._grants: Mapping[str, str] | None = grants
        self._snapshots: dict[str, str] = {}
        Path(workspace).mkdir(parents=True, exist_ok=True)
        self._root = Path(workspace).resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve ``path`` inside the workspace, mirroring the Docker
        backend's ``_safe_path`` posture: a model- or patch-supplied path such
        as ``../.gitconfig`` (or an absolute path outside the checkout) must
        never read or write beyond the sandbox workspace."""
        candidate = Path(path)
        resolved = (candidate if candidate.is_absolute() else self._root / candidate).resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise ValueError(f"path escapes sandbox workspace: {path}")
        return resolved

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        # argv into ``bash -c`` (not shell=True) — bash to match the Docker
        # backend's shell contract (`source`, `[[ ]]`, process substitution),
        # so the same RSI test command behaves identically under both backends.
        # Runs inside the isolated sbx microVM, which is the trust boundary —
        # the RSI quarantine gate governs what may leave it. Its own session/
        # process group, so a timeout kills the whole tree, not just the shell.
        # The environment is the credential boundary's (#78): rebuilt from the
        # minimal base + explicit grants on every exec, so ambient harness
        # credentials are never inherited and a candidate's own `export` in
        # one exec cannot widen the next one.
        proc = await asyncio.create_subprocess_exec(  # nosec B603
            "bash",
            "-c",
            command,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
            env=candidate_env(self._grants),
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            # Kill the entire process group — test runners and agents spawn
            # children (servers, `cmd & wait`) that would otherwise outlive the
            # shell and keep mutating the workspace for the rest of the run.
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.kill()
            # SIGKILL is delivered; bound the reap so a slow host can't wedge us.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=_REAP_GRACE_SECONDS)
            return _TIMEOUT_EXIT_CODE, f"timeout after {timeout}s"
        return proc.returncode or 0, stdout.decode(errors="replace")

    async def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    async def write_file(self, path: str, content: str) -> None:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    async def snapshot(self, label: str) -> str:
        snapshot_id = f"{label}-{uuid.uuid4().hex[:8]}"
        self._snapshots[snapshot_id] = label
        await logger.ainfo("rsi_local_snapshot_recorded", snapshot_id=snapshot_id, label=label)
        return snapshot_id

    async def restore(self, snapshot_id: str) -> None:
        if snapshot_id not in self._snapshots:
            raise KeyError(f"Unknown snapshot: {snapshot_id}")
        raise NotImplementedError(
            "LocalSandbox cannot restore snapshots; rebuild from the labeled git ref instead."
        )

    async def destroy(self) -> None:
        # sbx owns the microVM lifecycle; there is nothing to tear down locally.
        return None

    async def __aenter__(self) -> LocalSandbox:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.destroy()
