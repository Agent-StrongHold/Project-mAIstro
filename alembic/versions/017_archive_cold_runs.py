"""Tombstone columns for the archive tier (#273, ADR-082226-f436 decisions 2 and 10).

Archiving moves a record's *payload* to object storage and leaves the row.
`canonical_runs` was already shaped for that without anyone planning it:
identity and scope are real columns (`run_id`, `workspace_id`, `project_id`,
`parent_run_id`, `status`), and only `payload` carries the heavy content — the
graph snapshot, the result, the Attempt evidence. So every foreign key into the
spine keeps pointing at a row that still exists, which is the whole reason
decision 2 calls the tier safe.

Three changes per table, and the third is the one that matters.

**`archive_key`** addresses the object. Nullable, so every existing row keeps
exactly the meaning it has today and the upgrade needs no backfill.

**`payload` becomes nullable.** The alternative was to leave it NOT NULL and
write a stub, which is worse: a stub is a payload that validates as a model and
is not the record, and the first bug would be a caller reading the stub and
believing it.

**A CHECK that exactly one of them is present.** `payload IS NOT NULL` XOR
`archive_key IS NOT NULL`. Without it "neither" is representable, and "neither"
is data loss with no error attached — a row that says a Run exists and can no
longer say what it was. The constraint makes the lost state unwritable rather
than merely unlikely.

`finished_at` is promoted to a real column on `canonical_runs` for the same
reason migration 013 promoted `retention_expires_at`: the sweep filters on it,
`text::timestamptz` is STABLE so PostgreSQL refuses it in an index, and a
column is the honest place to materialise it. Backfilled from the payload, so
Runs recorded before this migration are eligible on the same terms as new ones.

The partial index encodes decision 10's predicate directly: archive-eligible is
terminal, `retention_expires_at IS NULL` (kept indefinitely, so nobody chose to
delete it), and not already archived. A Run *with* a retention deadline is
purge-eligible and is never archived — the two populations are disjoint, and
indexing only one of them keeps the sweep off the hot insert path.

Revision ID: 017
Revises: 016
Create Date: 2026-08-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None

#: The same terminal set migration 013 uses. Spelled again rather than imported
#: because a migration must keep meaning what it meant on the day it ran, even
#: if the application's constant later moves.
_TERMINAL = "status IN ('completed', 'failed', 'cancelled', 'timed_out')"

_TABLES = ("canonical_runs", "canonical_node_runs", "canonical_attempts")


def _exactly_one(table: str) -> str:
    return f"ck_{table}_payload_xor_archive_key"


def upgrade() -> None:
    for table in _TABLES:
        op.add_column(table, sa.Column("archive_key", sa.Text, nullable=True))
        op.alter_column(table, "payload", existing_type=sa.JSON, nullable=True)
        op.create_check_constraint(
            _exactly_one(table),
            table,
            "(payload IS NOT NULL) <> (archive_key IS NOT NULL)",
        )

    op.add_column(
        "canonical_runs",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Backfill from the payload the column duplicates. `payload` is still
    # non-null for every row at this point -- nothing has been archived yet --
    # so this cannot skip a row it should have filled.
    op.execute(
        sa.text(
            """UPDATE canonical_runs
                  SET finished_at = (payload->>'finished_at')::timestamptz
                WHERE payload->>'finished_at' IS NOT NULL"""
        )
    )
    op.create_index(
        "ix_canonical_runs_archive_candidates",
        "canonical_runs",
        ["finished_at"],
        postgresql_where=sa.text(
            f"archive_key IS NULL AND retention_expires_at IS NULL AND {_TERMINAL}"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_runs_archive_candidates", table_name="canonical_runs")
    op.drop_column("canonical_runs", "finished_at")
    for table in _TABLES:
        op.drop_constraint(_exactly_one(table), table, type_="check")
        # Reversing the nullability needs every row to have a payload again, so
        # a database with archived records cannot downgrade silently: the ALTER
        # fails on the archived rows rather than deleting them. Rehydrate first.
        op.alter_column(table, "payload", existing_type=sa.JSON, nullable=False)
        op.drop_column(table, "archive_key")
