"""Audit migration DDL contract, runnable without a PostgreSQL service (#358)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_audit_revision_only_changes_its_eight_ordered_scope_indexes(
    direction: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = Path(__file__).resolve().parents[2] / "alembic/versions/059_audit_cursor_indexes.py"
    spec = importlib.util.spec_from_file_location("audit_cursor_indexes", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements: list[str] = []
    monkeypatch.setattr(migration.op, "execute", statements.append)

    assert migration.revision == "059"
    assert migration.down_revision == "058"
    getattr(migration, direction)()

    if direction == "upgrade":
        # Each equality-filter subset must retain scope and stable tie ordering.
        # Pin independently of the migration's generated index definitions.
        filters = (
            "",
            "user_id, ",
            "boundary, ",
            "(verdict = 'denied'), ",
            "user_id, boundary, ",
            "user_id, (verdict = 'denied'), ",
            "boundary, (verdict = 'denied'), ",
            "user_id, boundary, (verdict = 'denied'), ",
        )
        assert statements == [
            f"CREATE INDEX IF NOT EXISTS ix_audit_page_{index} ON audit_log "
            f"(org_id, {fields}timestamp DESC, id DESC)"
            for index, fields in enumerate(filters)
        ]
    else:
        # In particular do not undo develop's preceding Run-store indexes.
        assert statements == [
            f"DROP INDEX IF EXISTS ix_audit_page_{index}" for index in reversed(range(8))
        ]
