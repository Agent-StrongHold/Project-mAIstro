"""Persistence surface for evaluation workspaces.

One store, one authority. Workspace state transitions go through the store,
so the pool and the service never disagree about who owns a workspace or
what state it is in -- the failure mode a second authority (a pool with its
own map, a cache with its own lifecycle) exists to cause.

The in-memory implementation is the dev/test backend and is behavioural, in
line with ADR-083026-e602: a store that only the durable backend implements
lets every in-memory test pass while only the durable ones do the work.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from maistro.eval_workspace.model import EvalWorkspace, EvalWorkspaceStatus, WorkspaceSnapshot


class EvalWorkspaceNotFound(KeyError):
    """Raised when a workspace or snapshot id does not resolve."""

    def __init__(self, kind: str, workspace_env_id: str) -> None:
        super().__init__(f"{kind} not found: {workspace_env_id}")
        self.kind = kind
        self.workspace_env_id = workspace_env_id


class DuplicateWorkspaceError(RuntimeError):
    """Raised when a store is asked to hold two records under one id."""


@runtime_checkable
class EvalWorkspaceStore(Protocol):
    """Reads and writes workspace and snapshot records."""

    def add_workspace(self, workspace: EvalWorkspace) -> None: ...

    def save_workspace(self, workspace: EvalWorkspace) -> None: ...

    def get_workspace(self, workspace_env_id: str) -> EvalWorkspace: ...

    def find_by_status(self, status: EvalWorkspaceStatus | str) -> list[EvalWorkspace]: ...

    def find_available_by_digest(self, environment_digest: str) -> list[EvalWorkspace]: ...

    def find_by_owner(self, attempt_id: str) -> list[EvalWorkspace]: ...

    def children_of(self, parent_workspace_env_id: str) -> list[EvalWorkspace]: ...

    def add_snapshot(self, snapshot: WorkspaceSnapshot) -> None: ...

    def get_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot: ...

    def snapshots_of(self, workspace_env_id: str) -> list[WorkspaceSnapshot]: ...

    def produced_by_run(
        self, run_id: str
    ) -> tuple[list[EvalWorkspace], list[WorkspaceSnapshot]]: ...


class InMemoryEvalWorkspaceStore:
    """In-memory `EvalWorkspaceStore`; process-local, dev and test backend."""

    def __init__(self) -> None:
        self._workspaces: dict[str, EvalWorkspace] = {}
        self._snapshots: dict[str, WorkspaceSnapshot] = {}
        # Insertion order, kept across saves: the pool's FIFO claim is
        # "oldest warm workspace", and equal timestamps must not make that
        # order random.
        self._insertion: dict[str, int] = {}
        self._counter = 0

    # -- workspaces ---------------------------------------------------------

    def add_workspace(self, workspace: EvalWorkspace) -> None:
        if workspace.workspace_env_id in self._workspaces:
            raise DuplicateWorkspaceError(f"workspace already exists: {workspace.workspace_env_id}")
        self._counter += 1
        self._insertion[workspace.workspace_env_id] = self._counter
        self._workspaces[workspace.workspace_env_id] = workspace

    def save_workspace(self, workspace: EvalWorkspace) -> None:
        """The write door: invariants are re-checked here.

        Status and its companion field (owner, archived_at) move together in
        one save, so per-assignment checks would fire on the intermediate
        state no caller ever observes. The store re-runs the model validator
        on every save -- the same discipline as the canonical run store's
        fence on `transition_attempt`.
        """
        if workspace.workspace_env_id not in self._workspaces:
            raise EvalWorkspaceNotFound("workspace", workspace.workspace_env_id)
        # The write door re-runs the construction validator by name: pydantic
        # wraps a @model_validator in a descriptor proxy whose *static* type
        # is not callable, but the runtime call is the supported in-place
        # re-validation, and tests pin that it rejects mutated violations.
        workspace.validate_invariants()  # type: ignore[operator]
        self._workspaces[workspace.workspace_env_id] = workspace

    def get_workspace(self, workspace_env_id: str) -> EvalWorkspace:
        try:
            return self._workspaces[workspace_env_id]
        except KeyError:
            raise EvalWorkspaceNotFound("workspace", workspace_env_id) from None

    def find_by_status(self, status: EvalWorkspaceStatus | str) -> list[EvalWorkspace]:
        wanted = status if isinstance(status, EvalWorkspaceStatus) else EvalWorkspaceStatus(status)
        return [ws for ws in self._workspaces.values() if ws.status is wanted]

    def find_available_by_digest(self, environment_digest: str) -> list[EvalWorkspace]:
        """AVAILABLE workspaces of exactly one environment, oldest first.

        A pool claim serves from this list head, so warm-pool behaviour is
        FIFO and the digest match is enforced by the query itself: a
        workspace of any other environment is not a miss-shaped result, it is
        simply not in the answer.
        """
        ready = [
            ws
            for ws in self._workspaces.values()
            if ws.status is EvalWorkspaceStatus.AVAILABLE
            and ws.environment_digest == environment_digest
        ]
        return sorted(
            ready,
            key=lambda ws: (ws.updated_at, self._insertion[ws.workspace_env_id]),
        )

    def find_by_owner(self, attempt_id: str) -> list[EvalWorkspace]:
        return [ws for ws in self._workspaces.values() if ws.owner_attempt_id == attempt_id]

    def children_of(self, parent_workspace_env_id: str) -> list[EvalWorkspace]:
        return [
            ws
            for ws in self._workspaces.values()
            if ws.parent_workspace_env_id == parent_workspace_env_id
        ]

    # -- snapshots ----------------------------------------------------------

    def add_snapshot(self, snapshot: WorkspaceSnapshot) -> None:
        if snapshot.snapshot_id in self._snapshots:
            raise DuplicateWorkspaceError(f"snapshot already exists: {snapshot.snapshot_id}")
        # A snapshot must name a workspace the store knows: a snapshot of an
        # unrecorded workspace is provenance pointing nowhere.
        if snapshot.workspace_env_id not in self._workspaces:
            raise EvalWorkspaceNotFound("workspace", snapshot.workspace_env_id)
        self._snapshots[snapshot.snapshot_id] = snapshot

    def get_snapshot(self, snapshot_id: str) -> WorkspaceSnapshot:
        try:
            return self._snapshots[snapshot_id]
        except KeyError:
            raise EvalWorkspaceNotFound("snapshot", snapshot_id) from None

    def snapshots_of(self, workspace_env_id: str) -> list[WorkspaceSnapshot]:
        return [
            snap for snap in self._snapshots.values() if snap.workspace_env_id == workspace_env_id
        ]

    def produced_by_run(self, run_id: str) -> tuple[list[EvalWorkspace], list[WorkspaceSnapshot]]:
        """What one Run produced, per ADR-083026-e602.

        A blank `run_id` returns nothing rather than every unattributed
        record: "which workspaces did no execution produce" is a legitimate
        question and a different one, and answering it from the same call
        means a caller with an unresolved id silently gets the wrong set.
        """
        if not run_id.strip():
            return ([], [])
        workspaces = [ws for ws in self._workspaces.values() if ws.produced_run_id == run_id]
        snapshots = [snap for snap in self._snapshots.values() if snap.produced_run_id == run_id]
        return (workspaces, snapshots)
