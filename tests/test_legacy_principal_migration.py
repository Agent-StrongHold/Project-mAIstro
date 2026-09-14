"""Contract checks for the transactional legacy-principal migration (#1095)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "036_legacy_principal_ownership.py"


@pytest.fixture
def migration(monkeypatch: pytest.MonkeyPatch):
    spec = importlib.util.spec_from_file_location("legacy_principal_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    statements: list[str] = []
    monkeypatch.setattr(module.op, "execute", lambda statement: statements.append(str(statement)))
    monkeypatch.setattr(module.op, "drop_table", lambda name: statements.append(str(name)))
    return module, statements


def test_upgrade_emits_one_restart_safe_identity_mapping_and_ownership_plan(migration) -> None:
    module, statements = migration

    module.upgrade()
    sql = "\n".join(statements)

    assert module.revision == "036"
    assert module.down_revision == ("035", "035_outcome_scope_thumb_index")
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


def test_downgrade_does_not_guess_at_post_migration_ownership(migration) -> None:
    module, statements = migration

    module.downgrade()

    assert statements == ["principal_identity_mappings"]
