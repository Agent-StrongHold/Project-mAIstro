"""Migration 031 lands the episodic producer columns, and un-lands them (#64).

The upgrade/downgrade round trip against a real PostgreSQL, the same shape
migration 026's landing demanded for the learnings/outcomes/design_outputs
provenance: a downgrade that leaves half its change behind hands the next
migration a schema nobody has tested. Skips without a server, for the reason
`test_migration_chain.py` states — but the skip is exactly what let the
original chain bug survive, which is why CI's `postgres` job is what matters.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; these need a real PostgreSQL server",
)

_COLUMNS = ("run_id", "node_run_id", "attempt_id")


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": DATABASE_URL},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _columns() -> dict[str, bool]:
    """Every episodic producer column the live catalog holds, and its nullability.

    Read from `information_schema`, not from the migration source: what a
    later migration or a hand-run ALTER did to the table is a fact about the
    catalog alone.
    """
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select column_name, is_nullable
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'episodic_memories'
              and column_name = any(%s)
            """,
            (list(_COLUMNS),),
        )
        return {str(name): nullable == "YES" for name, nullable in cur.fetchall()}


def _index_exists() -> bool:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select 1 from pg_indexes
            where schemaname = 'public'
              and tablename = 'episodic_memories'
              and indexname = 'idx_episodic_memories_run_id'
            """
        )
        return cur.fetchone() is not None


@pytest.fixture
def at_030():
    """Start from 030 — the shape immediately before this change — and return
    there, so one failure cannot cascade into the next test."""
    _alembic("upgrade", "030")
    yield
    _alembic("upgrade", "head")


class TestTheProducerColumnsLand:
    """SPEC-090226-e4a1's prose preservation property: the migration half.

    Deliberately not `@pytest.mark.ac`-marked — the spec states why: a
    migration is a history file, not a module the reachability graph knows, so
    the criterion could never honestly reach the `reachable` rung. These still
    run in CI's migration suite and are listed in the spec's `tests:`.
    """

    def test_upgrade_adds_three_nullable_columns_and_the_index(self, at_030) -> None:
        assert _alembic("upgrade", "head").returncode == 0
        assert set(_columns()) == set(_COLUMNS)
        # Nullable, and deliberately: `NOT NULL DEFAULT ''` would make every
        # pre-031 row claim a Run whose id is the empty string — the over-claim
        # migration 026 refused for the other record kinds.
        assert all(_columns().values())
        assert _index_exists()

    def test_downgrade_to_030_removes_them(self, at_030) -> None:
        _alembic("upgrade", "head")
        result = _alembic("downgrade", "030")
        assert result.returncode == 0, result.stderr
        assert _columns() == {}
        assert not _index_exists()
