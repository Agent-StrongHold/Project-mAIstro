"""Workspace lifecycle operations.

Every mutation of a workspace record lives here so the invariants hold in one
place: transitions re-read the record from the store, validate the move, and
write it back. Nothing here spawns or stops sandboxes -- the environment's
real lifecycle is the caller's, driven through `SandboxProtocol`, and the
canonical execution lifecycle remains `Goal -> Graph -> Run -> NodeRun ->
Attempt`. What this service owns is the *record*: identity, ownership,
lineage, and the digests that make matched comparisons honest.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict

from maistro.eval_workspace.digest import content_digest, environment_digest
from maistro.eval_workspace.model import (
    EMPTY_FIXTURES,
    TERMINAL_WORKSPACE_STATUSES,
    EvalWorkspace,
    EvalWorkspaceStatus,
    FixtureManifest,
    WorkspaceSnapshot,
)
from maistro.eval_workspace.store import EvalWorkspaceStore
from maistro.sandbox.protocol import SandboxConfig

logger = logging.getLogger("maistro.eval_workspace.service")


class WorkspaceStateError(RuntimeError):
    """A transition the workspace's current state does not allow."""


class EnvironmentMismatchError(RuntimeError):
    """A fork/restore across environments that would fake an identical start.

    Comparing two branches only means something if they started identically.
    A fork into a different environment, or a restore of a snapshot taken in
    another environment, would produce a `start_state_digest` that *looks*
    comparable and is not -- so it is refused instead.
    """


class OwnershipError(WorkspaceStateError):
    """An attempt tried to release a workspace it does not own."""


#: Keyword provenance accepted by every producing operation (ADR-083026-e602).
#: A TypedDict, not ``dict[str, str | None]``: ``**``-unpacking a plain
#: mapping offers every constructor parameter a ``str | None``, which pyright
#: (unlike mypy) reads as a possible mismatch on fields the provenance never
#: touches. Optional per-key types keep the call sites honest.
class ProvenanceKwargs(TypedDict, total=False):
    """Optional producing-execution keyword arguments for one record."""

    produced_run_id: str | None
    produced_node_run_id: str | None
    produced_attempt_id: str | None


def _provenance_kwargs(
    run_id: str | None,
    node_run_id: str | None,
    attempt_id: str | None,
) -> ProvenanceKwargs:
    return {
        "produced_run_id": run_id,
        "produced_node_run_id": node_run_id,
        "produced_attempt_id": attempt_id,
    }


