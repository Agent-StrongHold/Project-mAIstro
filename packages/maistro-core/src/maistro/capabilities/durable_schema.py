"""Schema bootstrap for canonical capability approvals.

Invocation and Binding tables are owned by Alembic revisions 035 and 040 and
by their SQLite stores. This helper must not create a second Invocation
schema: an earlier draft used a full UNIQUE effect constraint and a JSONB
payload that contradicted the partial active-effect index and ``payload_json``
column the production stores actually write.
"""

from __future__ import annotations

from typing import Any

POSTGRES_APPROVAL_SCHEMA = """
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
    """Bootstrap approval identity on a standalone pool.

    Managed deployments also apply the Alembic revision. ``CREATE TABLE IF
    NOT EXISTS`` keeps the two from forking the approval key.
    """

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(POSTGRES_APPROVAL_SCHEMA)


__all__ = ["POSTGRES_APPROVAL_SCHEMA", "ensure_capability_schema"]
