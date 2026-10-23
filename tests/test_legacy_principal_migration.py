"""Contract checks for the transactional legacy-principal migration (#1095)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "064_legacy_principal_ownership.py"


@pytest.fixture
def migration(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("legacy_principal_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", lambda statement: statements.append(str(statement)))
    monkeypatch.setattr(module.op, "drop_table", lambda name: statements.append(str(name)))

    # The statement-key re-key step is row-level work through a real bind; the
    # contract here only checks the emitted plan, so an empty table (no rows to
    # re-key) keeps the pass through upgrade() on the same footing.
    class _Result:
        def fetchall(self) -> list[tuple]:
            return []

        def scalar(self) -> None:
            return None

    class _Bind:
        def execute(self, statement: object, params: object = None) -> _Result:
            statements.append(str(statement))
            return _Result()

    monkeypatch.setattr(module.op, "get_bind", lambda: _Bind())
    return module, statements


def test_upgrade_emits_one_restart_safe_identity_mapping_and_ownership_plan(migration) -> None:
    module, statements = migration

    module.upgrade()
    sql = "\n".join(statements)

    assert module.revision == "064"
    assert module.down_revision == "063"
    assert "principal_identity_mappings" in sql
    assert "ON CONFLICT (legacy_principal) DO UPDATE" in sql
    assert "ON CONFLICT (workspace_id, user_id) DO UPDATE" in sql
    assert "ON CONFLICT (project_id, principal_id) DO UPDATE" in sql
    assert "ON CONFLICT (user_id) DO UPDATE" in sql
    assert "principal:default" in sql
    assert "canonical_workspace_memberships" in sql
    assert "canonical_project_memberships" in sql
    assert "canonical_runs" in sql
    assert "canonical_event_log" in sql
    assert "security_violations" in sql
    # The owner-bound statement digests are recomputed under the canonical
    # owner and merged, not left hashed from `default`.
    assert "DISTINCT ON (k.fact_key)" in sql
    assert "user_model_statement_keys" in sql
    assert "user_model_facts" in sql


def test_downgrade_does_not_guess_at_post_migration_ownership(migration) -> None:
    module, statements = migration

    module.downgrade()

    assert statements == ["principal_identity_mappings"]
