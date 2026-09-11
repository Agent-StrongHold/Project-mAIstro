"""Deletion authority for Run retention, named in one place (#1175).

A leaf module, for the same reason `runs.sources` is: three parts of the
system — the `RunStore` protocol, the two durable backends' candidate SQL,
and the sweeper that rides on admission — must agree on what a purge is
allowed to touch, and none of them can import the others without a cycle.
Retention is invoked from Workspace-scoped admission and composition, so the
scope has to be a value the caller *names*, not a predicate the store
*remembers*: an omitted scope must be impossible, and store-wide must be an
explicit, attributed act rather than the default.

## The dependent-reference inventory (#1175 acceptance 3)

A Run row is the index into more than its own spine. One purge, one database
transaction, and a policy for every reference — decided once, in one table, so
the next dependent table added to the schema edits this list instead of
silently joining the population "references nobody accounted for":

================================================  ============================  ====================================================
Reference                                         Declared constraint           Policy under purge
================================================  ============================  ====================================================
canonical_attempts.node_run_id                    FK ON DELETE RESTRICT (012)   Delete — spine children go first, in the purge transaction.
canonical_node_runs.run_id                        FK ON DELETE RESTRICT (012)   Delete — same transaction.
canonical_runs.parent_run_id                      FK (012)                      Never selected — a Run with live descendants is not a candidate.
canonical_runs.parent_node_run_id                 FK (012)                      Never selected — same rule, through a NodeRun.
graph_continuations.run_id                        PK only, **no FK** (021)      Delete in the purge transaction. Traversal state is execution identity, not audit (ADR-062); a continuation whose Run is gone is not history, it is a recovery trap — the recovery tick reads due run_ids from this table. `CanonicalDurableRunStore.get` already refuses the dangling case outright ("purged without reconciling Graph continuation state"), and its `reconcile_persistence` remains the crash backstop.
canonical_event_log.run_id (+ node/attempt ids)   none — logical (030)          **Preserve.** The Event log is the append-only audit trail; deleting or rewriting events to keep ids resolvable would destroy the provenance retention exists to bound. The purge counts how many events now attribute to purged Runs so the residue is observable, not silent.
schedule occurrence claim                         unique expression index on the Run's own provenance (015)   Dies with the Run row — deleting the Run *is* releasing the claim, the same policy `InMemoryRunStore._forget_run` has always applied. Counted per purge.
schedules.last_run_id                             none — logical (016)   **Release the pointer** — set it back to absent in the purge transaction, and count the release. The fire cursor is a pointer to the newest Run, not a history of them (`scheduling.admission` says so in as many words), so a purged Run must not leave the cursor naming an id nothing resolves; the fire's *history* (`last_fired_at`, `runs_so_far`, and the Run-provenance occurrence the Event log carries) is untouched. Released in the purge transaction on every backend that can see the `schedules` table.
canonical_runs.archive_key                        column (017)                  Not reachable — purgable Runs carry a deadline, archived Runs carry none; the populations are disjoint by predicate (ADR-082226-f436 decision 10).
tasks.run_id, session_turns.run_id                none — logical (004/028)      Preserve. Historical attribution owned by other modules: a task receipt or a session turn says "this happened", and it stays true after the execution identity is reclaimed. Same class as Events.
learnings/outcomes/design_outputs/episodic_memories .run_id, .node_run_id, .attempt_id   none — logical (026/028/031)   Preserve. Producer provenance (#709, #64): "this execution produced this learning/outcome/design output/memory" is attribution history exactly like a task receipt — it names an execution that did happen. The purge never touches these tables; the reference resolving to a purged Run is the same residue an Event reference is, and the same policy — observable, not destroyed — applies.
================================================  ============================  ====================================================

The line the table draws: **execution state** (spine children, continuations,
occurrence claims) is reclaimed with the Run; **attribution history** (events,
task receipts, session turns) outlives it and is counted or left inspectable
rather than silently destroyed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.model import Run

__all__ = [
    "GlobalRetentionGrant",
    "GlobalRetentionScope",
    "RetentionAuthorizationError",
    "RetentionScope",
    "WorkspaceRetentionScope",
    "require_retention_scope",
    "run_in_purge_scope",
]


@dataclass(frozen=True)
class WorkspaceRetentionScope:
    """Deletion authority over the Runs of exactly one Workspace (#1175).

    Retention is invoked from Workspace-scoped admission and composition, so
    this is the scope every routine sweeper carries: its purge can only ever
    select Runs filed in this Workspace, whatever else expires elsewhere in
    the same store while it runs.
    """

    workspace_id: str

    def __post_init__(self) -> None:
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")


class RetentionAuthorizationError(PermissionError):
    """A global retention capability is absent, forged, revoked, or expired."""


class GlobalRetentionGrant:
    """Opaque global-retention capability issued by the privilege authority.

    A principal name is attribution, not authorization.  The grant therefore
    carries a validator owned by :class:`PrivilegeGuard`; key rotation or
    guard reinitialization invalidates it before a purge can select a row.
    ``_issue`` is intentionally the only constructor used by the privilege
    subsystem, so callers cannot turn an arbitrary string into authority.
    """

    __slots__ = ("_authorized_by", "_validator")

    def __init__(
        self,
        authorized_by: str,
        validator: Callable[[], bool],
        *,
        _issued: object,
    ) -> None:
        if _issued is not _GRANT_ISSUANCE_TOKEN:
            raise TypeError("global retention grants must be issued by PrivilegeGuard")
        if not authorized_by.strip():
            raise ValueError("authorized_by must name the admin principal")
        self._authorized_by = authorized_by
        self._validator = validator

    @classmethod
    def _issue(cls, authorized_by: str, validator: Callable[[], bool]) -> GlobalRetentionGrant:
        return cls(authorized_by, validator, _issued=_GRANT_ISSUANCE_TOKEN)

    @property
    def authorized_by(self) -> str:
        return self._authorized_by

    def validate(self) -> None:
        if not self._validator():
            raise RetentionAuthorizationError(
                "global retention grant is no longer valid; obtain a fresh admin grant"
            )


_GRANT_ISSUANCE_TOKEN = object()


class GlobalRetentionScope:
    """Explicitly authorized store-wide retention (#1175).

    Store-wide deletion is supported only with a capability issued by the
    existing privilege authority.  In particular, ``authorized_by`` is a
    read-only audit attribute of that capability, not a caller-supplied bypass.
    """

    __slots__ = ("grant",)

    def __init__(self, grant: GlobalRetentionGrant) -> None:
        if not isinstance(grant, GlobalRetentionGrant):
            raise TypeError("GlobalRetentionScope requires a PrivilegeGuard-issued grant")
        self.grant = grant

    @property
    def authorized_by(self) -> str:
        return self.grant.authorized_by


RetentionScope = WorkspaceRetentionScope | GlobalRetentionScope


def require_retention_scope(scope: object) -> RetentionScope:
    """Validate both the runtime scope type and global deletion authority."""
    if not isinstance(scope, (WorkspaceRetentionScope, GlobalRetentionScope)):
        raise TypeError(
            "purge_expired_runs requires WorkspaceRetentionScope or an authorized "
            "GlobalRetentionScope"
        )
    if isinstance(scope, GlobalRetentionScope):
        scope.grant.validate()
    return scope


def run_in_purge_scope(run: Run, scope: RetentionScope) -> bool:
    """Whether ``run`` is inside ``scope``'s deletion authority.

    A module function rather than a method on the scope so the durable backends
    can translate it into their candidate SQL's WHERE clause while this stays
    the one statement of what the predicate means.
    """
    require_retention_scope(scope)
    if isinstance(scope, WorkspaceRetentionScope):
        return run.workspace_id == scope.workspace_id
    return True
