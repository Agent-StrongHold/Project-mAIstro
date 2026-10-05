"""Migration conformance for the capability Invocation effect claim (#42, #1194).

The deployment schema truth for `capability_invocations` is revision `035`:
the #1194 effect-claim scope corrections were folded into it at the 55be1459
develop sync — the persisted ``effect_scope`` column and the scope-keyed
``uq_capability_invocation_active_effect`` partial unique index — replacing
this branch's earlier standalone revisions. Those earlier revisions are gone
from the chain by recorded resolution
(``auto-42-develop-sync-55be1459-reconciliation``): ``043`` realigned
``idx_capability_invocation_effect`` without ``node_run_id``, but the durable
stores kept the physical-visit lookup index (the logical-effect read is
served through the ``run_id`` prefix), so the reshape was superseded, not
folded; ``045``'s ``logical_effect`` boolean discriminator lost to the
``effect_scope`` design and its DDL exists in no store. Keeping the file (now
asserting the surviving shape) rather than deleting it preserves the offline
half of the guard: ``test_migration_chain.py`` proves the claim schema on a
live PostgreSQL, and the stores' own suites prove the stores against their
own DDL — this is the no-server check that migration 035 and both durable
stores still describe one schema.

The chain history below is the same renumbering chronicle the revisions
themselves carry: 043 followed 042 when written, then re-parented onto
develop's ``039_quota_usage_event_identity`` (#1204), then onto #286's
``044_canvas_store_tables`` (PR #1620); 046 (`#72`), 047 (`#1133`), 048
(`#398`), 049 (`#780`), 050 (`#774`), 051 (#792's eval-score evidence), 052
(develop's knowledge-stage ladder, M4-B1/ADR-103) and 053 (this branch's
learning-lifecycle columns, M4-B) each claimed the tip in turn. Develop's
#1756 learning-applicability migration (M4-B3, #119) then claimed that tip
as ``054_learning_applicability_epistemics``, and #1892's forward
admission-generation representation — numbered ``053`` when written on the
``052`` base, re-parented onto this chain's ``053`` tip at the previous
develop sync — re-numbers to ``055`` on top of it. Develop's #55 effect-path
sync then lands its ``043_invocation_quota_door`` (#1196/#718) on that
``055`` tip, and this sync's #1047 user-model tables — re-parented past
develop's ``054`` and ``055`` as ``056`` in their own two collisions — revise
the quota door, so the single linear head is the user-model revision.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "alembic" / "versions" / "035_capability_invocations.py"
STORES = (
    ROOT / "packages" / "maistro-core" / "src" / "maistro" / "capabilities" / "invocation_store.py",
    ROOT
    / "packages"
    / "maistro-core"
    / "src"
    / "maistro"
    / "capabilities"
    / "pg_invocation_store.py",
)

#: The claim-index columns and predicate every copy of the truth must spell.
CLAIM_COLUMNS = ["run_id", "effect_scope", "binding_id", "effect_key"]
CLAIM_PREDICATE = "WHERE status IN ('created', 'running', 'completed', 'unknown')"
#: The physical-visit lookup index keeps node_run_id: the logical-effect read
#: (``list_effect(node_run_id=None)``) is served through the ``run_id`` prefix,
#: which is why 043's reshape was superseded rather than folded into 035.
LOOKUP_COLUMNS = [
    "run_id",
    "node_run_id",
    "binding_id",
    "effect_key",
    "created_at",
    "invocation_id",
]


@pytest.fixture
def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("invocation_effect_index_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Operations:
    def __init__(self) -> None:
        self.created_indexes: list[tuple[str, str, list[str]]] = []
        self.dropped_indexes: list[tuple[str, str]] = []
        self.executed: list[str] = []
        self.table: Any = None
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *columns: Any) -> None:
        self.table_name = name
        self.columns = list(columns)

    def create_index(self, name: str, table: str, columns: list[str], **_kw: Any) -> None:
        self.created_indexes.append((name, table, list(columns)))

    def drop_index(self, name: str, table_name: str) -> None:
        self.dropped_indexes.append((name, table_name))

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def drop_table(self, name: str, *_columns: Any, **_kw: Any) -> None:
        self.dropped_tables.append(name)


def _normalized(statement: str) -> str:
    return " ".join(statement.split())


def _ddl_string_constants(path: Path, names: tuple[str, ...]) -> dict[str, str]:
    """Read module-level string constants out of a store module without importing it.

    Importing the stores would drag the whole capability stack into a migration
    conformance test; the DDL is a literal assignment, so the AST is the whole
    truth. Finding none of the names fails the caller loudly instead of
    comparing air.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    found: dict[str, str] = {}
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in names
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            found[node.targets[0].id] = node.value.value
    if not found:
        msg = f"{path.name} declares none of the string constant(s) {list(names)}; the comparison would be vacuous"
        raise AssertionError(msg)
    return found


def _store_claim_statements(path: Path) -> list[str]:
    ddl = _ddl_string_constants(path, ("_CLAIM_DDL",))["_CLAIM_DDL"]
    statements = [_normalized(s) for s in ddl.split(";") if s.strip()]
    assert len(statements) == 3, f"{path.name} _CLAIM_DDL is not the backfill/drop/create trio"
    return statements


