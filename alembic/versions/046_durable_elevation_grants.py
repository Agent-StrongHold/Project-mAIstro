"""Persist short-lived elevation grants in the canonical database.

Rebased onto the trunk chain three times (#72 merge, the 2026-09 develop
sync, then the #1204 sync that brought `039_quota_usage_event_identity`):
the revision ids up to 038 were already taken by the canonical migrations,
so the table first attached as "039" — and when develop added its own
`039` (canvas job admission key) on the same parent "038", that collision
made `alembic history` fail outright ("042 overlaps with other requested
revisions 039"). It was renumbered to 043 on parent 042, and when develop
then landed its own #1204 migration `039_quota_usage_event_identity` on
the same parent 042, that left two heads — and when develop then landed
`044_canvas_store_tables` on `039_quota_usage_event_identity`, that took
"044" too. It therefore attached after develop's chain tip `044` as
`045` — until develop's #1194 sync landed its own
`045_capability_invocation_logical_effect` on parent `043`, claiming the
same id. Per the same convention it now attaches after develop's chain
tip `045` as `046`, keeping the chain linear with exactly one head.

The DDL is guarded (`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT
EXISTS`), matching the SQLite twin's `ensure_schema` and the adoption
rule 044 states for the chain: the chain-level re-application test
stamps a migrated database back and re-upgrades it, so a bare
`CREATE TABLE` here failed that walk with `DuplicateTable` — the same
shape that broke CI's coverage (PostgreSQL) leg for #1194's 045. A
database that already carries `elevation_grants` is adopted untouched;
a fresh one is built to exactly the definition the runtime store reads.
"""

from __future__ import annotations

from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS elevation_grants (
            id BIGSERIAL PRIMARY KEY,
            principal_id TEXT NOT NULL,
            action_class TEXT NOT NULL,
            kind TEXT NOT NULL,
            granted_at TIMESTAMPTZ NOT NULL,
            ttl_seconds INTEGER NOT NULL,
            signed_by TEXT NOT NULL,
            action_args_hash TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_elevation_grants_lookup "
        "ON elevation_grants (principal_id, action_class, granted_at)"
    )


def downgrade() -> None:
    op.drop_index("idx_elevation_grants_lookup", table_name="elevation_grants")
    op.drop_table("elevation_grants")
