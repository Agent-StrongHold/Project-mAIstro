"""A session turn's identity becomes a row of its own (#327, ADR-083026-5fab).

`append_messages` was atomic and serialized but not idempotent: the advisory
lock added for #327's other criteria makes two *different* writers safe and
says nothing about the same writer arriving twice. `ChatAttemptExecutor`
retries one turn as a second Attempt under the same NodeRun, so a retried turn
appended the user's message again at fresh sequence numbers.

The marker is a row rather than a column on `sessions` because the fact has a
different arity from a message: one turn writes several messages, so a unique
index over (session_id, turn_id) on the message table would reject the second
message of the very batch it is meant to admit.

`timestamp` carries the same server default and index as `sessions.timestamp`,
because the marker is purged by the same TTL sweep as the messages it admitted.
A marker outliving its messages would suppress a turn that no longer exists.

Revision ID: 023
Revises: 022
Create Date: 2026-08-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "session_turns",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("turn_id", sa.Text, primary_key=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_session_turns_timestamp", "session_turns", ["timestamp"])


def downgrade() -> None:
    # Lossless in the direction that matters: the markers record only that a
    # turn was already appended, and every message they admitted stays in
    # `sessions`. What is lost is the ability to recognize a later retry, which
    # a database rolled back to 022 could not do anyway.
    op.drop_index("ix_session_turns_timestamp", table_name="session_turns")
    op.drop_table("session_turns")
