"""Migration conformance tests for audit organization scope (#1155)."""

from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "036_audit_log_org_scope.py"


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("audit_scope_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Result:
    def __init__(self, rowcount: int) -> None:
        self.rowcount = rowcount


class _Connection:
    def __init__(self, rowcounts: list[int]) -> None:
        self.rowcounts = iter(rowcounts)
        self.calls: list[tuple[Any, dict[str, int]]] = []

    def execute(self, statement: Any, params: dict[str, int]) -> _Result:
        self.calls.append((statement, params))
        return _Result(next(self.rowcounts))


class _Context:
    def __init__(self) -> None:
        self.autocommit_blocks = 0

    @contextmanager
    def autocommit_block(self):
        self.autocommit_blocks += 1
        yield


class _Operations:
    def __init__(self, connection: _Connection) -> None:
        self.connection = connection
        self.context = _Context()
        self.added: list[tuple[str, Any]] = []
        self.created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.dropped: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def add_column(self, table: str, column: Any) -> None:
        self.added.append((table, column))

    def get_bind(self) -> _Connection:
        return self.connection

    def get_context(self) -> _Context:
        return self.context

    def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.created.append((args, kwargs))

    def drop_index(self, *args: Any, **kwargs: Any) -> None:
        self.dropped.append((args, kwargs))

    def drop_column(self, *args: Any, **kwargs: Any) -> None:
        return None


def test_audit_scope_migration_is_the_single_head() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    directory = ScriptDirectory.from_config(config)

    revision = directory.get_revision("036_audit_log_org_scope")
    # 036 already existed on the historical 035 branch when the consumer and
    # task migrations landed, and develop's chain kept growing while this
    # branch was open (039 for #1531, then 040 for #1079, each taking the
<<<<<<< HEAD
    # parent this revision had claimed). Merging that state into the #1057
    # branch — which had already taken 040's child slot with
    # ``041_task_identity_provenance`` — forked the chain again, so it now
    # follows that branch's chain tip (042_task_receipt_dispatch_inputs, the
    # tip of 035 -> ... -> 040 -> 041_task_identity_provenance ->
    # 042_task_receipt_dispatch_inputs) so every deployment's ordinary
    # ``upgrade head`` applies the audit scope migration rather than leaving
    # it on a competing branch.
    assert revision.down_revision == "042_task_receipt_dispatch_inputs"
    assert directory.get_heads() == ["036_audit_log_org_scope"]
    walked = {item.revision for item in directory.walk_revisions("base", revision.revision)}
=======
    # parent this revision had claimed). It therefore follows the current
    # develop chain tip (040, the tip of 035 -> ... -> 038 -> 039 -> 040) so
    # every deployment's ordinary ``upgrade head`` applies the audit scope
    # migration rather than leaving it on a competing branch.
    assert revision.down_revision == "040"
    # #1120's manual-fire occurrence migration (042) re-parented onto this
    # revision when the develop chain grew again while that branch was open —
    # the same extension this revision's own docstring records for itself.
    # The contract under test is not that the audit migration IS the tip
    # (any later migration on any open branch would break that); it is that
    # a plain ``upgrade head`` still applies it: exactly one head, with the
    # audit scope migration on that head's chain.
    heads = directory.get_heads()
    assert len(heads) == 1
    walked = {item.revision for item in directory.walk_revisions("base", heads[0])}
>>>>>>> b906cc577fbb209d949d94606671c51ac57d4b2b
    assert revision.revision in walked


def test_backfill_is_bounded_and_stops_after_the_last_batch(migration: ModuleType) -> None:
    connection = _Connection([2, 1, 0])

    migration._backfill_org_scope(connection, batch_size=2)

    assert len(connection.calls) == 3
    statement = str(connection.calls[0][0])
    assert "WHERE org_id IS NULL" in statement
    assert "LIMIT :batch_size" in statement
    assert all(call[1] == {"batch_size": 2} for call in connection.calls)


def test_upgrade_and_downgrade_build_scope_index_concurrently(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = _Operations(_Connection([0]))
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    table, column = operations.added[0]
    assert table == "audit_log"
    assert column.name == "org_id"
    assert column.nullable is True
    assert str(column.server_default.arg) == "''"
    assert operations.context.autocommit_blocks == 1
    assert operations.created == [
        (
            ("ix_audit_log_scope", "audit_log", ["org_id", "timestamp"]),
            {"postgresql_concurrently": True},
        )
    ]

    migration.downgrade()

    assert operations.context.autocommit_blocks == 2
    assert operations.dropped == [
        (("ix_audit_log_scope",), {"table_name": "audit_log", "postgresql_concurrently": True})
    ]
