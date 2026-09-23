"""Preserve canonical Invocation provenance in quota accounting (#718).

The aggregate quota row cannot provide at-most-once accounting or explain a
missing provider usage report by itself.  Keep one immutable evidence row per
canonical physical Invocation, then project it into the existing aggregate.

Revision ID: 041_quota_invocation_evidence
Revises: 040
Create Date: 2026-09-08

Re-ID'd twice during the develop integration. First 035 -> 039: the same
revision id was claimed by develop's capability-invocation migration, which
left alembic with two heads and a duplicate "035". Then 039 ->
041_quota_invocation_evidence: merging develop brought its own numeric
`039_canvas_job_admission_key` (and `040`, which chains onto it), so the
numeric slot was taken too. Following develop's string-suffixed naming and
chaining after the develop chain tip 040 keeps exactly one head; the id stays
under alembic's 32-character `alembic_version.version_num` limit (the live
chain test applies the whole chain to an empty database, which is where a
too-long id fails).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "041_quota_invocation_evidence"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quota_usage",
        sa.Column("unreported_count", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_table(
        "quota_invocation_evidence",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("cycle_key", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("usage_reported", sa.Boolean, nullable=False),
    )
    op.create_index(
        "ix_quota_invocation_evidence_provider_cycle",
        "quota_invocation_evidence",
        ["provider", "cycle_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quota_invocation_evidence_provider_cycle",
        table_name="quota_invocation_evidence",
    )
    op.drop_table("quota_invocation_evidence")
    op.drop_column("quota_usage", "unreported_count")
