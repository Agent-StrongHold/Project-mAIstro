"""Sandbox protocol — the contract all backends implement."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

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
    cpu_cores: float = 1.0
    timeout_s: int = 120
    network: bool = False
    writable_paths: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    min_isolation: IsolationTier = "container"


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
