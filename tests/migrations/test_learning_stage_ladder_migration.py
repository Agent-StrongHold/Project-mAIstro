"""Migration 048 lands the knowledge-stage ladder, and un-lands it (M4-B1/ADR-103).

The upgrade/downgrade round trip against a real PostgreSQL — the same shape
migration 031's landing demanded for the episodic provenance columns: a
downgrade that leaves half its change behind hands the next migration a
schema nobody has tested. Skips without a server, for the reason
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

_STAGE_COLUMNS = ("stage", "validated_by", "promoted_by")


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


def _learning_stage_columns() -> dict[str, str | None]:
    """The stage columns the live catalog holds, and their defaults."""
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            """
            select column_name, column_default
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'learnings'
              and column_name = any(%s)
            """,
            (list(_STAGE_COLUMNS),),
        )
        return {row[0]: row[1] for row in cur.fetchall()}


def _ledger_table() -> str | None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("select to_regclass('public.learning_stage_transitions')")
        row = cur.fetchone()
        return str(row[0]) if row and row[0] else None


def test_upgrade_lands_the_stage_columns_and_the_ledger() -> None:
    result = _alembic("upgrade", "048")
    assert result.returncode == 0, result.stderr

    columns = _learning_stage_columns()
    assert set(columns) == set(_STAGE_COLUMNS)
    # NOT NULL with honest defaults: a pre-ladder row is `memory` with no
    # fabricated validation or promotion actor.
    assert columns["stage"] == "'memory'::text"
    assert columns["validated_by"] == "''::text"
    assert columns["promoted_by"] == "''::text"
    assert _ledger_table() == "learning_stage_transitions"


def test_downgrade_unlands_the_whole_ladder() -> None:
    _alembic("upgrade", "048")
    result = _alembic("downgrade", "047")
    assert result.returncode == 0, result.stderr

    assert _learning_stage_columns() == {}
    assert _ledger_table() is None


def test_re_upgrading_over_a_downgraded_schema_restores_the_ladder() -> None:
    _alembic("downgrade", "047")
    result = _alembic("upgrade", "048")
    assert result.returncode == 0, result.stderr
    assert set(_learning_stage_columns()) == set(_STAGE_COLUMNS)
    assert _ledger_table() is not None
