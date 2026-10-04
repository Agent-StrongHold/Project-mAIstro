"""A warm pool of evaluation workspaces, keyed by environment digest.

"Warm pools where justified" (#107) is a *policy* question, not a new
lifecycle: the pool decides which AVAILABLE workspace an Attempt gets, and holds
no state of its own -- every read and write goes through the store, so the
pool and the service can never disagree about who owns what.

The digest key is the whole safety story. A claim names the environment it
needs; the pool answers from workspaces of *exactly* that digest or not at
all. A near-miss environment (same image, different fixtures, wider egress)
is not a warm hit, it is a comparison-invalidating substitution -- so the
claim misses instead, and the caller provisions the environment it actually
asked for.
"""

from __future__ import annotations

import logging

from maistro.eval_workspace.model import EvalWorkspace
from maistro.eval_workspace.service import EvalWorkspaceService
from maistro.eval_workspace.store import EvalWorkspaceStore

logger = logging.getLogger("maistro.eval_workspace.pool")


class WorkspacePool:
    """Claim/release policy over AVAILABLE workspaces of one exact environment."""

    def __init__(self, store: EvalWorkspaceStore, service: EvalWorkspaceService) -> None:
        self._store = store
        self._service = service

    def claim(
        self,
        environment_digest: str,
        *,
        attempt_id: str,
        node_run_id: str | None = None,
        run_id: str | None = None,
    ) -> EvalWorkspace | None:
        """Claim the oldest AVAILABLE workspace of exactly this digest, or None.

        None is a miss, not an error: the caller provisions a fresh
        environment of the requested digest. Never raises on a digest with no
        warm workspaces -- that is the normal cold-start path.
        """
        candidates = self._store.find_available_by_digest(environment_digest)
        if not candidates:
            return None
        chosen = candidates[0]
        return self._service.claim_for_attempt(
            chosen.workspace_env_id,
            attempt_id=attempt_id,
            node_run_id=node_run_id,
            run_id=run_id,
        )

    def release(self, workspace_env_id: str, *, attempt_id: str, keep_warm: bool = True) -> None:
        """Release after use: keep it warm (AVAILABLE, claimable) or park it."""
        self._service.release_from_attempt(
            workspace_env_id, attempt_id=attempt_id, keep_warm=keep_warm
        )

    def warm_count(self, environment_digest: str) -> int:
        """How many AVAILABLE workspaces are warm for one environment."""
        return len(self._store.find_available_by_digest(environment_digest))

    def parked(self) -> list[EvalWorkspace]:
        """Workspaces currently parked in PARKED state."""
        return self._store.find_by_status("parked")


__all__ = ["WorkspacePool"]
