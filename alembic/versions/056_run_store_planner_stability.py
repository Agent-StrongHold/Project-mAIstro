"""Planner-stable Run-store retention, queue and status indexes (#863).

Three measured shapes stopped being index-served as the spine grew, and all
three share one root cause: PostgreSQL could not prove a partial index's
predicate for the way the query was parameterized.

**The status-literal proof.** A partial index whose predicate names constant
statuses (``ix_canonical_runs_retention``'s ``status IN (...)``, migration 013)
is only usable when the query's own status clause is *also* constant. The
retention and archive sweeps passed the terminal set as ``$n::text[]``, so once
PostgreSQL switched the statement to a generic prepared plan (its steady state
after five executions), the predicate was unprovable and the candidate scan
degraded to a sequential scan of every Run ever kept — exactly when the table
is large enough for the index to matter. The fix is in the queries: the terminal
set is interpolated as literals, the same store-owned interpolation
``_ACTIVE_ROOT_COUNTS_SQL`` already uses for `ix_canonical_runs_live`. The
values come from the model, never from caller input.

**The queue cursor's missing order.** `list_by_status` — the consumer tick's
starvation-cursor read — filtered on `status = $1`, a parameter no partial
status index can prove, and sorted by `payload->>'created_at'`, an expression no
index carried: every tick was a full scan plus a full sort, O(every Run) per
page, fairness paid per tick. The new `ix_canonical_runs_status_created` index
is deliberately *not* partial — an unconditional `(status, created_at, run_id)`
btree answers any single-status read with an index-provided order, the
`(created_at, run_id)` row-comparison cursor rides the same leading columns,
and a generic plan needs no predicate proof at all. The expression is
IMMUTABLE (`jsonb ->> text`, the operator migration 015 already indexes), and
it sorts by the same text the query always sorted by, so page contents are
unchanged — only their cost is.

**The parent anti-join.** The retention sweep refuses a Run that spawned
children through `canonical_runs.parent_node_run_id`, and every NodeRun delete
re-probes the same column for the RESTRICT foreign key. That column had no
index, so each probe walked the whole table. `ix_canonical_runs_parent_node`
closes it — non-partial, so the foreign-key trigger's internal query proves
nothing and scans nothing.

**Status domains.** The status columns were unconstrained text, so a status
value added to the model would silently fall outside every partial-index
predicate above: live Runs would vanish from recovery scans, terminal Runs from
sweeps. CHECK constraints now pin each status column to its model enum
(`ck_canonical_runs_status`, `ck_canonical_node_runs_status`,
`ck_canonical_attempts_status`, `ck_graph_continuations_status`), which makes
the failure loud instead of silent: a new status cannot be written at all until
a migration extends the domain — and that migration is the one place the
partial-index predicates get revised in lockstep.
`tests/migrations/test_status_domain_lockstep.py` holds the DDL to the model so
the pairing cannot rot quietly.

Migration-time cost, stated rather than discovered: each CHECK is validated
over its whole table (one scan, inside this revision's transaction), and the
two new `canonical_runs` indexes each add one btree entry per transition the
way any index on `status` does. In exchange the retention sweep, the archive
sweep and every queue tick stop paying a scan-plus-sort per call — the trade
#863 asks for. No index added here duplicates another: the continuations index
*replaces* `(status, project_id)`, whose filter this store's only status
listing never used as an ordering column, so the write cost is one index on
that table, not two.

Every statement is guarded (`CREATE INDEX IF NOT EXISTS`, `DROP INDEX IF
EXISTS`, and a catalog-checked `ADD CONSTRAINT` — PostgreSQL has no ``IF NOT
EXISTS`` for constraints), matching 046/047/051: stamp-back and re-upgrade is
a live repair path, and the chain's contract is that re-applying a revision
over the schema it already built is adoption, not an error
(`tests/migrations`,
`test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted`). The
conditional add also spares an adopted database the constraint's validation
scan: an existing CHECK is left exactly as it stands rather than dropped and
rebuilt.

Numbered 052 when written; develop's M4-B1 knowledge-stage ladder
(ADR-103) claimed that id on the same `051` parent while this branch was
open, so per this chain's collision convention the revision re-parented
onto that `052_learning_stage_ladder` tip as 053. Develop's M4-B
learning-lifecycle columns (ADR-100126-8c2d) then claimed `053` on that
same parent, and the revision re-parented once more, as 054. Develop's
own learning-applicability migration (M4-B3, #119) then claimed `054` on
the lifecycle tip and #1892's forward admission-generation representation
collided in turn, re-parenting onto it as `055`; this revision follows
them, re-parenting onto that `055_task_admission_generations` as 056.
One linear head, no duplicate revision ids.

Revision ID: 056
Revises: 055
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

#: The model's status domains, spelled out because a migration must keep
#: meaning what it meant on the day it ran — it cannot import the enums.
#: `test_status_domain_lockstep.py` holds these lists to `model.py`, so a
#: status added to the model without a migration fails a test instead of
#: disappearing from every correctness-critical scan.
_RUN_STATUS_VALUES = (
    "created",
    "queued",
    "running",
    "waiting",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)
_ATTEMPT_STATUS_VALUES = (
    "created",
    "running",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
    "yielded",
)

_RUN_STATUS_CHECK = "status IN ({})".format(", ".join(f"'{value}'" for value in _RUN_STATUS_VALUES))  # nosec B608
_ATTEMPT_STATUS_CHECK = "status IN ({})".format(
    ", ".join(f"'{value}'" for value in _ATTEMPT_STATUS_VALUES)
)  # nosec B608

#: The guarded ``ADD CONSTRAINT``, as a format template rather than an
#: f-string. The run-id reference inventory (``scripts/check-durable-table-``
#: ``inventory.py``, replayed by ``test_retention_reference_inventory.py``)
#: reads every string constant in the chain as SQL text and *refuses* an
#: f-string carrying ``ALTER TABLE`` whose interpolations it cannot resolve
#: statically — which a helper's parameters never are. A template is one
#: constant: the scan reads its literal skeleton (and would still see a
#: ``run_id`` column if this DDL ever named one), while the placeholders are
#: filled here from this module's own constants — never from caller input.
_GUARDED_CHECK_CONSTRAINT = (
    "DO $constraint_guard$ BEGIN "
    "IF NOT EXISTS ("
    "SELECT 1 FROM pg_constraint "
    "WHERE conname = '{constraint}' AND conrelid = '{table}'::regclass) THEN "
    "ALTER TABLE {table} ADD CONSTRAINT {constraint} CHECK ({check}); "
    "END IF; END $constraint_guard$"
)


def _add_check_constraint_if_absent(constraint: str, table: str, check: str) -> None:
    """Add a CHECK constraint only when the catalog does not already have it.

    ``ADD CONSTRAINT`` has no ``IF NOT EXISTS`` and a bare add fails a
    re-application with ``DuplicateObject``; a drop-then-add would tear the
    domain guard away for a moment and pay the validation scan again on a
    schema that already satisfies it. One catalog probe inside one ``DO``
    block is the guarded form the chain's adoption contract needs — and the
    names come from this module's constants, not from any caller.
    """
    op.execute(_GUARDED_CHECK_CONSTRAINT.format(constraint=constraint, table=table, check=check))  # nosec B608


def upgrade() -> None:
    # Domains first, so every index created below is provably indexing a closed
    # set of values on a table that cannot hold a value outside its predicate.
    _add_check_constraint_if_absent("ck_canonical_runs_status", "canonical_runs", _RUN_STATUS_CHECK)
    _add_check_constraint_if_absent(
        "ck_canonical_node_runs_status", "canonical_node_runs", _RUN_STATUS_CHECK
    )
    _add_check_constraint_if_absent(
        "ck_canonical_attempts_status", "canonical_attempts", _ATTEMPT_STATUS_CHECK
    )
    _add_check_constraint_if_absent(
        "ck_graph_continuations_status", "graph_continuations", _RUN_STATUS_CHECK
    )

    # The retention anti-join and the NodeRun RESTRICT foreign-key probe.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_runs_parent_node "
        "ON canonical_runs (parent_node_run_id)"
    )

    # The queue cursor: any single status, in (created_at, run_id) order, with
    # the keyset comparison on the same trailing columns.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_runs_status_created "
        "ON canonical_runs (status, ((payload->>'created_at')), run_id)"
    )

    # The continuation listing's sort, replacing the (status, project_id)
    # prefix no query ordered by. The project-scoped read keeps its own
    # (project_id, created_at) index from migration 021.
    op.execute("DROP INDEX IF EXISTS ix_graph_continuations_status")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_continuations_status_created "
        "ON graph_continuations (status, created_at, run_id)"
    )


def downgrade() -> None:
    # The same guards, mirrored: a downgrade re-run over an already-downgraded
    # schema is the chain's reverse adoption and must be as quiet.
    op.execute("DROP INDEX IF EXISTS ix_graph_continuations_status_created")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_graph_continuations_status "
        "ON graph_continuations (status, project_id)"
    )
    op.execute("DROP INDEX IF EXISTS ix_canonical_runs_status_created")
    op.execute("DROP INDEX IF EXISTS ix_canonical_runs_parent_node")
    op.execute(
        "ALTER TABLE graph_continuations DROP CONSTRAINT IF EXISTS ck_graph_continuations_status"
    )
    op.execute(
        "ALTER TABLE canonical_attempts DROP CONSTRAINT IF EXISTS ck_canonical_attempts_status"
    )
    op.execute(
        "ALTER TABLE canonical_node_runs DROP CONSTRAINT IF EXISTS ck_canonical_node_runs_status"
    )
    op.execute("ALTER TABLE canonical_runs DROP CONSTRAINT IF EXISTS ck_canonical_runs_status")
