"""Columns `PgLearningStore.store` writes that the learnings table lacks (#122).

Same drift as the outcomes table, one store over. `store()` inserts
`rca_category`, `rca_prevention`, `success_after_use` and `failure_after_use`;
migration 001 created none of them, so every insert failed with
`UndefinedColumnError`. The SQLite twin has carried all four for some time — the
two implementations that claim the same protocol disagreed about the table, and
only the one nothing exercised was wrong.

`source_query` gets a server default rather than new columns: migration 001
declared it `NOT NULL` with no default of any kind, and the store does not write
it. #122 also fixes the store to persist it, for the same reason it now persists
`org_id` — a column the reader expects and the writer omits is a column that is
always empty. The default stays as the backstop for a caller that has nothing
meaningful to put there.

Types follow the SQLite schema and the `Learning` dataclass.

Revision ID: 009
Revises: 008
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("learnings", sa.Column("rca_category", sa.Text, nullable=True))
    op.add_column(
        "learnings",
        sa.Column("rca_prevention", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "learnings",
        sa.Column("success_after_use", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "learnings",
        sa.Column("failure_after_use", sa.Integer, nullable=False, server_default="0"),
    )
    op.execute("ALTER TABLE learnings ALTER COLUMN source_query SET DEFAULT ''")


def downgrade() -> None:
    op.execute("ALTER TABLE learnings ALTER COLUMN source_query DROP DEFAULT")
    op.drop_column("learnings", "failure_after_use")
    op.drop_column("learnings", "success_after_use")
    op.drop_column("learnings", "rca_prevention")
    op.drop_column("learnings", "rca_category")
