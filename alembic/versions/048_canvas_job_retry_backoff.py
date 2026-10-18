"""Issue #398: generation_jobs.next_retry_at — durable retry backoff.

A requeued Canvas receipt is not claimable again until ``next_retry_at``. The
requeueing writers — ``CanvasJobRunner.tick_once``'s failure path and
``PgCanvasStore.reap_expired_leases`` — both compute the delay from the shared
``RetryBackoff`` schedule and persist it on the row, and
``claim_next_pending`` refuses a receipt whose ``next_retry_at`` is in the
future (clearing the column on the claim that finally takes the attempt).

The column is durable on purpose: a worker that dies right after requeueing a
job must not lose the backoff, or the next claim loop retries the provider in
a tight cycle — the exact unbounded behavior #398 removes. Nullable: a
never-failed job has no scheduled retry, and every pre-#398 row legitimately
reads as claimable.

Revision ID: 048
Revises: 047
Create Date: 2026-10-25
"""

from __future__ import annotations

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent like 044: the chain's "adopt a live table" legs replay older
    # revisions over an existing schema, so re-stamping and re-upgrading must
    # not collide with a column an earlier full upgrade already added.
    op.execute("ALTER TABLE generation_jobs ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ")


def downgrade() -> None:
    op.drop_column("generation_jobs", "next_retry_at")
