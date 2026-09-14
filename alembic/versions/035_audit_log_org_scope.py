"""Persist and index the audit log organization scope (#1155).

The audit stores accepted ``AuditEntry.org_id`` before the database shape did,
so the value was discarded on write and a scoped read could not constrain SQL.
The expand phase stays nullable so old and new writers can coexist; its default
and backfill represent existing rows with the explicit empty-string
system/unscoped scope. A later contract migration may make the column
non-nullable once old writers are retired.

Revision ID: 035
Revises: 034
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Expand: old application versions omit this column while rolling deploys
    # overlap, so the new shape must remain nullable. The default protects
    # concurrent old writes; the update below makes legacy rows explicit.
    op.add_column(
        "audit_log",
        sa.Column("org_id", sa.Text, nullable=True, server_default=sa.text("''")),
    )
    op.execute(sa.text("UPDATE audit_log SET org_id = '' WHERE org_id IS NULL"))
    op.create_index(
        "ix_audit_log_scope",
        "audit_log",
        ["org_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_scope", table_name="audit_log")
    op.drop_column("audit_log", "org_id")
