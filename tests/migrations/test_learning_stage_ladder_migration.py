"""Migration 053 lands the knowledge-stage ladder's provenance, and un-lands it.

Numbered 048 when written; develop's #398 claimed that id, and develop's own
#780/#774 then took 049/050, so the revision re-parented onto that chain —
and develop's #792 eval evidence re-parented onto the same `050` as 051,
making it the chain tip, so the ladder first landed one rung higher
(`052_learning_stage_ladder`, `down_revision = "051"`). The merge that
graduated the M4-B ladder (ADR-103) onto the implemented M4-B lifecycle
(ADR-100126-9a4b) brought both branches' 052 revisions onto the same parent,
so the ladder re-parented once more: `053_learning_stage_ladder` — the same
renumbering every develop collision in this chain has gone through.

In the merged chain `052_learning_lifecycle_columns` already owns
`stage` (default `learning` — rows enter the ladder at the extracted-claim
rung) and `validated_by`; this revision adds `promoted_by` and the
append-only `learning_stage_transitions` ledger, so its downgrade un-lands
only what it owns.

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

#: What this revision alone owns: `promoted_by` and the ledger. `stage` and
#: `validated_by` belong to 052 and survive this revision's downgrade.
_OWNED_AFTER_DOWNGRADE = {
    "stage": "'learning'::text",
    "validated_by": "''::text",
}


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
    result = _alembic("upgrade", "053")
    assert result.returncode == 0, result.stderr

    columns = _learning_stage_columns()
    assert set(columns) == set(_STAGE_COLUMNS)
    # NOT NULL with honest defaults: rows enter the ladder at `learning`
    # (extraction is the MEMORY -> LEARNING step) with no fabricated
    # validation or promotion actor.
    assert columns["stage"] == "'learning'::text"
    assert columns["validated_by"] == "''::text"
    assert columns["promoted_by"] == "''::text"
    assert _ledger_table() == "learning_stage_transitions"


def test_downgrade_unlands_only_what_this_revision_owns() -> None:
    _alembic("upgrade", "053")
    result = _alembic("downgrade", "052")
    assert result.returncode == 0, result.stderr

    # `promoted_by` and the ledger go; `stage`/`validated_by` stay — 052
    # owns them, and a downgrade must not strip a lower revision's columns.
    assert _learning_stage_columns() == _OWNED_AFTER_DOWNGRADE
    assert _ledger_table() is None


def test_re_upgrading_over_a_downgraded_schema_restores_the_ladder() -> None:
    _alembic("downgrade", "052")
    result = _alembic("upgrade", "053")
    assert result.returncode == 0, result.stderr
    assert set(_learning_stage_columns()) == set(_STAGE_COLUMNS)
    assert _ledger_table() is not None
