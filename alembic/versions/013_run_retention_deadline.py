"""A retention deadline on the canonical Run (#131, ADR-082226-c126).

Chat turns admit as one Run each, which is a growth rate the spine has never
been asked to carry. `InMemoryRunStore` grew a last-resort eviction bound in
#132; `canonical_runs` had none, and a Postgres table that grows without limit
is the same defect with a slower fuse.

`retention_expires_at` duplicates `payload->>'retention_expires_at'`, which is
the same trade migration 010 already makes for `status`: the payload stays the
single source of truth for the model, and the few fields a query filters on get
a real column so the query can use an index.

It has to be a column rather than an expression index over the payload, because
`text::timestamptz` is STABLE (it reads the session `TimeZone`), so PostgreSQL
refuses it in an index — the cast would have to be materialised somewhere, and
a column is the honest place.

The index is partial on terminal status: the sweep only ever deletes terminal
Runs (a deadline is a floor, not a ceiling — live work keeps its execution
identity), so indexing the rest would be dead weight on the hot insert path.
It is the mirror image of `ix_canonical_runs_live` from 010.

NULL means "retain indefinitely", so every Run already recorded keeps exactly
the retention it has today and the upgrade needs no backfill.

Revision ID: 013
Revises: 012
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None

_TERMINAL = "status IN ('completed', 'failed', 'cancelled', 'timed_out')"


def upgrade() -> None:
    op.add_column(
        "canonical_runs",
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_canonical_runs_retention",
        "canonical_runs",
        ["retention_expires_at"],
        postgresql_where=sa.text(f"retention_expires_at IS NOT NULL AND {_TERMINAL}"),
    )


def downgrade() -> None:
    op.drop_index("ix_canonical_runs_retention", table_name="canonical_runs")
    op.drop_column("canonical_runs", "retention_expires_at")
