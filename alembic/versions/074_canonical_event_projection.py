"""Canonical-Envelope -> durable-log projection (#2506).

The ADR-086 durable trigger log gains the canonical-source identity a row was
projected from, and the replay projector gains its two durable tables:

- ``event_log`` gains the nullable ``source_event_id`` column with a unique
  index. NULLs are distinct in both PostgreSQL's and SQLite's unique indexes,
  so legacy and non-canonical rows never collide; the one keyed row per
  canonical Event is what makes the legacy-bus bridge and the replay
  projector two ingress paths onto one durable fact instead of two
  occurrences.
- ``canonical_event_projection_streams`` is the projector's per-stream replay
  cursor (position + claim lease + fencing token), registered at the
  canonical stream watermark so retained pre-projection history is never
  rescanned.
- ``canonical_projection_failures`` is the bounded poison bookkeeping
  (attempts, backoff, terminal ``failed_at`` disposition) for events whose
  log append keeps failing.

Revision ID: 074
Revises: 073
Create Date: 2026-11-28
"""

from __future__ import annotations

from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None

#: Statement-for-statement twin of `pg_stores._SCHEMA` additions; the
#: schema-agreement test holds the two catalogues equal. `IF NOT EXISTS`
#: forms, because the chain is re-applied over already-migrated schemas
#: (stamp-back, #286) and a bare CREATE fails that re-application.
_STATEMENTS = (
    "ALTER TABLE event_log ADD COLUMN IF NOT EXISTS source_event_id TEXT",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_event_log_source_event_id "
    "ON event_log (source_event_id)",
    """CREATE TABLE IF NOT EXISTS canonical_event_projection_streams (
    stream_id TEXT PRIMARY KEY,
    position BIGINT NOT NULL DEFAULT 0,
    holder TEXT NOT NULL DEFAULT '',
    fencing_token TEXT NOT NULL DEFAULT '',
    lease_expires_at DOUBLE PRECISION NOT NULL DEFAULT 0
)""",
    """CREATE TABLE IF NOT EXISTS canonical_projection_failures (
    event_id TEXT PRIMARY KEY,
    stream_id TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    next_attempt_at DOUBLE PRECISION NOT NULL DEFAULT 0,
    failed_at DOUBLE PRECISION
)""",
)


def upgrade() -> None:
    for statement in _STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS canonical_projection_failures")
    op.execute("DROP TABLE IF EXISTS canonical_event_projection_streams")
    op.execute("DROP INDEX IF EXISTS idx_event_log_source_event_id")
    op.execute("ALTER TABLE event_log DROP COLUMN IF EXISTS source_event_id")