class EvalWorkspaceService:
    """All record-level workspace operations; the pool is a thin client."""

    def __init__(self, store: EvalWorkspaceStore) -> None:
        self._store = store

    # -- creation -----------------------------------------------------------

    def provision(
        self,
        *,
        workspace_id: str,
        project_id: str,
        image: str,
        sandbox: SandboxConfig,
        fixtures: FixtureManifest = EMPTY_FIXTURES,
        run_id: str | None = None,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> EvalWorkspace:
        """Register a new workspace in PROVISIONING state.

        The caller brings the backing environment up via `SandboxProtocol`
        and then calls `activate`. Provisioning with a digest computed here
        means the environment's identity is fixed before the environment
        exists, which is exactly the property matched comparisons need.
        """
        fixtures.validate_unique_names()
        workspace = EvalWorkspace(
            workspace_id=workspace_id,
            project_id=project_id,
            environment_digest=environment_digest(
                image=image,
                sandbox=sandbox,
                fixtures_digest=fixtures.digest,
            ),
            **_provenance_kwargs(run_id, node_run_id, attempt_id),
        )
        self._store.add_workspace(workspace)
        logger.info(
            "eval_workspace_provisioned id=%s digest=%s run=%s",
            workspace.workspace_env_id,
            workspace.environment_digest[:12],
            run_id or "-",
        )
        return workspace

    def activate(self, workspace_env_id: str) -> EvalWorkspace:
        """PROVISIONING -> AVAILABLE once the backing environment is up."""
        return self._transition(workspace_env_id, _ACTIVATE)

    # -- claiming (canonical Run/Attempt ownership) --------------------------

    def claim_for_attempt(
        self,
        workspace_env_id: str,
        *,
        attempt_id: str,
        node_run_id: str | None = None,
        run_id: str | None = None,
    ) -> EvalWorkspace:
        """Bind a AVAILABLE workspace to exactly one Attempt."""
        workspace = self._store.get_workspace(workspace_env_id)
        if workspace.status is not EvalWorkspaceStatus.AVAILABLE:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} is {workspace.status.value}, not AVAILABLE; "
                "only an AVAILABLE workspace can be held"
            )
        if workspace.archived_at is not None:  # pragma: no cover - status implies this
            raise WorkspaceStateError("retired workspaces cannot be held")
        workspace.owner_attempt_id = attempt_id
        workspace.status = EvalWorkspaceStatus.IN_USE
        workspace.updated_at = datetime.now(UTC)
        self._store.save_workspace(workspace)
        logger.info(
            "eval_workspace_held id=%s attempt=%s node_run=%s run=%s",
            workspace_env_id,
            attempt_id,
            node_run_id or "-",
            run_id or "-",
        )
        return workspace

    def release_from_attempt(
        self,
        workspace_env_id: str,
        *,
        attempt_id: str,
        keep_warm: bool = True,
    ) -> EvalWorkspace:
        """Release a held workspace: back to AVAILABLE (warm) or PARKED.

        `keep_warm` is the warm-pool decision the releasing Attempt makes:
        the environment stays up and claimable when its contents are
        reusable, and parks when they are not. Only the owning Attempt may
        release; anything else is an ownership violation, not a state error.
        """
        workspace = self._store.get_workspace(workspace_env_id)
        if workspace.status is not EvalWorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} is {workspace.status.value}, not IN_USE"
            )
        if workspace.owner_attempt_id != attempt_id:
            raise OwnershipError(
                f"attempt {attempt_id} does not own workspace {workspace_env_id} "
                f"(owner={workspace.owner_attempt_id})"
            )
        workspace.owner_attempt_id = None
        workspace.status = (
            EvalWorkspaceStatus.AVAILABLE if keep_warm else EvalWorkspaceStatus.PARKED
        )
        workspace.updated_at = datetime.now(UTC)
        self._store.save_workspace(workspace)
        return workspace

    # -- pause / resume / restore --------------------------------------------

    def pause(self, workspace_env_id: str) -> EvalWorkspace:
        """AVAILABLE -> PARKED. State is preserved by the caller's substrate."""
        return self._transition(workspace_env_id, _PAUSE)

    def resume(self, workspace_env_id: str) -> EvalWorkspace:
        """PARKED -> AVAILABLE."""
        return self._transition(workspace_env_id, _RESUME)

    def restore(
        self,
        workspace_env_id: str,
        snapshot_id: str,
        *,
        run_id: str | None = None,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> EvalWorkspace:
        """Point a workspace's start state at a recorded snapshot.

        Restoring is only defined within one environment: a snapshot's
        `environment_digest` must equal the workspace's. The caller applies
        the captured content through `SandboxProtocol`; the record change is
        what makes later comparisons check against the restored state.
        """
        workspace = self._store.get_workspace(workspace_env_id)
        if workspace.status in TERMINAL_WORKSPACE_STATUSES:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} is retired and cannot be restored"
            )
        snapshot = self._store.get_snapshot(snapshot_id)
        if snapshot.environment_digest != workspace.environment_digest:
            raise EnvironmentMismatchError(
                f"snapshot {snapshot_id} belongs to environment "
                f"{snapshot.environment_digest[:12]}, workspace {workspace_env_id} runs "
                f"{workspace.environment_digest[:12]}; restoring it would fake an "
                "identical start state"
            )
        workspace.start_state_digest = snapshot.content_digest
        workspace.updated_at = datetime.now(UTC)
        self._store.save_workspace(workspace)
        logger.info(
            "eval_workspace_restored id=%s snapshot=%s run=%s node_run=%s attempt=%s",
            workspace_env_id,
            snapshot_id,
            run_id or "-",
            node_run_id or "-",
            attempt_id or "-",
        )
        return workspace

    # -- snapshots ------------------------------------------------------------

    def snapshot(
        self,
        workspace_env_id: str,
        *,
        state: bytes,
        label: str | None = None,
        run_id: str | None = None,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> WorkspaceSnapshot:
        """Record a digest-addressed capture of the workspace's state.

        `state` is the captured content (whatever the caller read from the
        environment through `SandboxProtocol`). The content digest is
        computed here from the bytes, never accepted from the caller: a
        self-declared digest would let a broken capture claim reproducibility
        it does not have. `label` is uninterpreted bookkeeping.
        """
        del label  # accepted for caller readability; not part of the digest
        workspace = self._store.get_workspace(workspace_env_id)
        if workspace.status in TERMINAL_WORKSPACE_STATUSES:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} is retired and cannot be snapshotted"
            )
        snapshot = WorkspaceSnapshot(
            workspace_env_id=workspace_env_id,
            environment_digest=workspace.environment_digest,
            content_digest=content_digest(state),
            **_provenance_kwargs(run_id, node_run_id, attempt_id),
        )
        self._store.add_snapshot(snapshot)
        return snapshot

    # -- fork -----------------------------------------------------------------

    def fork_from_workspace(
        self,
        workspace_env_id: str,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None = None,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> EvalWorkspace:
        """Fork at the workspace's latest snapshot.

        A fork without a recorded start state cannot promise an identical
        start, which is the one thing forks exist for -- so a workspace with
        no snapshots cannot be forked. The child inherits the environment and
        starts AVAILABLE: it is a clone of a live environment, not a fresh one.
        """
        workspace = self._store.get_workspace(workspace_env_id)
        snapshots = self._store.snapshots_of(workspace_env_id)
        if not snapshots:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} has no snapshots; a fork needs a recorded "
                "start state, not just a live environment"
            )
        fork_point = max(snapshots, key=lambda s: s.created_at)
        return self._record_fork(
            parent=workspace,
            fork_point=fork_point,
            workspace_id=workspace_id,
            project_id=project_id,
            **_provenance_kwargs(run_id, node_run_id, attempt_id),
        )

    def fork_from_snapshot(
        self,
        snapshot_id: str,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None = None,
        node_run_id: str | None = None,
        attempt_id: str | None = None,
    ) -> EvalWorkspace:
        """Fork from an explicit snapshot (the fork point need not be latest)."""
        fork_point = self._store.get_snapshot(snapshot_id)
        parent = self._store.get_workspace(fork_point.workspace_env_id)
        return self._record_fork(
            parent=parent,
            fork_point=fork_point,
            workspace_id=workspace_id,
            project_id=project_id,
            **_provenance_kwargs(run_id, node_run_id, attempt_id),
        )

    def _record_fork(
        self,
        *,
        parent: EvalWorkspace,
        fork_point: WorkspaceSnapshot,
        workspace_id: str,
        project_id: str,
        produced_run_id: str | None,
        produced_node_run_id: str | None,
        produced_attempt_id: str | None,
    ) -> EvalWorkspace:
        if parent.status is EvalWorkspaceStatus.RETIRED:
            raise WorkspaceStateError(
                f"workspace {parent.workspace_env_id} is retired and cannot be forked"
            )
        # The fork point must belong to the environment being forked. A
        # snapshot could only disagree with its own workspace if the
        # environment digest were editable, which it is not -- this guard
        # exists so that assumption fails loudly if it ever stops holding.
        if fork_point.environment_digest != parent.environment_digest:
            raise EnvironmentMismatchError(
                f"snapshot {fork_point.snapshot_id} does not belong to environment of "
                f"workspace {parent.workspace_env_id}"
            )
        child = EvalWorkspace(
            workspace_id=workspace_id,
            project_id=project_id,
            environment_digest=parent.environment_digest,
            status=EvalWorkspaceStatus.AVAILABLE,
            parent_workspace_env_id=parent.workspace_env_id,
            forked_from_snapshot_id=fork_point.snapshot_id,
            start_state_digest=fork_point.content_digest,
            **_provenance_kwargs(produced_run_id, produced_node_run_id, produced_attempt_id),
        )
        self._store.add_workspace(child)
        logger.info(
            "eval_workspace_forked child=%s parent=%s fork_point=%s run=%s",
            child.workspace_env_id,
            parent.workspace_env_id,
            fork_point.snapshot_id,
            produced_run_id or "-",
        )
        return child

    # -- archive ---------------------------------------------------------------

    def archive(self, workspace_env_id: str) -> EvalWorkspace:
        """Terminal transition; the record is kept for provenance only."""
        workspace = self._store.get_workspace(workspace_env_id)
        if workspace.status is EvalWorkspaceStatus.RETIRED:
            return workspace
        if workspace.status is EvalWorkspaceStatus.IN_USE:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id} is held by "
                f"{workspace.owner_attempt_id}; release it before retiring"
            )
        workspace.owner_attempt_id = None
        workspace.status = EvalWorkspaceStatus.RETIRED
        workspace.archived_at = datetime.now(UTC)
        workspace.updated_at = workspace.archived_at
        self._store.save_workspace(workspace)
        return workspace

    # -- reads ------------------------------------------------------------------

    def get(self, workspace_env_id: str) -> EvalWorkspace:
        return self._store.get_workspace(workspace_env_id)

    def produced_by_run(self, run_id: str) -> tuple[list[EvalWorkspace], list[WorkspaceSnapshot]]:
        return self._store.produced_by_run(run_id)

    def children_of(self, parent_workspace_env_id: str) -> list[EvalWorkspace]:
        return self._store.children_of(parent_workspace_env_id)

    # -- transition table ---------------------------------------------------------

    def _transition(self, workspace_env_id: str, target: EvalWorkspaceStatus) -> EvalWorkspace:
        workspace = self._store.get_workspace(workspace_env_id)
        allowed = _ALLOWED_TRANSITIONS.get(workspace.status, ())
        if target not in allowed:
            raise WorkspaceStateError(
                f"workspace {workspace_env_id}: {workspace.status.value} -> "
                f"{target.value} is not a permitted transition"
            )
        workspace.status = target
        workspace.updated_at = datetime.now(UTC)
        if target is EvalWorkspaceStatus.AVAILABLE:
            # resume returns a workspace to the claimable pool; it never
            # resurrects an owner (only release clears one, and pause
            # required a clear owner already).
            workspace.owner_attempt_id = None
        self._store.save_workspace(workspace)
        return workspace


#: The transition table, explicit so a new status cannot silently acquire
#: edges nobody voted for. Values are the states each source may move to.
_ALLOWED_TRANSITIONS: dict[EvalWorkspaceStatus, frozenset[EvalWorkspaceStatus]] = {
    EvalWorkspaceStatus.PROVISIONING: frozenset({EvalWorkspaceStatus.AVAILABLE}),
    EvalWorkspaceStatus.AVAILABLE: frozenset(
        {EvalWorkspaceStatus.PARKED, EvalWorkspaceStatus.RETIRED}
    ),
    EvalWorkspaceStatus.IN_USE: frozenset(),
    EvalWorkspaceStatus.PARKED: frozenset({EvalWorkspaceStatus.AVAILABLE}),
    EvalWorkspaceStatus.RETIRED: frozenset(),
}

_ACTIVATE = EvalWorkspaceStatus.AVAILABLE
_PAUSE = EvalWorkspaceStatus.PARKED
_RESUME = EvalWorkspaceStatus.AVAILABLE

__all__ = [
    "EnvironmentMismatchError",
    "EvalWorkspaceService",
    "OwnershipError",
    "WorkspaceStateError",
]
