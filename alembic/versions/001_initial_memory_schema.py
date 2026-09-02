"""Initial memory schema — tasks, memory_entries, knowledge_nodes, learnings, episodic_memories, outcomes.

Revision ID: 001
Revises:
Create Date: 2026-04-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgvector extension (required for memory_entries embedding column)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── tasks (TaskRecord) ──────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(24), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("workspace", sa.String(500), nullable=False),
        sa.Column("tier", sa.Integer, default=2),
        sa.Column("phase", sa.String(20), nullable=True),
        sa.Column("progress", postgresql.JSONB, nullable=True),
        sa.Column("result", postgresql.JSONB, nullable=True),
        sa.Column("constraints", postgresql.JSONB, nullable=True),
        sa.Column("branch", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime, nullable=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )

    # ── memory_entries (MemoryEntry) ────────────────────────────────
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace", sa.String(500), nullable=False, index=True),
        sa.Column("layer", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        # NOTE: this makes the column `text`, and the `ALTER` below does NOT
        # change that -- `IF NOT EXISTS` finds the column this line just
        # created and skips, silently. `memory_entries.embedding` was `text`
        # in every deployment until migration 029 repaired it (#188,
        # ADR-083026-4b70). Both lines are left exactly as they ran; a
        # migration records what happened, and the repair is forward.
        sa.Column("embedding", sa.Text, nullable=True),
    )
    # Intended to make the column a vector; a no-op in practice, see above.
    op.execute("ALTER TABLE memory_entries ADD COLUMN IF NOT EXISTS embedding vector(1536)")

    # ── knowledge_nodes (KnowledgeNode) ────────────────────────────
    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("workspace", sa.String(500), nullable=False, index=True),
        sa.Column("node_type", sa.String(50), nullable=False),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("file_path", sa.String(1000), nullable=False),
        sa.Column("depends_on", postgresql.JSONB, nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_knowledge_workspace_type", "knowledge_nodes", ["workspace", "node_type"])

    # ── learnings ──────────────────────────────────────────────────
    op.create_table(
        "learnings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("category", sa.String(100), nullable=False, default="general"),
        sa.Column("trigger_keys", postgresql.JSONB, nullable=False),
        sa.Column("learning", sa.Text, nullable=False),
        sa.Column("tool_name", sa.String(200), nullable=False),
        sa.Column("source_query", sa.Text, nullable=False),
        sa.Column("org_id", sa.String(200), nullable=False, default=""),
        sa.Column("team_id", sa.String(200), nullable=False, default=""),
        sa.Column("agent_id", sa.String(200), nullable=True),
        sa.Column("user_id", sa.String(200), nullable=True),
        sa.Column("scope", sa.String(50), nullable=False, default="agent"),
        sa.Column("hit_count", sa.Integer, nullable=False, default=0),
        sa.Column("status", sa.String(50), nullable=False, default="active"),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_learnings_org_tool", "learnings", ["org_id", "tool_name"])
    op.create_index("ix_learnings_status", "learnings", ["status"])

    # ── episodic_memories ──────────────────────────────────────────
    op.create_table(
        "episodic_memories",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("memory_id", sa.String(100), nullable=False, unique=True),
        sa.Column("tier", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("weight", sa.Float, nullable=False, default=0.3),
        sa.Column("org_id", sa.String(200), nullable=False, default=""),
        sa.Column("team_id", sa.String(200), nullable=False, default=""),
        sa.Column("agent_id", sa.String(200), nullable=True),
        sa.Column("user_id", sa.String(200), nullable=True),
        sa.Column("scope", sa.String(50), nullable=False, default="agent"),
        sa.Column("source", sa.String(500), nullable=False, default=""),
        sa.Column("context", postgresql.JSONB, nullable=True),
        sa.Column("reinforcement_count", sa.Integer, nullable=False, default=0),
        sa.Column("contradiction_count", sa.Integer, nullable=False, default=0),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("last_accessed_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("deleted", sa.Boolean, nullable=False, default=False),
    )
    op.create_index("ix_episodic_org_scope", "episodic_memories", ["org_id", "scope"])

    # ── outcomes ───────────────────────────────────────────────────
    op.create_table(
        "outcomes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False, default=""),
        sa.Column("model_used", sa.String(200), nullable=False, default=""),
        sa.Column("provider", sa.String(100), nullable=False, default=""),
        sa.Column("tool_calls", postgresql.JSONB, nullable=True),
        sa.Column("success", sa.Boolean, nullable=False, default=True),
        sa.Column("error_type", sa.String(100), nullable=False, default=""),
        sa.Column("response_time_ms", sa.Integer, nullable=False, default=0),
        sa.Column("org_id", sa.String(200), nullable=False, default=""),
        sa.Column("team_id", sa.String(200), nullable=False, default=""),
        sa.Column("user_id", sa.String(200), nullable=False, default=""),
        sa.Column("agent_id", sa.String(200), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=False, default=0),
        sa.Column("output_tokens", sa.Integer, nullable=False, default=0),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index("ix_outcomes_org_task", "outcomes", ["org_id", "task_type"])
    op.create_index("ix_outcomes_created_at", "outcomes", ["created_at"])


def downgrade() -> None:
    op.drop_table("outcomes")
    op.drop_table("episodic_memories")
    op.drop_table("learnings")
    op.drop_index("ix_knowledge_workspace_type", table_name="knowledge_nodes")
    op.drop_table("knowledge_nodes")
    op.drop_table("memory_entries")
    op.drop_table("tasks")
