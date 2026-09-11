"""Schema bootstrap helpers for canonical capability effect stores."""

from __future__ import annotations

from typing import Any

POSTGRES_SCHEMA = """
CREATE TABLE IF NOT EXISTS capability_bindings (
    binding_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    node_id TEXT NOT NULL DEFAULT '',
    capability TEXT NOT NULL,
    payload JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS capability_invocations (
    invocation_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    payload JSONB NOT NULL,
    CONSTRAINT uq_capability_invocation_effect
      UNIQUE (run_id, node_run_id, binding_id, effect_key)
);
CREATE INDEX IF NOT EXISTS idx_capability_invocation_attempt
  ON capability_invocations (attempt_id, created_at, invocation_id);
CREATE TABLE IF NOT EXISTS capability_approvals (
    request_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    node_run_id TEXT NOT NULL,
    binding_id TEXT NOT NULL,
    effect_key TEXT NOT NULL,
    payload JSONB NOT NULL,
    CONSTRAINT uq_capability_approval_effect
      UNIQUE (run_id, node_run_id, binding_id, effect_key)
);
"""


async def ensure_capability_schema(pool: Any) -> None:
    """Bootstrap standalone pools; managed containers require the migration."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(POSTGRES_SCHEMA)


__all__ = ["POSTGRES_SCHEMA", "ensure_capability_schema"]
