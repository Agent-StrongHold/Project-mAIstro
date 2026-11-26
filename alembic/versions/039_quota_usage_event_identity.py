"""Persist quota event identities for crash-safe retries (#1204).

Revision ID: 039_quota_usage_event_identity
Revises: 042
Create Date: 2026-09-10

Originally parented on ``038`` when trunk's tip was 038; merging develop's
``039_canvas_job_admission_key`` and ``040`` restored a two-head fork that
fails every deployment's ``upgrade head`` with "Multiple head revisions are
present". This revision now follows the develop chain tip
``036_audit_log_org_scope``, keeping the chain linear — the same
reconciliation this repository's other re-parented revisions document.
When develop's ``042_manual_fire_occurrence_identity`` then took
``036_audit_log_org_scope`` as its parent while this branch was open, the
re-merge forked the chain into two heads again (this revision and ``042``
both children of ``036_audit_log_org_scope``), so the parent moved once
more onto ``042`` — the develop chain tip — restoring the single linear
head. Only the identifier changes; the DDL is untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "039_quota_usage_event_identity"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_usage_events",
        sa.Column("event_id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("cycle_key", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.BigInteger, nullable=False),
        sa.Column("output_tokens", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("quota_usage_events")
