"""Tables the PostgreSQL stores query but nothing ever created (#122).

`maistro.persistence`'s PostgreSQL half has been unwired since consolidation, so
the gap was invisible: `PgQuotaTracker`, `PgSessionStore`, `PgAuditLog` and
`PgPromptManager` all `SELECT`/`INSERT` against tables no migration defines, and
`PgAgentRegistry` — which does have a caller — upserts into an `agents` table in
the same position. Wiring the PostgreSQL backend without these turns a silent
in-memory fallback into a loud `UndefinedTableError`, which is better but still
not a working deployment.

Column definitions are taken from each store's own SQL and cross-checked against
its SQLite counterpart, which implements the same protocol and does carry a
schema. Where the two differ it is by type only: SQLite's `timestamp REAL` and
`TEXT` timestamps become `TIMESTAMPTZ`, and its `TEXT` JSON becomes `JSONB`.

The `security_*` tables move here from `maistro.security.pg_strikes._SCHEMA`,
which creates them at runtime on first use. That worked while the tracker owned
its own pool and nothing else touched those tables, but provisioning belongs in
one place once the container wires the backend — otherwise the schema a
deployment has depends on which code path happened to run first.

Revision ID: 005
Revises: 004
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005"
down_revision = "004_task_run_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── quota_usage (PgQuotaTracker) ───────────────────────────────
    # Composite PK, because the tracker's ON CONFLICT (provider, cycle_key)
    # accumulate is the whole mechanism: without the constraint the upsert is a
    # plain insert and every request starts a new usage row.
    op.create_table(
        "quota_usage",
        sa.Column("provider", sa.Text, primary_key=True),
        sa.Column("cycle_key", sa.Text, primary_key=True),
        sa.Column("input_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("request_count", sa.BigInteger, nullable=False, server_default="0"),
    )

    # ── sessions (PgSessionStore) ──────────────────────────────────
    # `timestamp` carries a server default: the store inserts (session_id, seq,
    # role, content) only, and its TTL purge compares `timestamp` against
    # to_timestamp(...). A nullable column with no default would make every row
    # immortal.
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.Text, primary_key=True),
        sa.Column("seq", sa.Integer, primary_key=True),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_sessions_timestamp", "sessions", ["timestamp"])

    # ── audit_log (PgAuditLog) ─────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("boundary", sa.Text, nullable=False, server_default=""),
        sa.Column("user_id", sa.Text, nullable=False, server_default=""),
        sa.Column("team_id", sa.Text, nullable=False, server_default=""),
        sa.Column("agent_id", sa.Text, nullable=False, server_default=""),
        sa.Column("tool_name", sa.Text, nullable=True),
        sa.Column("verdict", sa.Text, nullable=False, server_default="allowed"),
        sa.Column("detail", sa.Text, nullable=False, server_default=""),
        sa.Column("trace_id", sa.Text, nullable=False, server_default=""),
        sa.Column("request_id", sa.Text, nullable=False, server_default=""),
    )
    # The only ordering the store ever asks for, and the filters it allows.
    op.create_index("ix_audit_log_timestamp", "audit_log", ["timestamp"])
    op.create_index("ix_audit_log_user", "audit_log", ["user_id", "timestamp"])
    op.create_index("ix_audit_log_agent", "audit_log", ["agent_id", "timestamp"])

    # ── prompts (PgPromptManager) ──────────────────────────────────
    op.create_table(
        "prompts",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("version", sa.Integer, primary_key=True),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("config", postgresql.JSONB, nullable=True),
    )
    # Partial unique index, matching the SQLite store: one row may hold a given
    # label for a name, but the many unlabelled versions must not collide.
    op.create_index(
        "ix_prompts_name_label",
        "prompts",
        ["name", "label"],
        unique=True,
        postgresql_where=sa.text("label IS NOT NULL"),
    )

    # ── agents (PgAgentRegistry) ───────────────────────────────────
    # `name` is the conflict target of the registry's upsert, so it is the key.
    op.create_table(
        "agents",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("version", sa.Text, nullable=False, server_default=""),
        sa.Column("description", sa.Text, nullable=False, server_default=""),
        sa.Column("soul", sa.Text, nullable=False, server_default=""),
        sa.Column("model", sa.Text, nullable=False, server_default=""),
        sa.Column("model_fallbacks", postgresql.JSONB, nullable=True),
        sa.Column("model_constraints", postgresql.JSONB, nullable=True),
        sa.Column("tools", postgresql.JSONB, nullable=True),
        sa.Column("skills", postgresql.JSONB, nullable=True),
        sa.Column("rules", postgresql.JSONB, nullable=True),
        sa.Column("trust_tier", sa.Text, nullable=False, server_default=""),
        sa.Column("priority_tier", sa.Integer, nullable=True),
        sa.Column("max_tool_rounds", sa.Integer, nullable=True),
        sa.Column("reasoning_strategy", sa.Text, nullable=False, server_default=""),
        sa.Column("memory_config", postgresql.JSONB, nullable=True),
        sa.Column("provenance", postgresql.JSONB, nullable=True),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_agents_active", "agents", ["active"])

    # ── security_* (PgStrikeTracker, PgRateLimiter) ────────────────
    op.create_table(
        "security_strikes",
        sa.Column("user_id", sa.Text, primary_key=True),
        sa.Column("strike_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("scrutiny_level", sa.Text, nullable=False, server_default="normal"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("last_violation_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_appeal", sa.Text, nullable=True, server_default=""),
        sa.Column("last_appeal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_table(
        "security_violations",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("boundary", sa.Text, nullable=False, server_default="user_input"),
        sa.Column("detail", sa.Text, nullable=True, server_default=""),
        sa.ForeignKeyConstraint(["user_id"], ["security_strikes.user_id"]),
    )
    op.create_index("ix_security_violations_user", "security_violations", ["user_id"])
    op.create_table(
        "security_rate_limits",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("count", sa.Integer, nullable=False, server_default="1"),
    )
    op.create_index("ix_rate_limits_expiry", "security_rate_limits", ["window_start"])


def downgrade() -> None:
    op.drop_table("security_rate_limits")
    op.drop_table("security_violations")
    op.drop_table("security_strikes")
    op.drop_table("agents")
    op.drop_table("prompts")
    op.drop_table("audit_log")
    op.drop_table("sessions")
    op.drop_table("quota_usage")
