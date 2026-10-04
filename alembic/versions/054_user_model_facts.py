"""Durable user-model tables (#1047, ADR-092526-4391).

The durable user model is a separate ``UserModelFact`` record type kept in
PostgreSQL as the system of record (ADR-082226-5104 §§1, 5, 6); Ladybug may
cache a projection and is never authoritative. Two tables:

- ``user_model_facts`` -- one row per fact revision. Every change appends a
  revision (promote/reinforce/correct/mark-private); tombstoning deletes the
  lineage's content revisions and keeps one tombstone revision recording who
  deleted the fact and why, so a deleted statement is gone from the record
  while the lineage identity survives.
- ``user_model_statement_keys`` -- owner-bound statement key to lineage id.
  Rows are never deleted: they are what lets a tombstone block every wording
  its lineage ever held, including one replayed from a stale Ladybug working
  graph. Re-keyed by ``fact_key(owner_user_id, normalize_statement(statement))``
  so a producer relabelling a kind cannot step around an owner's tombstone.

All timestamps are ``TIMESTAMP WITH TIME ZONE``: fact validity windows are
compared against aware UTC instants (SPEC-241 temporal semantics), and a
naive local time on either side would silently shift them.

Revision ID: 054
Revises: 053
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Double,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_model_facts",
        Column("fact_id", String(64), primary_key=True),
        Column("lineage_id", String(64), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("supersedes", String(64), nullable=True),
        Column("owner_user_id", String(128), nullable=False),
        Column("kind", String(64), nullable=False),
        Column("statement", Text, nullable=False),
        Column("evidence", JSONB, nullable=False),
        Column("first_observed", DateTime(timezone=True), nullable=False),
        Column("last_observed", DateTime(timezone=True), nullable=False),
        Column("last_reinforced", DateTime(timezone=True), nullable=False),
        Column("confidence", Double, nullable=False),
        Column("state", String(32), nullable=False),
        Column("valid_from", DateTime(timezone=True), nullable=True),
        Column("valid_until", DateTime(timezone=True), nullable=True),
        Column("sensitivity", String(32), nullable=False),
        Column("reusable", Boolean, nullable=False),
        Column("correction", JSONB, nullable=True),
        Column("persona_hints", JSONB, nullable=False),
    )
    op.create_index("ix_user_model_facts_lineage_id", "user_model_facts", ["lineage_id"])
    op.create_index("ix_user_model_facts_owner_user_id", "user_model_facts", ["owner_user_id"])
    op.create_table(
        "user_model_statement_keys",
        Column("fact_key", String(64), primary_key=True),
        Column("lineage_id", String(64), nullable=False),
        Column("owner_user_id", String(128), nullable=False),
    )
    op.create_index(
        "ix_user_model_statement_keys_lineage_id",
        "user_model_statement_keys",
        ["lineage_id"],
    )
    op.create_index(
        "ix_user_model_statement_keys_owner_user_id",
        "user_model_statement_keys",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_table("user_model_statement_keys")
    op.drop_table("user_model_facts")
