"""Locating a real PostgreSQL for the conformance suites.

Lives in `maistro.testing` rather than a conftest because three suites need it —
persistence (#122), the execution spine (#132), and the container wiring — and
they sit in sibling test directories that cannot import each other's conftest.
A helper duplicated per directory would be several definitions of "is there a
database", which is the drift the conformance suites exist to catch.
"""

from __future__ import annotations

import os
from typing import Any

#: Environment variable naming a *migrated* PostgreSQL to test against. CI runs
#: a `postgres` service and `alembic upgrade head` before pytest; unset locally,
#: the PostgreSQL cases of each backend-parametrized suite skip.
POSTGRES_DSN_ENV = "MAISTRO_TEST_PG_DSN"


def postgres_dsn() -> str:
    """The configured DSN, or ``""`` when no server is available."""
    return os.getenv(POSTGRES_DSN_ENV, "").strip()


async def provision_workspace(pool: Any, workspace_id: str) -> None:
    """Give a PG fixture the canonical Workspace its Root Project needs (#37).

    The admission fence makes ``create_root`` refuse a Workspace id nothing
    canonical owns, which is exactly what every scratch id a suite mints is
    until provisioned. Production never hits this — the container provisions
    its configured Workspace at startup and Hive's imports provision theirs —
    so fixtures provision the same way, through ``PgWorkspaceStore.create``.

    Idempotent on purpose: workspace rows are durable and deliberately not in
    the scratch-truncate list, so a suite re-run meets the id it wrote last
    time. The pool is shared with the caller; nothing here closes it.
    """
    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.pg_store import PgWorkspaceStore

    store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
    if await store.get(workspace_id) is None:
        await store.create(creator_user_id="test", name=workspace_id, workspace_id=workspace_id)


__all__ = ["POSTGRES_DSN_ENV", "postgres_dsn", "provision_workspace"]
