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
    effect_scope TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL,
    CONSTRAINT uq_capability_approval_effect
      UNIQUE (run_id, effect_scope, binding_id, effect_key)
);
"""


async def ensure_capability_schema(pool: Any) -> None:
    """Bootstrap approval identity on a standalone pool.

    Managed deployments also apply the Alembic revision. ``CREATE TABLE IF
    NOT EXISTS`` keeps the two from forking the approval key. A table created
    before effect scoping (the #55 shape, keyed on the physical visit) is
    upgraded in place with ``ADD COLUMN IF NOT EXISTS`` — one idempotent
    statement, the same compatibility half the SQLite store gives its legacy
    tables; new tables get the scope-keyed constraint inline.
    """

    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(POSTGRES_APPROVAL_SCHEMA)
        await conn.execute(
            "ALTER TABLE capability_approvals "
            "ADD COLUMN IF NOT EXISTS effect_scope TEXT NOT NULL DEFAULT ''"
        )


__all__ = ["POSTGRES_APPROVAL_SCHEMA", "ensure_capability_schema"]
