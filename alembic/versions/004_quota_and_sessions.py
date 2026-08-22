"""Quota usage and session history — the two tables their stores query and no migration created.

`PgQuotaTracker` and `PgSessionStore` are the intended durable owners of quota
and conversation history per ADR-082226-5104, and both issued SQL against tables
that did not exist in any revision (#182). Migrations 001-003 create `tasks`,
`memory_entries`, `knowledge_nodes`, `learnings`, `episodic_memories`,
`outcomes`, the canvas tables and the design-project tables — neither of these
two appears among them, so both stores failed with `UndefinedTableError` on
their first call against a migrated database.

The DDL here is read off the queries in `persistence/pg_quota.py` and
`persistence/pg_sessions.py` rather than invented, and three details are
load-bearing enough to say out loud:

- `quota_usage` needs `(provider, cycle_key)` as a key, because `record_usage`
  upserts with `ON CONFLICT (provider, cycle_key)`. Without a matching unique
  constraint that statement raises instead of accumulating.
- `sessions.timestamp` needs a server default, because `append_messages` inserts
  four columns and never supplies it, while `get_history` filters on it and
  `purge_expired` deletes on it. A nullable column with no default would make
  every row invisible to reads and immune to the purge.
- `(session_id, seq)` is a primary key so that the `MAX(seq) + 1` race in
  `append_messages` fails loudly rather than silently seating two messages at
  one sequence number. See the note in `downgrade`'s counterpart below.

**On the revision id.** This is `004_quota_sessions` off `003`, and PR #181
adds a `004` off `003` as well. Whichever merges second must be repointed at the
first so the chain stays linear — alembic does not merge branches for you, and
two heads means `upgrade head` fails on every deployment at once, after both
changes have already merged and looked fine apart.
`tests/migrations/test_single_migration_head.py` fails the moment that happens,
so it is caught on the merge rather than in production.

Revision ID: 004_quota_sessions
Revises: 003
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "004_quota_sessions"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── quota_usage (PgQuotaTracker) ───────────────────────────────
    # BIGINT on the counters, not INTEGER: these accumulate every token a
    # provider serves across a billing cycle, and `record_usage` only ever adds
    # to them. A 32-bit column overflows partway through a busy month, and the
    # failure lands on the accounting path rather than anywhere visible.
    op.create_table(
        "quota_usage",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("cycle_key", sa.Text, primary_key=True),
        sa.Column("input_tokens", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("total_tokens", sa.BigInteger, nullable=False, server_default=sa.text("0")),
        sa.Column("request_count", sa.BigInteger, nullable=False, server_default=sa.text("0")),
    )

    # ── sessions (PgSessionStore) ──────────────────────────────────
    # The composite key is doing real work. `append_messages` derives its
    # sequence with `SELECT COALESCE(MAX(seq), -1) + 1` and then inserts, which
    # is a read-then-write with a window in it: two workers appending to one
    # session both read the same `next_seq`. With this key the second writer
    # gets a constraint violation; without it, two different messages quietly
    # occupy the same sequence and `ORDER BY seq` returns them in arbitrary
    # order. The schema is what decides whether that race is loud or silent.
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("seq", sa.Integer, primary_key=True, autoincrement=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        # Server-side default, because no caller passes it.
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # The TTL purge is a full-table `DELETE ... WHERE timestamp <= $1` on every
    # `append_messages` call, so it runs on the hot write path and needs its
    # own index rather than a sequential scan that grows with history.
    op.create_index("idx_sessions_timestamp", "sessions", ["timestamp"])


def downgrade() -> None:
    op.drop_index("idx_sessions_timestamp", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("quota_usage")
