"""PostgreSQL access for the persistence conformance suite.

The `pg_pool` fixture lives in the package-level conftest, because the
execution-spine suite (#132) needs the same one and pytest fixtures do not cross
sibling directories. The DSN helper lives in `maistro.testing.postgres` for the
same reason one level up: conftest modules cannot import each other.
"""

from __future__ import annotations

import pytest

from maistro.testing.postgres import postgres_dsn

requires_postgres = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)

__all__ = ["postgres_dsn", "requires_postgres"]
