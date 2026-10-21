"""Downgrading 064 must leave every receipt readable by the 063 runtime.

Revision-063's ``InvocationStatus`` has no ``UNKNOWN`` member: its row
decoder calls ``InvocationStatus(row['status'])`` and raises ``ValueError``
on any leftover ``'unknown'`` receipt, so a rolled-back deployment could
neither read nor claim those rows — the store would crash on first touch
rather than degrade. The 064 downgrade therefore reclassifies ``unknown``
receipts to 063-era terminal ``failed`` (the previous release's own outcome
for ambiguous transports: never re-dispatched by a runtime that cannot
represent uncertainty) and tags ``last_error`` for operators via the
``unknown_receipt_downgraded`` placeholder when the row carries no error
text yet.

The reclassification is data, not DDL, so the offline ``--sql`` render of
the schema-agreement suite cannot see it. These tests walk the real chain
against a real server:

* **Decode safety** — after ``downgrade 063`` every ``handler_invocations``
  status is a member of the 063-era status set. That set is spelled out
  rather than imported: the live enum gained ``unknown`` on this branch, so
  the regression this test names (an ``'unknown'`` surviving the downgrade)
  would decode fine against today's model and pass vacuously.
* **Round trip** — re-applying 064 re-derives the downgraded rows
  fail-closed: back to ``unknown`` through the ``legacy_failed_unproven``
  upgrade path (whose ``last_error_code = ''`` guard matches the column
  default the downgrade reinstates), with ``uncertain_prior_dispatch``
  from the preserved attempt count, the delivery key still ``NULL`` (a
  downgrade never reinvents one), and historical SUCCESS / unattempted
  pending rows untouched.

The PostgreSQL legs need a real server and skip without one
(``MAISTRO_TEST_DATABASE_URL``); CI's ``coverage (PostgreSQL)`` job owns a
migrated service for ``tests/migrations``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DATABASE_URL = os.environ.get("MAISTRO_TEST_DATABASE_URL", "")

#: The 063-era ``InvocationStatus`` values (the chain one revision back).
#: ``unknown`` joined the model with 064 itself, so a receipt still sitting
#: on ``'unknown'`` after the downgrade is exactly the crash this file
#: exists to prevent. Importing the live enum would invert the assertion.
LEGACY_063_STATUSES = frozenset({"pending", "success", "failed", "retrying"})

PG_MARK = pytest.mark.skipif(
    not DATABASE_URL,
    reason="MAISTRO_TEST_DATABASE_URL is unset; walking the chain needs a real server",
)


def _alembic_env() -> dict[str, str]:
    """alembic/env.py resolves one URL through `require_database_url`."""
    return {**os.environ, "DATABASE_URL": DATABASE_URL}


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=_alembic_env(),
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )


def _query(sql: str) -> list[tuple[object, ...]]:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return list(cur.fetchall())


def _execute(sql: str) -> None:
    import psycopg

    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(sql)


def _columns(table: str) -> set[str]:
    return {
        str(row[0])
        for row in _query(
            "select column_name from information_schema.columns "
            f"where table_schema = 'public' and table_name = '{table}'"
        )
    }


def _receipts() -> dict[int, tuple[object, ...]]:
    """(status, attempts, last_error) by event — columns both schemas have."""
    rows = _query(
        "select event_id, status, attempts, last_error from handler_invocations order by event_id"
    )
    return {int(row[0]): row[1:] for row in rows}


def _receipt_extensions() -> dict[int, tuple[object, ...]]:
    """(delivery_key, uncertain_prior_dispatch, last_error_code) by event."""
    rows = _query(
        "select event_id, delivery_key, uncertain_prior_dispatch, last_error_code "
        "from handler_invocations order by event_id"
    )
    return {int(row[0]): row[1:] for row in rows}


@pytest.fixture
def chain_database():
    """064 applied, seeded with the boundary rows, restored after each test.

    Mirrors ``test_goal_installed_base_upgrade.empty_database``: one failing
    test cannot cascade, and the shared CI service is left where the next
    module expects it. Seeding is raw SQL at 064 exactly as the receipts the
    protocol writes would look — including one row whose ``unknown`` came
    from the legacy upgrade (no error text yet) to exercise the tag.
    """
    assert _alembic("downgrade", "base").returncode == 0
    _drop_public_tables()
    assert _alembic("upgrade", "066").returncode == 0
    _execute(
        """
        INSERT INTO handler_invocations
          (trigger_id, event_id, status, attempts, last_error, created_at,
           lease_expires_at, delivery_key, uncertain_prior_dispatch, last_error_code)
        VALUES
          -- protocol-written unknown receipt: transport loss after a send
          ('t', 1, 'unknown', 3, 'connection lost', 1.0, 0, 'key1', TRUE, 'some_refusal'),
          -- unknown receipt with no error text yet: the tag must appear
          ('t', 2, 'unknown', 1, '', 1.0, 0, 'key2', TRUE, 'legacy_unkeyed_attempt'),
          -- historical settled acknowledgment: must survive both directions
          ('t', 3, 'success', 1, '', 1.0, 0, 'key3', FALSE, ''),
          -- truly unattempted pending row: must survive both directions
          ('t', 4, 'pending', 0, '', 1.0, 0, NULL, FALSE, '')
        """
    )
    yield
    assert _alembic("downgrade", "base").returncode == 0
    _drop_public_tables()
    assert _alembic("upgrade", "head").returncode == 0


def _drop_public_tables() -> None:
    for (name,) in _query("select tablename from pg_tables where schemaname = 'public'"):
        quoted = str(name).replace('"', '""')
        _execute(f'drop table if exists "{quoted}" cascade')


@PG_MARK
class TestDowngrade064LeavesReadableReceipts:
    def test_unknown_receipts_reclassify_to_legacy_terminal_failed(
        self, chain_database: None
    ) -> None:
        assert _alembic("downgrade", "063").returncode == 0
        receipts = _receipts()
        assert set(receipts) == {1, 2, 3, 4}, "rows must survive the downgrade"

        # The regression this file names: every surviving status is one the
        # 063 runtime can decode. Before the reclassification landed, rows 1
        # and 2 stayed 'unknown' and InvocationStatus(row['status']) raised.
        for event_id, (status, *_rest) in receipts.items():
            assert status in LEGACY_063_STATUSES, (
                f"row {event_id}: {status!r} is not decodable by the 063 runtime"
            )

        # Unknown becomes 063's terminal failed: never re-dispatched by a
        # runtime that cannot represent uncertainty.
        assert receipts[1][0] == "failed"
        assert receipts[2][0] == "failed"
        # Operator evidence: existing error text is kept, empty text gets the
        # placeholder — a downgrade never fabricates a different error story.
        assert receipts[1][2] == "connection lost"
        assert receipts[2][2] == "unknown_receipt_downgraded"
        # Attempt counts are cumulative evidence and are never reset.
        assert receipts[1][1] == 3
        assert receipts[2][1] == 1

        # The receipt columns are gone with the revision that added them.
        columns = _columns("handler_invocations")
        for dropped in (
            "delivery_key",
            "handler_url",
            "request_digest",
            "replay_safety",
            "contract_ref",
            "claim_token",
            "revision",
            "dispatch_started_at",
            "last_outcome",
            "uncertain_prior_dispatch",
            "last_error_code",
        ):
            assert dropped not in columns, f"{dropped} survived the downgrade"

    def test_reupgrade_rederives_unknown_fail_closed(self, chain_database: None) -> None:
        assert _alembic("downgrade", "063").returncode == 0
        assert _alembic("upgrade", "066").returncode == 0
        receipts = _receipts()
        extensions = _receipt_extensions()

        # Round trip: the downgraded unknowns re-derive fail-closed through
        # the legacy_failed_unproven upgrade path — uncertainty from the
        # preserved attempt count, error text untouched, no key reinvented.
        for event_id in (1, 2):
            status, attempts, _ = receipts[event_id]
            delivery_key, uncertain, code = extensions[event_id]
            assert status == "unknown", f"row {event_id}: {status}"
            assert uncertain is True, f"row {event_id} lost its uncertainty"
            assert attempts == (3 if event_id == 1 else 1)
            assert delivery_key is None, f"row {event_id}: a key was reinvented"
            assert code == "legacy_failed_unproven", f"row {event_id}: {code}"
        assert receipts[1][2] == "connection lost"
        assert receipts[2][2] == "unknown_receipt_downgraded"

        # Historical acknowledgment and the unattempted row are untouched.
        assert receipts[3][0] == "success" and extensions[3][1] is False
        assert receipts[4][0] == "pending" and extensions[4][1] is False
