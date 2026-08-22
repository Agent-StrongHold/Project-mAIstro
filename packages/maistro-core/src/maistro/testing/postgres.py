"""Locating a real PostgreSQL for the conformance suites.

Lives in `maistro.testing` rather than a conftest because three suites need it —
persistence (#122), the execution spine (#132), and the container wiring — and
they sit in sibling test directories that cannot import each other's conftest.
A helper duplicated per directory would be several definitions of "is there a
database", which is the drift the conformance suites exist to catch.
"""

from __future__ import annotations

import os

#: Environment variable naming a *migrated* PostgreSQL to test against. CI runs
#: a `postgres` service and `alembic upgrade head` before pytest; unset locally,
#: the PostgreSQL cases of each backend-parametrized suite skip.
POSTGRES_DSN_ENV = "MAISTRO_TEST_PG_DSN"


def postgres_dsn() -> str:
    """The configured DSN, or ``""`` when no server is available."""
    return os.getenv(POSTGRES_DSN_ENV, "").strip()


__all__ = ["POSTGRES_DSN_ENV", "postgres_dsn"]
