"""Docker-backed development implementation of `MicroVmSandbox`.

Wraps the existing `maistro.tools.sandbox.docker.SandboxContainer` (ADR-054:
one sandbox per task, ephemeral FS, durable state in Postgres/git) so RSI
cycles are runnable today without a real microVM host. `create_microvm_sandbox`
is the single seam to replace once a microVM backend is selected — Firecracker
gives the fastest boot/snapshot story, E2B wraps Firecracker as a hosted SDK
with no host KVM setup, gVisor trades some isolation strength for deployability
on existing container infra. None of the rest of `maistro_rsi` depends on which
one wins; it only depends on `MicroVmSandbox`.
"""

from __future__ import annotations

import os
import uuid

import structlog

from maistro.config.settings import SandboxSettings
from maistro.tools.sandbox.docker import SandboxContainer, create_sandbox
from maistro_rsi.protocols import MicroVmSandbox
from maistro_rsi.sandbox.local import LocalSandbox

logger = structlog.get_logger()

#: Env var that selects the RSI sandbox backend. ``"docker"`` (default) boots a
#: nested container; ``"local"`` runs directly on the local FS — set by the sbx
#: agent kit, because sbx has *already* provided an isolated microVM.
SANDBOX_BACKEND_ENV = "MAISTRO_RSI_SANDBOX"

#: Set by ``sbx/maistro-rsi/spec.yaml`` to attest the containment it creates, and
#: available to an operator whose substrate this module cannot recognise.
#:
#: Auto-detection alone is not sufficient here, and that is not a theoretical
#: worry: isolated environments exist that expose none of the markers in
#: :func:`isolation_evidence` — no ``/.dockerenv``, a bare ``/proc/1/cgroup``,
#: unreadable DMI. Refusing those would brick the RSI loop in exactly the
#: environment it is designed for, so the layer that *provides* the microVM
#: declares it, and detection stays a convenience for plain container hosts.
#:
#: Deliberately verbose: asserting containment by hand should have to be meant,
#: and should be greppable in a shell history or CI config afterwards.
SANDBOX_ATTEST_ENV = "MAISTRO_RSI_SANDBOX_ATTEST_ISOLATED"
_ATTEST_VALUE = "i-am-inside-a-disposable-vm"


# Filesystem markers consulted by isolation_evidence(). Module-level so tests
# can point them at fixture paths and drive both verdicts deterministically.
_CONTAINER_MARKER_FILES: tuple[str, ...] = (
    "/.dockerenv",  # Docker/OCI runtimes create this at the container root
    "/run/.containerenv",  # podman
)
_CGROUP_PATH = "/proc/1/cgroup"
_CGROUP_RUNTIME_TOKENS: tuple[str, ...] = ("docker", "containerd", "kubepods", "libpod", "lxc")


def isolation_evidence() -> list[str]:
    """Return positive, checkable evidence that this process is inside a
    disposable *container*.

    ``LocalSandbox`` executes the coding agent directly against the mounted
    filesystem with no containment of its own — the *sbx* microVM is the
    boundary. Selecting it therefore encodes a claim about the environment, and
    until now that claim was a single environment variable that anything in the
    process tree could set. This function looks for the boundary instead of
    taking its word for it.

    Only container evidence counts. Generic VM-ness (a KVM/QEMU/VirtualBox
    string in DMI) deliberately does NOT: an ordinary persistent development VM
    reports those too, and its filesystem is exactly the thing an auto-approved
    agent must not be handed — "inside a VM" is not "disposable". A genuinely
    bare microVM with no container markers (the sbx case) is attested by the
    layer that creates it (``SANDBOX_ATTEST_ENV`` in ``sbx/maistro-rsi/
    spec.yaml``) rather than guessed at here.
    """
    found: list[str] = []

    for marker in _CONTAINER_MARKER_FILES:
        if os.path.exists(marker):
            found.append(marker)

    # PID 1's cgroup path names the supervising runtime on cgroup v1 and on v2
    # under most container runtimes.
    try:
        with open(_CGROUP_PATH, encoding="utf-8", errors="replace") as fh:
            cgroup = fh.read()
    except OSError:
        cgroup = ""
    for token in _CGROUP_RUNTIME_TOKENS:
        if token in cgroup:
            found.append(f"{_CGROUP_PATH}:{token}")
            break

    return found


