"""Persistent, forkable evaluation workspaces (#107).

Bookkeeping substrate over the M2 sandbox: environment digests for matched
comparisons, digest-addressed snapshots, fork/pause/resume/restore records,
and a digest-keyed warm pool. No execution lifecycle lives here -- workspaces
ride the canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model, and
real environments are driven through `maistro.sandbox.SandboxProtocol`.
"""

from maistro.eval_workspace.digest import (
    canonical_json,
    content_digest,
    environment_digest,
    sha256_hex,
)
from maistro.eval_workspace.model import (
    EMPTY_FIXTURES,
    TERMINAL_WORKSPACE_STATUSES,
    EvalWorkspace,
    EvalWorkspaceStatus,
    FixtureEntry,
    FixtureManifest,
    WorkspaceSnapshot,
    start_states_match,
)
from maistro.eval_workspace.pool import WorkspacePool
from maistro.eval_workspace.service import (
    EnvironmentMismatchError,
    EvalWorkspaceService,
    OwnershipError,
    WorkspaceStateError,
)
from maistro.eval_workspace.store import (
    DuplicateWorkspaceError,
    EvalWorkspaceNotFound,
    EvalWorkspaceStore,
    InMemoryEvalWorkspaceStore,
)

__all__ = [
    "EMPTY_FIXTURES",
    "TERMINAL_WORKSPACE_STATUSES",
    "DuplicateWorkspaceError",
    "EnvironmentMismatchError",
    "EvalWorkspace",
    "EvalWorkspaceNotFound",
    "EvalWorkspaceService",
    "EvalWorkspaceStatus",
    "EvalWorkspaceStore",
    "FixtureEntry",
    "FixtureManifest",
    "InMemoryEvalWorkspaceStore",
    "OwnershipError",
    "WorkspacePool",
    "WorkspaceSnapshot",
    "WorkspaceStateError",
    "canonical_json",
    "content_digest",
    "environment_digest",
    "sha256_hex",
    "start_states_match",
]
