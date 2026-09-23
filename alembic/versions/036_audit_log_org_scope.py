"""Persist and index the audit log organization scope (#1155).

The audit stores accepted ``AuditEntry.org_id`` before the database shape did,
so the value was discarded on write and a scoped read could not constrain SQL.
The expand phase stays nullable so old and new writers can coexist; its default
and backfill represent existing rows with the explicit empty-string
system/unscoped scope. A later contract migration may make the column
non-nullable once old writers are retired.

Revision ID: 036_audit_log_org_scope
Revises: 040
Create Date: 2026-09-10

Re-parented twice, both times because develop took the same parent while this
branch was open: first onto 038, then onto 039 after
`039_canvas_job_admission_key` landed (#1531); merging develop's `040`
(`down_revision = "039"`) then restored a two-head fork that fails every
deployment's ``upgrade head`` with "Multiple head revisions are present". This
revision now follows the develop chain tip 040, keeping the chain linear with
the audit scope migration as its single head — the same reconciliation revision
040's own docstring records for its two renumberings.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_audit_log_org_scope"
down_revision = "040"
branch_labels = None
depends_on = None


_BACKFILL_BATCH_SIZE = 1_000


def _backfill_org_scope(connection: sa.Connection, *, batch_size: int) -> None:
    """Normalize legacy rows without holding one write lock for the table."""
    statement = sa.text(
        """
        UPDATE audit_log
        SET org_id = ''
        WHERE id IN (
            SELECT id
            FROM audit_log
            WHERE org_id IS NULL
            ORDER BY id
            LIMIT :batch_size
        )
        """
    )
    while True:
        result = connection.execute(statement, {"batch_size": batch_size})
        if result.rowcount == 0:
            return


def upgrade() -> None:
    # Expand: old application versions omit this column while rolling deploys
    # overlap, so the new shape must remain nullable. The default protects
    # concurrent old writes; the batched update makes legacy rows explicit.
    op.add_column(
        "audit_log",
        sa.Column("org_id", sa.Text, nullable=True, server_default=sa.text("''")),
    )
    _backfill_org_scope(op.get_bind(), batch_size=_BACKFILL_BATCH_SIZE)

    # CREATE INDEX CONCURRENTLY cannot run inside Alembic's normal transaction.
    # The autocommit block also prevents this index from blocking audit writes.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_audit_log_scope",
            "audit_log",
            ["org_id", "timestamp"],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    # Match the online upgrade: dropping the index should not take the audit
    # table's write path offline during a rollback.
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_audit_log_scope",
            table_name="audit_log",
            postgresql_concurrently=True,
        )
    op.drop_column("audit_log", "org_id")