class DockerMicroVmSandbox:
    """Adapts `SandboxContainer` to the `MicroVmSandbox` protocol.

    Containers can't pause/resume the way microVMs can, so `snapshot` records
    a label for bookkeeping but `restore` raises — callers should rebuild the
    sandbox from the labeled git ref instead. A real microVM backend can offer
    genuine pause/resume here without changing this class's interface.
    """

    def __init__(self, container: SandboxContainer) -> None:
        self._container = container
        self._snapshots: dict[str, str] = {}

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        return await self._container.exec(command, timeout=timeout)

    async def read_file(self, path: str) -> str:
        return await self._container.read_file(path)

    async def write_file(self, path: str, content: str) -> None:
        await self._container.write_file(path, content)

    async def snapshot(self, label: str) -> str:
        snapshot_id = f"{label}-{uuid.uuid4().hex[:8]}"
        self._snapshots[snapshot_id] = label
        await logger.ainfo("rsi_sandbox_snapshot_recorded", snapshot_id=snapshot_id, label=label)
        return snapshot_id

    async def restore(self, snapshot_id: str) -> None:
        if snapshot_id not in self._snapshots:
            raise KeyError(f"Unknown snapshot: {snapshot_id}")
        raise NotImplementedError(
            "Docker backend cannot restore microVM-style snapshots; "
            "rebuild the sandbox from the labeled git ref instead."
        )

    async def destroy(self) -> None:
        await self._container.destroy()

    async def __aenter__(self) -> DockerMicroVmSandbox:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.destroy()


async def create_microvm_sandbox(
    workspace: str,
    settings: SandboxSettings | None = None,
    env: dict[str, str] | None = None,
) -> DockerMicroVmSandbox:
    """Create a sandbox satisfying the `MicroVmSandbox` protocol.

    Currently Docker-backed; swap the body of this function for a Firecracker/
    E2B/gVisor-backed implementation when that decision is made.
    """
    container = await create_sandbox(workspace, settings=settings, env=env)
    return DockerMicroVmSandbox(container)


async def create_rsi_sandbox(
    workspace: str,
    settings: SandboxSettings | None = None,
    env: dict[str, str] | None = None,
    backend: str | None = None,
) -> MicroVmSandbox:
    """Create the RSI sandbox for ``workspace`` using the selected backend.

    ``backend`` (or ``$MAISTRO_RSI_SANDBOX``) picks the isolation strategy:

    - ``"local"`` → :class:`LocalSandbox`, for when the cycle already runs inside
      an isolated microVM (a Docker Sandboxes / ``sbx`` agent) — no nested
      Docker-in-Docker.
    - ``"docker"`` (default) → :class:`DockerMicroVmSandbox`, which boots its own
      container for standalone / dev runs.
    """
    resolved = (backend or os.environ.get(SANDBOX_BACKEND_ENV, "docker")).strip().lower()
    if resolved == "local":
        # `local` means "the environment is the containment". Require the
        # environment to show it. MAISTRO_RSI_SANDBOX=local on a bare host
        # would otherwise hand an auto-approved coding agent the real
        # filesystem — the exact configuration LocalSandbox exists to *avoid*
        # nesting inside, never to run without.
        evidence = isolation_evidence()
        if not evidence:
            if os.environ.get(SANDBOX_ATTEST_ENV) == _ATTEST_VALUE:
                logger.warning(
                    "rsi_sandbox_isolation_attested_not_verified",
                    attest_env=SANDBOX_ATTEST_ENV,
                )
            else:
                raise RuntimeError(
                    "MAISTRO_RSI_SANDBOX=local requires a verified isolated "
                    "environment, and no container/VM evidence was found "
                    "(checked /.dockerenv, /run/.containerenv, /proc/1/cgroup, "
                    "DMI platform). LocalSandbox runs the coding agent directly "
                    "on this filesystem. If this host truly is a disposable "
                    f"VM this module cannot recognise, set {SANDBOX_ATTEST_ENV}="
                    f"{_ATTEST_VALUE} to override explicitly."
                )
        else:
            logger.info("rsi_sandbox_isolation_verified", evidence=evidence)
        return LocalSandbox(workspace)
    return await create_microvm_sandbox(workspace, settings=settings, env=env)
