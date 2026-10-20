"""vm-tier canonical backend over the SPEC-205 ``VMMLauncher`` seam.

The launcher is *caller wiring*: production points it at a real VMM
(Firecracker / Cloud Hypervisor / QEMU), tests inject a fake. That is why
``wiring.build_selector`` never registers this backend — a launcher cannot be
probed as a host capability, and a tier claim must be evidenced. Callers that
wire a launcher register it on a :class:`~maistro.sandbox.selector.SandboxSelector`
themselves, so the selector stays the authority: tier admission, egress
resolution, and budgets all come from ``select()``/``build_config()`` exactly
as they do for host-evidenced backends (#76).

Honesty about egress is the load-bearing property here. No real launcher ships
in this repository, so nothing enforces a destination filter, and no networked
profile is wired either: any grant that would hand the guest an interface is
refused. The deny-only posture is enforced in ``spawn`` by overriding the
substrate config's ``network`` field — under canonical authority the egress
grant, not the substrate config, decides — so a ``MicroVMConfig(network=...)``
value cannot widen what the policy denied.

Each ``exec`` boots a fresh microVM (SPEC-205's model), so ``destroy`` has no
persistent resource to reclaim; it is the idempotent no-op the protocol
requires.
"""

from __future__ import annotations

import dataclasses
import shlex
import time
from pathlib import Path
from uuid import uuid4

from maistro.sandbox.network import resolve_grant
from maistro.sandbox.protocol import ExecResult, SandboxConfig, SandboxInstance
from maistro.tools.sandbox.microvm import (
    LauncherFn,
    MicroVMConfig,
    MicroVMSandbox,
    VMMLauncher,
)
from maistro.tools.sandbox.workspace import validate_workspace_path


class LauncherVMUnavailableError(RuntimeError):
    """Raised when the launcher-backed VM substrate cannot honour a config."""


class LauncherVMSandboxBackend:
    """A vm-tier backend whose substrate is an injected VMM launcher seam."""

    tier = "vm"
    #: No shipped launcher can filter destinations, and none provides a
    #: networked profile at all: deny-only (see the module docstring).
    supports_scoped_egress = False

    def __init__(
        self,
        launcher: VMMLauncher | LauncherFn,
        *,
        config: MicroVMConfig | None = None,
        workspace: str = ".",
        trusted_env: dict[str, str] | None = None,
    ) -> None:
        self._launcher = launcher
        self._substrate = config or MicroVMConfig()
        # Validate only, never create: materializing the workspace is the
        # launcher's business (same contract MicroVMSandbox applies).
        self._workspace = validate_workspace_path(workspace)
        self._trusted_env = dict(trusted_env or {})
        self._instances: dict[str, MicroVMSandbox] = {}

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        sid = f"launcher-vm-{uuid4().hex[:12]}"
        grant = resolve_grant(
            config.egress,
            backend_name=type(self).__name__,
            supports_scoped_egress=self.supports_scoped_egress,
            sandbox_id=sid,
        )
        if grant.grants_network:
            # Fail closed rather than pretend: `resolve_grant` already refuses
            # SCOPED for a non-filtering backend; HOST is refused here because
            # no shipped launcher provides a networked guest profile at all.
            raise LauncherVMUnavailableError(
                "the launcher-vm substrate ships deny-only: no networked microVM "
                "profile exists to honour this grant; refusing rather than "
                "approximating it"
            )
        effective = dataclasses.replace(self._substrate, network="none")
        self._instances[sid] = MicroVMSandbox(
            self._launcher,
            config=effective,
            workspace=str(self._workspace),
            trusted_env=self._trusted_env,
        )
        return SandboxInstance(
            id=sid,
            backend="launcher-vm",
            isolation_tier=self.tier,
            metadata={"workspace": str(self._workspace)},
        )

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        sandbox = self._require(instance)
        start = time.monotonic()
        # A one-element command list is a shell command line — the shape the
        # harness ``SandboxExec`` seam speaks — and reaches the launcher
        # verbatim. Longer lists are argv and are joined shell-safely.
        line = command[0] if len(command) == 1 else shlex.join(command)
        code, output = await sandbox.exec(line, timeout=timeout_s)
        return ExecResult(
            exit_code=code,
            stdout=output,
            stderr="",
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        self._require(instance)
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        self._require(instance)
        return self._resolve(path).read_bytes()

    async def destroy(self, instance: SandboxInstance) -> None:
        # One VM per exec (SPEC-205): there is no persistent resource to tear
        # down, and the method must stay idempotent.
        self._instances.pop(instance.id, None)

    def _require(self, instance: SandboxInstance) -> MicroVMSandbox:
        sandbox = self._instances.get(instance.id)
        if sandbox is None:
            raise KeyError(f"no live sandbox {instance.id!r}")
        return sandbox

    def _resolve(self, path: str) -> Path:
        """Resolve a sandbox path against the workspace root, refusing escapes."""
        relative = Path(path)
        if relative.is_absolute():
            try:
                relative = relative.relative_to("/workspace")
            except ValueError:
                raise ValueError(f"path {path!r} is outside the sandbox") from None
        target = (self._workspace / relative).resolve()
        if not target.is_relative_to(self._workspace.resolve()):
            raise ValueError(f"path {path!r} escapes the sandbox workspace")
        return target


__all__ = ["LauncherVMSandboxBackend", "LauncherVMUnavailableError"]
