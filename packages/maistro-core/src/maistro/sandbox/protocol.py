"""Sandbox protocol — the contract all backends implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.sandbox.network import DENY_ALL, EgressGrant

# Retained-output policy (#1197) is OWNED by the stdlib-only
# `maistro.tools.sandbox._capture` — the executors (docker/microVM, the RSI
# promotion path) import their bounds from there without initializing this
# package — and re-exported here as the policy's public home. One definition,
# two spellings; drift is impossible by construction.
from maistro.tools.sandbox._capture import (
    DEFAULT_MAX_OUTPUT_BYTES as DEFAULT_MAX_OUTPUT_BYTES,
)
from maistro.tools.sandbox._capture import (
    MAX_OUTPUT_BYTES_CEILING as MAX_OUTPUT_BYTES_CEILING,
)
from maistro.tools.sandbox._capture import (
    clamped_output_limit as clamped_output_limit,
)

if TYPE_CHECKING:
    # Annotation-only: a runtime import here would close the cycle
    # protocol -> fence -> runs -> graph -> capabilities -> opencode ->
    # tools/sandbox.microvm -> capture -> protocol.
    from maistro.sandbox.fence import SandboxFence

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
    #: Host-selected bound (#1197) on stdout/stderr bytes the backend retains.
    #: Output past the limit is read and discarded (never buffered), so an
    #: unbounded emitter cannot grow host memory nor wedge the executor on a
    #: full pipe. Clamped to `MAX_OUTPUT_BYTES_CEILING` at the backend; a
    #: workload cannot raise it.
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES


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
    """Result of a command execution in a sandbox.

    Truncation semantics (#1197): every backend retains at most
    `SandboxConfig.max_output_bytes` per stream. Output beyond the limit is
    read and *discarded* — not buffered — so the workload runs to its natural
    completion (or its timeout) without blocking on a full pipe. `stdout` /
    `stderr` therefore may be partial; `*_truncated` says so, and `*_bytes`
    are the retained byte counts (the raw bytes captured, which after a
    `errors="replace"` decode can differ from `len(stdout)`). Callers and
    audit must treat a result with `*_truncated` as incomplete evidence.
    """

    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    #: Retained stdout/stderr bytes (post-clamp raw byte counts, #1197).
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    #: True when the stream exceeded the retained-output limit and the rest
    #: was drained and discarded.
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def truncation_summary(self) -> str | None:
        """Operator-facing truncation summary, or None when evidence is complete.

        The contract line above — a truncated result is incomplete evidence —
        needs a reader to be true: backends log this at the point of
        truncation, so an audit trail always carries the fact that retained
        output is partial and how much was kept.
        """
        parts: list[str] = []
        if self.stdout_truncated:
            parts.append(f"stdout truncated ({self.stdout_bytes} bytes retained)")
        if self.stderr_truncated:
            parts.append(f"stderr truncated ({self.stderr_bytes} bytes retained)")
        return "; ".join(parts) if parts else None
