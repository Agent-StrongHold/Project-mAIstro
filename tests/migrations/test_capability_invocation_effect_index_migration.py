"""Migration conformance tests for the capability Invocation effect index (#1194).

Revision 042 recreates ``idx_capability_invocation_effect`` without
``node_run_id`` so the PostgreSQL ledger matches the SQLite twin: the
logical-effect lookup (``node_run_id=None`` — one history per Run across
every physical NodeRun) and the physical-visit lookup must both be served
by one index in both durable backends of the replay contract.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "042_capability_invocation_effect_index.py"


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invocation_effect_index_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Operations:
    def __init__(self) -> None:
        self.created: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        self.dropped: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def create_index(self, *args: Any, **kwargs: Any) -> None:
        self.created.append((args, kwargs))

    def drop_index(self, *args: Any, **kwargs: Any) -> None:
        self.dropped.append((args, kwargs))


def test_effect_index_migration_follows_the_chain_tip() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    directory = ScriptDirectory.from_config(config)

    revision = directory.get_revision("042")
    assert revision.down_revision == "036_audit_log_org_scope"
    assert directory.get_heads() == ["042"]


def test_upgrade_and_downgrade_swap_the_index_shape(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = _Operations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    # Drop first: the pre-#1194 shape led with node_run_id, so the
    # logical-effect lookup could not use it past the run_id prefix.
    assert operations.dropped == [
        (("idx_capability_invocation_effect",), {"table_name": "capability_invocations"})
    ]
    assert operations.created == [
        (
            (
                "idx_capability_invocation_effect",
                "capability_invocations",
                ["run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
            ),
            {},
        )
    ]

    migration.downgrade()

    # The downgrade restores the historical shape exactly: a deployment that
    # must roll back keeps the index it was migrated from.
    assert operations.created[-1] == (
        (
            "idx_capability_invocation_effect",
            "capability_invocations",
            ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
        ),
        {},
    )
