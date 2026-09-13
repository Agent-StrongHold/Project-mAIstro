"""Persist and index the audit log organization scope (#1155).

The audit stores accepted ``AuditEntry.org_id`` before the database shape did,
so the value was discarded on write and a scoped read could not constrain SQL.
Existing rows are deliberately represented as the empty string: they are
system/unscoped entries, not members of an arbitrary tenant.

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
    op.add_column(
        "audit_log",
        sa.Column("org_id", sa.Text, nullable=False, server_default=sa.text("''")),
    )
    op.create_index(
        "ix_audit_log_scope",
        "audit_log",
        ["org_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_log_scope", table_name="audit_log")
    op.drop_column("audit_log", "org_id")
