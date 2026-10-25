"""Sandbox protocol — the contract all backends implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from maistro.sandbox.fence import SandboxFence
from maistro.sandbox.network import DENY_ALL, EgressGrant

# Type alias for clarity
IsolationTier = str  # "vm" | "gvisor" | "container" | "bubblewrap" | "fake"


@runtime_checkable
class SandboxProtocol(Protocol):
    """A sandbox can spawn an isolated environment, execute code, and tear down."""

    async def spawn(self, *, config: SandboxConfig) -> SandboxInstance:
        """Create an isolated sandbox. Returns a handle for exec/file ops."""
        ...

    async def exec(
        self, instance: SandboxInstance, command: list[str], *, timeout_s: int = 120
    ) -> ExecResult:
        """Execute a command inside the sandbox."""
        ...

    async def write_file(self, instance: SandboxInstance, path: str, content: bytes) -> None:
        """Write a file into the sandbox filesystem."""
        ...

    async def read_file(self, instance: SandboxInstance, path: str) -> bytes:
        """Read a file from the sandbox filesystem."""
        ...

    async def destroy(self, instance: SandboxInstance) -> None:
        """Tear down the sandbox. Must be idempotent."""
        ...


@dataclass(frozen=True)
class SandboxConfig:
    """What the sandbox needs to provide."""

    memory_mb: int = 256
    #: A *rate*, enforced as a CPU-seconds budget over `timeout_s` (#80): a
    #: quarter core for two minutes is thirty CPU-seconds, and a busy loop that
    #: exceeds it is killed by the kernel rather than left to burn a core.
    cpu_cores: float = 1.0
    timeout_s: int = 120
    #: Largest single file the sandbox may write. The workdir is on the host's
    #: filesystem, so without this a workload fills the host's disk (#80).
    max_file_mb: int = 512
    #: Best-effort process ceiling. Set as `RLIMIT_NPROC`, which the kernel
    #: does not enforce for a privileged parent -- see `resource_limits`.
    max_processes: int = 128
    network: bool = False
    writable_paths: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    min_isolation: IsolationTier = "container"
    #: The egress grant this sandbox runs under. Default-deny (#77), and
    #: frozen with the rest of the config so nothing can widen it after the
    #: sandbox is running.
    egress: EgressGrant = DENY_ALL
    #: The Attempt fence this sandbox executes under (#79). Injected into
    #: the sandbox environment so anything it publishes can prove it is
    #: still the current execution. `None` for work with nothing to commit.
    fence: SandboxFence | None = None


@dataclass
class SandboxInstance:
    """Handle to a live sandbox."""

    id: str
    backend: str
    isolation_tier: IsolationTier
    pid: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecResult:
    """Result of a command execution in a sandbox."""

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
