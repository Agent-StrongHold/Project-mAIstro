"""Issue #398: canvas job retry backoff column.

Revision ID: 004
Revises: 003
Create Date: 2026-10-25

Adds ``next_retry_at`` to generation_jobs, mirroring the root chain's 048: a
requeued receipt is not claimable until this instant. Nullable — NULL means
the job was never requeued, or its scheduled delay has been taken by a claim.
"""

from __future__ import annotations

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent, mirroring the root chain's 048: a re-run must not collide
    # with a column an earlier upgrade already added.
    op.execute("ALTER TABLE generation_jobs ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ")


def downgrade() -> None:
    op.drop_column("generation_jobs", "next_retry_at")
