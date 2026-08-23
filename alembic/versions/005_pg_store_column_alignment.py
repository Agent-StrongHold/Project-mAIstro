"""Add the six columns the pg_* stores write and no migration ever created (#122).

`maistro.container` sends a `postgresql://` URL down the in-memory branch, so
the PostgreSQL stores have never run against a migrated database. Wiring them
(the point of #122) surfaces that their SQL and the schema disagree. Verified
against PostgreSQL 18.6 with revisions 001-004 applied:

    learnings.store  -> UndefinedColumnError: column "rca_category" of
                        relation "learnings" does not exist
    outcomes.record  -> UndefinedColumnError: column "charged_microchips" of
                        relation "outcomes" does not exist

Six columns in total, all of them fields that already exist on the `Learning`
and `Outcome` dataclasses and are already read back by `_row_to_learning`:

    learnings: rca_category, rca_prevention, success_after_use, failure_after_use
    outcomes:  charged_microchips, pricing_version

Every one is added with a server default, because existing rows need a value
and because these columns are written by a raw INSERT rather than through the
ORM. That distinction is the reason this revision exists at all: migration 001
declares its NOT NULL columns with SQLAlchemy's `default=`, which is applied
*in Python by the ORM* and emits no DEFAULT clause in the DDL. A raw INSERT
that omits such a column gets a NOT NULL violation, not the default. The store
fixes in this same change supply those columns explicitly rather than leaning
on a default that is not there.

`charged_microchips` is BIGINT rather than INTEGER for the same reason
`quota_usage`'s counters are: it is a running charge, and a 32-bit ceiling on
an accounting column fails partway through a busy month, on the billing path.

Revision ID: 005_pg_store_alignment
Revises: 004_quota_sessions
Create Date: 2026-08-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "005_pg_store_alignment"
down_revision = "004_quota_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── learnings: the RCA and reinforcement fields (PgLearningStore) ──
    # `_row_to_learning` already reads all four back, so before this revision a
    # `SELECT *` returned rows whose rca/reinforcement fields silently fell to
    # their `row.get(..., default)` fallbacks — the read half failed quietly
    # while only the write half raised.
    op.add_column("learnings", sa.Column("rca_category", sa.String(100), nullable=True))
    op.add_column(
        "learnings",
        sa.Column("rca_prevention", sa.Text, nullable=False, server_default=""),
    )
    op.add_column(
        "learnings",
        sa.Column(
            "success_after_use", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column(
        "learnings",
        sa.Column(
            "failure_after_use", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
    )

    # ── outcomes: the billing fields (PgOutcomeStore) ──────────────────
    op.add_column(
        "outcomes",
        sa.Column(
            "charged_microchips",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "outcomes",
        sa.Column("pricing_version", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("outcomes", "pricing_version")
    op.drop_column("outcomes", "charged_microchips")
    op.drop_column("learnings", "failure_after_use")
    op.drop_column("learnings", "success_after_use")
    op.drop_column("learnings", "rca_prevention")
    op.drop_column("learnings", "rca_category")