def _store_table_ddl(path: Path) -> str:
    """The table DDL, under either store's name for it."""
    constants = _ddl_string_constants(path, ("_SCHEMA", "_TABLE_DDL"))
    return next(iter(constants.values()))


def _store_lookup_index_columns(path: Path) -> list[str]:
    schema = _store_table_ddl(path)
    match = re.search(
        r"CREATE INDEX IF NOT EXISTS idx_capability_invocation_effect\s+"
        r"ON capability_invocations\s*\(([^)]*)\)",
        schema,
    )
    assert match, f"{path.name} _SCHEMA declares no idx_capability_invocation_effect"
    return [column.strip() for column in match.group(1).split(",")]


def test_effect_claim_revision_follows_the_chain_tip() -> None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    directory = ScriptDirectory.from_config(config)

    assert directory.get_heads() == ["056"]
    walked = {item.revision for item in directory.walk_revisions("base", "056")}
    # The claim chain this branch folded the #1194 corrections into, and every
    # develop collision the chronicle above records, must stay on the one
    # linear path to the head. Develop's #1756 learning-applicability
    # migration (M4-B3, #119) claimed the `053` tip on develop as
    # `054_learning_applicability_epistemics`, renumbering #1892's
    # `054_task_admission_generations` — itself re-parented onto this
    # chain's `053` tip at the previous develop sync — to `055`; the
    # develop #55 effect-path sync added `043_invocation_quota_door`
    # (#1196/#718) on that tip; and this sync's #1047 user-model tables —
    # re-parented past develop's `054` and `055` as `056` in their own
    # two collisions — revise the quota door, so the single linear head
    # is the user-model revision.
    assert {
        "034_canonical_run_effect_claim",
        "034",
        "035",
        "039_quota_usage_event_identity",
        "044",
        "046",
        "047",
        "048",
        "049",
        "050",
        "051",
        "052",
        "053",
        "054",
        "055",
        "043_invocation_quota_door",
        "056",
    } <= walked
    # The superseded standalone revisions must stay gone: resurrecting either
    # re-forks the chain (a second head) or re-applies DDL no store declares —
    # the exact collision the 55be1459 resolution removed them for. Develop's
    # copies of both files stay deleted here; only this branch's test side of
    # the sync carries their absence, so the guard keeps asserting it even as
    # the quota door's revision id echoes the retired `043`.
    assert "043" not in walked
    assert "045" not in walked


def test_migration_and_the_durable_stores_describe_one_claim_schema(
    migration: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    operations = _Operations()
    monkeypatch.setattr(migration, "op", operations)

    migration.upgrade()

    # The table carries the persisted scope discriminator, defaulted empty so
    # the very next statement can backfill it from the physical visit.
    assert operations.table_name == "capability_invocations"
    columns = {column.name: column for column in operations.columns}
    assert set(columns) >= {"invocation_id", "run_id", "node_run_id", "effect_key", "effect_scope"}
    assert getattr(columns["effect_scope"].server_default, "arg", None) == ""

    # The lookup index keeps the physical-visit shape (043's reshape was
    # superseded), and the claim index is replaced by the scope-keyed one.
    assert ("idx_capability_invocation_effect", "capability_invocations", LOOKUP_COLUMNS) in (
        operations.created_indexes
    )
    claim_create = _normalized(
        f"CREATE UNIQUE INDEX uq_capability_invocation_active_effect "
        f"ON capability_invocations ({', '.join(CLAIM_COLUMNS)}) {CLAIM_PREDICATE}"
    )
    assert [_normalized(s) for s in operations.executed] == [
        "UPDATE capability_invocations SET effect_scope = node_run_id WHERE effect_scope = ''",
        "DROP INDEX IF EXISTS uq_capability_invocation_active_effect",
        claim_create,
    ]

    # The deployment DDL and both durable stores must state one claim schema:
    # the trio above, byte-for-byte after whitespace normalization, is what
    # ``ensure_schema`` runs on SQLite and PostgreSQL alike.
    for store in STORES:
        assert _store_claim_statements(store) == [_normalized(s) for s in operations.executed], (
            f"{store.name} _CLAIM_DDL drifted from migration 035"
        )
        assert _store_lookup_index_columns(store) == LOOKUP_COLUMNS, (
            f"{store.name} _SCHEMA lookup index drifted from migration 035"
        )
        schema = _store_table_ddl(store)
        assert "effect_scope TEXT NOT NULL DEFAULT ''" in _normalized(schema), (
            f"{store.name} _SCHEMA lost the effect_scope column"
        )

    migration.downgrade()

    # The downgrade un-lands exactly what the upgrade landed: the claim index
    # first, then both lookup indexes, then the table itself.
    assert operations.dropped_indexes == [
        ("uq_capability_invocation_active_effect", "capability_invocations"),
        ("idx_capability_invocation_attempt", "capability_invocations"),
        ("idx_capability_invocation_effect", "capability_invocations"),
    ]
    assert operations.dropped_tables == ["capability_invocations"]
