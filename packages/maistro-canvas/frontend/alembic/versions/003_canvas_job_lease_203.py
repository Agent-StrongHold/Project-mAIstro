"""SPEC-203: canvas job lease/retry columns.

Revision ID: 003
Revises: 002
Create Date: 2026-06-09

Adds lease + retry bookkeeping to generation_jobs so the CanvasJobRunner can
claim jobs atomically (FOR UPDATE SKIP LOCKED) and reap leases from workers that
died mid-job:

- attempts          — incremented at claim time; bounds retries
- max_attempts      — per-job retry ceiling (default 3)
- leased_by         — worker id holding the current RUNNING lease
- lease_expires_at  — when the lease goes stale and the reaper may reclaim

A partial index on (status) WHERE status='pending' keeps claim_next_pending's
hot-path scan cheap as the table grows.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "generation_jobs",
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("leased_by", sa.Text, nullable=True),
    )
    op.add_column(
        "generation_jobs",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_generation_jobs_pending",
        "generation_jobs",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_pending", table_name="generation_jobs")
    op.drop_column("generation_jobs", "lease_expires_at")
    op.drop_column("generation_jobs", "leased_by")
    op.drop_column("generation_jobs", "max_attempts")
    op.drop_column("generation_jobs", "attempts")
