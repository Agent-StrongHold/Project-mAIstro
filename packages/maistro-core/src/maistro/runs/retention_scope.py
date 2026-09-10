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
canonical_runs.archive_key                        column (017)                  Not reachable — purgable Runs carry a deadline, archived Runs carry none; the populations are disjoint by predicate (ADR-082226-f436 decision 10).
tasks.run_id, session_turns.run_id                none — logical (004/028)      Preserve. Historical attribution owned by other modules: a task receipt or a session turn says "this happened", and it stays true after the execution identity is reclaimed. Same class as Events.
================================================  ============================  ====================================================

The line the table draws: **execution state** (spine children, continuations,
occurrence claims) is reclaimed with the Run; **attribution history** (events,
task receipts, session turns) outlives it and is counted or left inspectable
rather than silently destroyed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.model import Run

__all__ = [
    "GlobalRetentionScope",
    "RetentionScope",
    "WorkspaceRetentionScope",
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


@dataclass(frozen=True)
class GlobalRetentionScope:
    """Explicitly authorized store-wide retention (#1175).

    Store-wide deletion exists — an operator decommissioning a deployment is
    its legitimate user — but it must never be what falls out of *omitting* a
    predicate, which is exactly what the pre-#1175 signature rewarded. The
    authorization is part of the value: whoever's name is in ``authorized_by``
    is who asked every Run in the store to be deletable, and it travels in the
    purge outcome for the same audit reason the Runs' own provenance does.
    """

    authorized_by: str

    def __post_init__(self) -> None:
        if not self.authorized_by.strip():
            raise ValueError("authorized_by must name the principal that authorized a global purge")


type RetentionScope = WorkspaceRetentionScope | GlobalRetentionScope


def run_in_purge_scope(run: Run, scope: RetentionScope) -> bool:
    """Whether ``run`` is inside ``scope``'s deletion authority.

    A module function rather than a method on the scope so the durable backends
    can translate it into their candidate SQL's WHERE clause while this stays
    the one statement of what the predicate means.
    """
    if isinstance(scope, WorkspaceRetentionScope):
        return run.workspace_id == scope.workspace_id
    return True
