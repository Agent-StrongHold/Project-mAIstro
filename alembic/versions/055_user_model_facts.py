"""Durable user-model tables (#1047, ADR-092526-4391).

Numbered ``054`` when written on the ``053`` base; develop's admission-generation
representation (#1892) claimed the same number on the same parent while this
branch was open, so per the chain's collision convention this revision
re-parents onto that ``054_task_admission_generations`` as ``055``.

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

Revision ID: 055
Revises: 054
Create Date: 2026-10-04
"""

from __future__ import annotations

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046/047/049/050/051/052: stamp-back and re-upgrade is
    # a live repair path, and the chain's contract is that re-applying a
    # revision over the schema it already built is adoption, not an error
    # (tests/migrations,
    # test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted).
    # A bare create_table failed that with DuplicateTable.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_model_facts (
            fact_id VARCHAR(64) NOT NULL,
            lineage_id VARCHAR(64) NOT NULL,
            revision INTEGER NOT NULL,
            supersedes VARCHAR(64),
            owner_user_id VARCHAR(128) NOT NULL,
            kind VARCHAR(64) NOT NULL,
            statement TEXT NOT NULL,
            evidence JSONB NOT NULL,
            first_observed TIMESTAMP WITH TIME ZONE NOT NULL,
            last_observed TIMESTAMP WITH TIME ZONE NOT NULL,
            last_reinforced TIMESTAMP WITH TIME ZONE NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            state VARCHAR(32) NOT NULL,
            valid_from TIMESTAMP WITH TIME ZONE,
            valid_until TIMESTAMP WITH TIME ZONE,
            sensitivity VARCHAR(32) NOT NULL,
            reusable BOOLEAN NOT NULL,
            correction JSONB,
            persona_hints JSONB NOT NULL,
            PRIMARY KEY (fact_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_model_facts_lineage_id ON user_model_facts (lineage_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_model_facts_owner_user_id "
        "ON user_model_facts (owner_user_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_model_statement_keys (
            fact_key VARCHAR(64) NOT NULL,
            lineage_id VARCHAR(64) NOT NULL,
            owner_user_id VARCHAR(128) NOT NULL,
            PRIMARY KEY (fact_key)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_model_statement_keys_lineage_id "
        "ON user_model_statement_keys (lineage_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_user_model_statement_keys_owner_user_id "
        "ON user_model_statement_keys (owner_user_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_model_statement_keys")
    op.execute("DROP TABLE IF EXISTS user_model_facts")
