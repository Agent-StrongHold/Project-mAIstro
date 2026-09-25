"""Migration 041: canonical Goals and their revisions (#1572).

The PostgreSQL round trip is `test_migration_chain.py`'s, against a real
server. This runs the same `upgrade()`/`downgrade()` on SQLite, so the
constraints the Goal stores lean on -- the same-Project parent key above all --
are exercised on every run, not only where a server exists.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "041_goals.py"


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("goals_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _foreign_keys(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
    dbapi_connection.execute("PRAGMA foreign_keys = ON")


@pytest.fixture
def engine(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")

    sa.event.listen(engine, "connect", _foreign_keys)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE canonical_projects (project_id TEXT PRIMARY KEY, workspace_id TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO canonical_projects VALUES ('p1', 'w'), ('p2', 'w')")
    yield engine
    engine.dispose()


def _run(migration: ModuleType, engine, step: str, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        getattr(migration, step)()


def _goal(conn, goal_id: str, project_id: str, parent: str | None = None) -> None:  # type: ignore[no-untyped-def]
    conn.exec_driver_sql(
        "INSERT INTO goals VALUES (?, 'w', ?, ?, 'agent', 'active', 1, "
        "'2026-09-25T00:00:00+00:00', '2026-09-25T00:00:00+00:00')",
        (goal_id, project_id, parent),
    )


def test_041_is_the_single_head_after_the_audit_scope_migration(migration) -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    directory = ScriptDirectory.from_config(config)

    assert migration.down_revision == "036_audit_log_org_scope"
    assert directory.get_heads() == [migration.revision]


def test_upgrade_enforces_the_goal_rules_and_downgrade_removes_them(
    migration, engine, monkeypatch
) -> None:
    _run(migration, engine, "upgrade", monkeypatch)

    assert {"goals", "goal_revisions"} <= set(sa.inspect(engine).get_table_names())
    with engine.begin() as conn:
        _goal(conn, "g1", "p1")
        _goal(conn, "g2", "p1", parent="g1")
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        _goal(conn, "g3", "p2", parent="g1")
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("UPDATE goals SET state = 'paused' WHERE goal_id = 'g1'")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO goal_revisions VALUES ('g1', 1, 'agent', 'd', '[]', '[]', 'u', "
            "'2026-09-25T00:00:00+00:00')"
        )
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO goal_revisions VALUES ('g1', 1, 'agent', 'd', '[]', '[]', 'u', "
            "'2026-09-25T00:00:00+00:00')"
        )
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM canonical_projects WHERE project_id = 'p1'")
    with engine.begin() as conn:
        conn.exec_driver_sql("DELETE FROM goals WHERE goal_id = 'g1'")
        remaining = conn.exec_driver_sql("SELECT count(*) FROM goals").scalar()
        revisions = conn.exec_driver_sql("SELECT count(*) FROM goal_revisions").scalar()
        conn.exec_driver_sql("DELETE FROM canonical_projects WHERE project_id = 'p1'")
    # The Subgoal and the revision went with their parent Goal.
    assert (remaining, revisions) == (0, 0)

    _run(migration, engine, "downgrade", monkeypatch)

    assert not {"goals", "goal_revisions"} & set(sa.inspect(engine).get_table_names())
