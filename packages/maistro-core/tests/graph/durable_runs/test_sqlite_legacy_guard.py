"""Regression tests for the canonical durable SQLite upgrade boundary."""

from __future__ import annotations

import sqlite3

import pytest

from maistro.graph.durable_runs import SqliteDurableRunStore


def _create_legacy_table(db_path, *, with_row: bool) -> None:
    """Create the minimum pre-canonical table shape needed by the upgrade guard."""
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE durable_runs (run_id TEXT PRIMARY KEY)")
        if with_row:
            conn.execute("INSERT INTO durable_runs(run_id) VALUES ('legacy-run')")
        conn.commit()


def test_sqlite_store_refuses_to_hide_unmigrated_legacy_rows(tmp_path) -> None:
    """Reject legacy persisted runs rather than silently replacing their table."""
    db_path = tmp_path / "durable.db"
    _create_legacy_table(db_path, with_row=True)

    with pytest.raises(RuntimeError, match="workspace_id"):
        SqliteDurableRunStore(db_path)

    with sqlite3.connect(db_path) as conn:
        legacy_count = conn.execute("SELECT COUNT(*) FROM durable_runs").fetchone()[0]
        canonical_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='durable_graph_runs'"
        ).fetchone()
    assert legacy_count == 1
    assert canonical_table is None


def test_sqlite_store_allows_empty_legacy_table(tmp_path) -> None:
    """Allow a database with no persisted legacy runs to adopt the canonical table."""
    db_path = tmp_path / "durable.db"
    _create_legacy_table(db_path, with_row=False)

    SqliteDurableRunStore(db_path)

    with sqlite3.connect(db_path) as conn:
        canonical_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='durable_graph_runs'"
        ).fetchone()
    assert canonical_table is not None
