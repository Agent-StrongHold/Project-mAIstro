"""Governed ceilings on concurrently active root Runs (#1182).

The ceiling is enforced inside `RunStore.create_run` rather than at any one
transport, because every producer -- HTTP, WebSocket, the scheduler, the
Workspace Agent, chat -- admits a Run through that call, and a counter kept
anywhere above it would be one each transport could disagree with.

Only *new root admission* is bounded. A child Run is capacity its root already
holds, and a parked Run resuming after a human answer or a timer was admitted
once already: the owner decision on #1182 lets it go over the ceiling rather
than strand work somebody has answered. WAITING and PAUSED hold no slot, so a
backlog of pending approvals cannot starve new work.
"""

from __future__ import annotations

from dataclasses import dataclass

from maistro.config.settings import get_settings
from maistro.runs.model import RunStatus
from maistro.security.resource_policy import (
    BASELINE_MAX_ACTIVE_ROOT_RUNS_PER_PRINCIPAL,
    BASELINE_MAX_ACTIVE_ROOT_RUNS_PER_WORKSPACE,
)

__all__ = [
    "ACTIVE_ROOT_STATUSES",
    "ACTIVE_ROOT_STATUS_VALUES",
    "RunConcurrencyExceeded",
    "RunConcurrencyLimits",
]

ACTIVE_ROOT_STATUSES = frozenset({RunStatus.CREATED, RunStatus.QUEUED, RunStatus.RUNNING})
ACTIVE_ROOT_STATUS_VALUES = tuple(sorted(status.value for status in ACTIVE_ROOT_STATUSES))


class RunConcurrencyExceeded(Exception):
    """A new root Run was refused because a governed ceiling is full.

    Backpressure, not an integrity failure: nothing about the request is
    wrong, and the same request is admissible once a slot frees. Deliberately
    not a `RunIntegrityError`, which callers read as a permanent refusal.
    """

    def __init__(self, scope: str, limit: int, active: int) -> None:
        super().__init__(
            f"active root Run ceiling reached for {scope}: {active} active, limit {limit}"
        )
        self.scope = scope
        self.limit = limit
        self.active = active


@dataclass(frozen=True)
class RunConcurrencyLimits:
    per_principal: int = BASELINE_MAX_ACTIVE_ROOT_RUNS_PER_PRINCIPAL
    per_workspace: int = BASELINE_MAX_ACTIVE_ROOT_RUNS_PER_WORKSPACE

    @classmethod
    def configured(cls) -> RunConcurrencyLimits:
        """The ceilings the operator configured, which `/health` reports.

        What a store falls back to when it is not handed limits, so a store
        built outside the spine wiring holds the same ceilings as one built
        inside it.
        """
        settings = get_settings()
        return cls(
            per_principal=settings.max_active_root_runs_per_principal,
            per_workspace=settings.max_active_root_runs_per_workspace,
        )

    def check(self, *, workspace_active: int, principal_active: int | None) -> None:
        """Refuse one more root Run when either ceiling is already full.

        `principal_active` is None for a Run with no actor principal, which
        is bounded by its Workspace alone.
        """
        if principal_active is not None and principal_active >= self.per_principal:
            raise RunConcurrencyExceeded("principal", self.per_principal, principal_active)
        if workspace_active >= self.per_workspace:
            raise RunConcurrencyExceeded("workspace", self.per_workspace, workspace_active)
