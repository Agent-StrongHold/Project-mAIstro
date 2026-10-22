"""Migration 048 lands applicability, confidence, evidence and epistemic type.

Two contracts, both driven against a real PostgreSQL because both failed CI at
the change that introduced them (observed 2026-10-03):

- a bare ``op.add_column`` ``server_default`` string is rendered as a quoted
  literal — ``DEFAULT '''[]''::jsonb'`` — which the server refuses as JSON, so
  the first ``alembic upgrade head`` of a clean install died inside
  ``ALTER TABLE`` (formal-conformance's ``invalid input syntax for type json``,
  Gate C's ``maistro-engine is unhealthy``, docker-build's pg18 boot);
- a bare ``ADD COLUMN`` is not adoption-safe: the stamp-back + re-upgrade
  repair path (test_migration_chain's adoption contract, #1194's 045)
  re-walks 044..head over an existing schema, where ``DuplicateColumn`` is a
  failure even though the schema is already the one the migration builds.

Skips without a server, for the reason ``test_migration_chain.py`` states —
but the skip is exactly what let the original bugs survive, which is why CI's
postgres job is what matters.
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


def _query(sql: str) -> list[tuple]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


#: The 047-shape `learnings` row the upgrade path starts from: the columns
#: 048 adds do not exist yet, and the insert names only what the table required
#: before 048 (`tool_name` is NOT NULL with no default; `created_at` defaults).
_LEGACY_ROW = """
insert into learnings
    (trigger_keys, learning, tool_name, org_id, run_id)
values
    ('["deploy"]', 'canary before promote', 'bash', 'org-legacy', 'run-producer')
"""


def _seed_legacy_row() -> None:
    """Remove any prior row this suite seeded, then insert a fresh one."""
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("delete from learnings where org_id = 'org-legacy'")
        cur.execute(_LEGACY_ROW)
        conn.commit()


def _flag_row() -> None:
    """Mark the seeded row tested-and-measured, so a re-run default that
    rewrote it would be visible instead of silent."""
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(
            "update learnings set epistemic_type = 'tested', confidence = 0.75 "
            "where org_id = 'org-legacy'"
        )
        conn.commit()


@pytest.fixture
def at_047():
    """Start from 047 — the shape immediately before this change — and return
    there, so one failure cannot cascade into the next test."""
    assert _alembic("upgrade", "047").returncode == 0
    yield
    assert _alembic("upgrade", "head").returncode == 0


class TestTheEpistemicColumnsLand:
    def test_a_legacy_row_reads_empirical_with_empty_applicability_and_no_confidence(
        self, at_047
    ) -> None:
        """The honest reading of a pre-M4-B row, not fabricated evidence.

        `confidence` arrives NULL — "never measured" is a promotion blocker,
        while a 0.0 default would read as measured-and-failing and a 1.0 as
        measured-and-perfect (the rule ADR-083026-a91e set for metrics). The
        defaulted columns backfill, so the NOT NULL add succeeds on a
        populated table. The epistemic default is `empirical`, the reconciled
        pipeline-epistemics reading (ADR-100126-8c2d) that `054` landed: a
        captured tool correction is empirical-by-construction.
        """
        assert _alembic("upgrade", "head").returncode == 0

        _seed_legacy_row()
        assert _alembic("upgrade", "head").returncode == 0
        rows = _query(
            "select epistemic_type, works_when, avoid_in, confidence, "
            "evidence_run_ids, evaluation_ids from learnings "
            "where org_id = 'org-legacy'"
        )
        assert rows == [
            ("empirical", [], [], None, [], []),
        ]

    def test_the_reapplied_chain_is_adopted_with_a_pre_existing_row(self, at_047) -> None:
        """Stamp-back + re-upgrade over an existing schema must not raise.

        The DDL is `ADD COLUMN IF NOT EXISTS` for the same reason migration
        025's is: the adoption path re-walks 044..head over a schema that
        already holds these columns, and a bare ADD COLUMN answers
        DuplicateColumn. A row that predates the re-application must survive
        with its values rather than being rewritten by the re-run default.
        """
        assert _alembic("upgrade", "head").returncode == 0

        _seed_legacy_row()
        _flag_row()

        assert _alembic("stamp", "047").returncode == 0
        result = _alembic("upgrade", "head")
        assert result.returncode == 0, result.stderr
        rows = _query(
            "select epistemic_type, confidence, works_when from learnings "
            "where org_id = 'org-legacy'"
        )
        assert rows == [("tested", 0.75, [])]
        counts = _query(
            "select count(*) from information_schema.columns "
            "where table_schema = 'public' and table_name = 'learnings' "
            "and column_name = 'epistemic_type'"
        )
        assert counts == [(1,)]
