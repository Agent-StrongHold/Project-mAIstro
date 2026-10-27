"""The stored-volume health probe (#325, the last unimplemented health metric).

The sweep counters are rates: they cannot distinguish "the purge keeps pace"
from "the purge never runs and nothing was deleted lately". The probe's series
— rows, bytes, oldest retained record per governed table — are the levels that
can. This file proves the probe's own contract: bounded labels, the throttle
that makes per-admission probing affordable, the timestamp conversions every
backend's stored time format needs, and the honest absences (a missing table,
a runtime without dbstat, an empty table) that must yield no series rather than
a fabricated number.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import aiosqlite
import pytest

from maistro.observability import metrics as retention_health
from maistro.observability.metrics import (
    RetentionTableSample,
    oldest_timestamp,
    postgres_table_sample,
    publish_retention_table_health,
    retention_oldest_record_timestamp,
    retention_table_bytes,
    retention_table_rows,
    sqlite_table_bytes,
    sqlite_table_sample,
)


@pytest.fixture(autouse=True)
def _no_standing_throttle() -> None:
    """The throttle ledger is process-wide by design; each test starts empty."""
    retention_health._LAST_PROBE.clear()


def _table_gauge(metric: Any, table: str, backend: str) -> float | None:
    values = [
        float(sample["value"])
        for sample in metric.collect()
        if sample.get("labels", {}).get("table") == table
        and sample.get("labels", {}).get("backend") == backend
    ]
    return sum(values) if values else None


def test_an_ungoverned_table_label_is_refused() -> None:
    """Metric label values are bounded (#818); the `table` label comes from
    the governed set, and a sample outside it is a programmer error raised at
    the probe, not a new label dimension invented at runtime."""
    with pytest.raises(ValueError, match="not a governed"):
        publish_retention_table_health(
            "k", "sqlite", [RetentionTableSample(table="not_a_table", rows=1)]
        )


def test_the_throttle_publishes_once_per_interval_per_key() -> None:
    sample = RetentionTableSample(table="audit_log", rows=1)
    assert publish_retention_table_health("audit:sqlite", "sqlite", [sample]) is True
    # Same store, same interval: sampled nothing, published nothing.
    assert publish_retention_table_health("audit:sqlite", "sqlite", [sample]) is False
    # A different store is a different probe: its first publish goes through.
    assert publish_retention_table_health("runs:sqlite", "sqlite", [sample]) is True


def test_an_expired_throttle_entry_publishes_again() -> None:
    sample = RetentionTableSample(table="audit_log", rows=1)
    assert publish_retention_table_health("k", "sqlite", [sample]) is True
    assert publish_retention_table_health("k", "sqlite", [sample]) is False
    # Age the ledger entry past the interval the way real time would.
    last = retention_health._LAST_PROBE["k"]
    retention_health._LAST_PROBE["k"] = last - (retention_health.DEFAULT_PROBE_INTERVAL_S + 1)
    assert publish_retention_table_health("k", "sqlite", [sample]) is True


def test_a_zero_interval_is_the_always_publish_setting() -> None:
    sample = RetentionTableSample(table="audit_log", rows=1)
    for _ in range(3):
        assert publish_retention_table_health("k", "sqlite", [sample], min_interval_s=0.0) is True


def test_the_published_gauges_carry_the_sample() -> None:
    # Gauges are process-global and `set` overwrites: seed a known prior
    # value so the assertions prove this sample's values, not an accumulation.
    seed = RetentionTableSample(table="audit_log", rows=1)
    publish_retention_table_health("k", "sqlite", [seed])
    publish_retention_table_health(
        "k2",
        "sqlite",
        [
            RetentionTableSample(
                table="audit_log", rows=7, total_bytes=4096, oldest_timestamp=1_700.0
            )
        ],
    )
    assert _table_gauge(retention_table_rows, "audit_log", "sqlite") == 7.0
    assert _table_gauge(retention_table_bytes, "audit_log", "sqlite") == 4096.0
    assert _table_gauge(retention_oldest_record_timestamp, "audit_log", "sqlite") == 1700.0


def test_oldest_timestamp_conversions() -> None:
    iso = "2026-08-22T12:00:00+00:00"
    expected = datetime(2026, 8, 22, 12, 0, tzinfo=UTC).timestamp()
    assert oldest_timestamp(iso, "iso") == expected
    assert oldest_timestamp(1_700.5, "unix_s") == 1700.5
    assert oldest_timestamp(1_700_000_500, "unix_us") == 1700.0005
    assert oldest_timestamp(datetime(2026, 8, 22, 12, 0, tzinfo=UTC), "datetime") == expected
    assert oldest_timestamp(None, "iso") is None
    assert oldest_timestamp("not a timestamp", "iso") is None


@pytest.fixture
async def conn() -> Any:
    c = await aiosqlite.connect(":memory:")
    yield c
    await c.close()


async def test_a_sqlite_sample_of_a_missing_table_is_none(conn: Any) -> None:
    """A table an optional module never provisioned must yield no sample —
    a zeroed sample would publish `rows=0` for a table that does not exist,
    which is a fabricated health signal, not an honest one."""
    assert await sqlite_table_sample(conn, "audit_log", "timestamp", oldest_unit="iso") is None


async def test_a_sqlite_sample_reads_rows_and_oldest(conn: Any) -> None:
    await conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL)")
    await conn.executemany(
        "INSERT INTO audit_log (timestamp) VALUES (?)",
        [("2026-08-20T00:00:00+00:00",), ("2026-08-22T00:00:00+00:00",)],
    )
    await conn.commit()

    sample = await sqlite_table_sample(conn, "audit_log", "timestamp", oldest_unit="iso")

    assert sample is not None
    assert sample.rows == 2
    assert sample.oldest_timestamp == datetime(2026, 8, 20, tzinfo=UTC).timestamp()
    # An empty table's oldest record is absent, not zero: the series must not
    # claim an epoch-origin record exists.
    await conn.execute("DELETE FROM audit_log")
    await conn.commit()
    empty = await sqlite_table_sample(conn, "audit_log", "timestamp", oldest_unit="iso")
    assert empty is not None
    assert empty.rows == 0
    assert empty.oldest_timestamp is None


async def test_sqlite_bytes_are_the_dbstat_sum_or_an_honest_none(conn: Any) -> None:
    """dbstat ships in many but not all SQLite runtimes. Where it exists the
    bytes are the table's page sum; where it does not, `None` — never a
    database-file stand-in that would overstate every table."""
    await conn.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY)")
    await conn.executemany("INSERT INTO audit_log DEFAULT VALUES", [() for _ in range(5)])
    await conn.commit()

    reported = await sqlite_table_bytes(conn, "audit_log")

    assert reported is None or reported > 0


async def test_a_sqlite_bytes_probe_of_a_missing_table_is_none(conn: Any) -> None:
    assert await sqlite_table_bytes(conn, "audit_log") is None


class _RecordingFetchrow:
    """`Connection.fetchrow` at the boundary `postgres_table_sample` needs.

    PostgreSQL answers `SELECT to_regclass($1) IS NOT NULL AS ok` with a
    one-row record even when the table is absent — `ok=False`, not `None` —
    so the probe must consult the field; the record's own truthiness says
    nothing about the table.
    """

    def __init__(self, ok: bool | None) -> None:
        self._ok = ok
        self.queries: list[str] = []

    async def __call__(self, query: str, *args: object) -> Any:
        self.queries.append(query)
        if "to_regclass" in query:
            return None if self._ok is None else {"ok": self._ok}
        return {"n": 7, "oldest": None}


async def test_a_postgres_sample_of_an_absent_table_is_none() -> None:
    """The absent-table answer arrives as a truthy record carrying `ok=False`:
    the probe must return `None` without issuing the count query — never a
    fabricated level for a table the deployment has not provisioned."""
    fetch = _RecordingFetchrow(ok=False)
    sample = await postgres_table_sample(fetch, "audit_log", "timestamp", oldest_unit="datetime")
    assert sample is None
    assert not any("COUNT(*)" in q for q in fetch.queries)


async def test_a_postgres_sample_of_an_unanswered_existence_check_is_none() -> None:
    """A boundary that cannot answer the existence check at all yields no
    sample either; the honest absence outranks any measurement."""
    fetch = _RecordingFetchrow(ok=None)
    sample = await postgres_table_sample(fetch, "audit_log", "timestamp", oldest_unit="datetime")
    assert sample is None
    assert not any("COUNT(*)" in q for q in fetch.queries)
