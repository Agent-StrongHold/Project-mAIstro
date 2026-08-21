"""Harness adapter protocol — spawn external agent harnesses as DAG nodes.

A "harness" is any agent execution environment that can receive a task,
run it asynchronously, and report back a result: Claude Code sessions,
remote Conductor instances, LangChain agents, generic HTTP endpoints, etc.

`HarnessAdapter` is the DI boundary. Concrete adapters (ClaudeCodeAdapter,
ConductorHttpAdapter, ...) live in hive-conductor or downstream products
and are wired into `AgentSpawnHarnessNode` at startup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class HarnessKind(StrEnum):
    CLAUDE_CODE = "claude_code"
    CONDUCTOR = "conductor"
    GENERIC_HTTP = "generic_http"
    IN_PROCESS = "in_process"


@dataclass(frozen=True)
class HarnessRequest:
    harness_type: str
    task: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 3600
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessHandle:
    handle_id: str
    harness_type: str
    dispatched_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class HarnessResult:
    handle_id: str
    success: bool
    output: str
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class HarnessAdapter(Protocol):
    """Protocol every harness backend implements.

    `dispatch` fires the task and returns a handle immediately (the DAG node
    then pauses). `poll` checks for a result on resume. `cancel` is called if
    the run is cancelled before the harness completes.
    """

    async def dispatch(self, request: HarnessRequest) -> HarnessHandle: ...

    async def poll(self, handle: HarnessHandle) -> HarnessResult | None:
        """Return the result if complete, None if still running."""
        ...

    async def cancel(self, handle: HarnessHandle) -> None: ...
