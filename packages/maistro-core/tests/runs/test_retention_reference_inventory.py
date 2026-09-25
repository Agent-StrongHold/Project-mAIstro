"""Every table carrying a ``run_id`` is named in the Run purge inventory (#1175).

The inventory in `maistro.runs.retention_scope` is the one place a purge's
policy for each dependent reference is decided. It only works if the next
table to grow a ``run_id`` column has to edit it: three tables
(``capability_invocations``, ``capability_approvals``, ``task_idempotency``)
joined the schema after it was written and nobody noticed. This test scans the
same sources the durable-table gate scans -- the Alembic chains, the raw
``.sql`` migrations and runtime ``CREATE TABLE`` DDL -- for tables that declare
a ``run_id`` column, and fails on any the inventory does not name.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

import maistro.runs.retention_scope as retention_scope
from maistro.runs.retention_scope import RUN_REFERENCING_TABLES

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "scripts" / "check-durable-table-inventory.py"

_RUN_ID_COLUMN = re.compile(r'(?:^|[(,])\s*"?run_id"?\s+[A-Za-z]', re.IGNORECASE)
_ADD_RUN_ID = re.compile(
    r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?(?:\"?[A-Za-z_]\w*\"?\.)?"
    r"\"?(?P<name>[A-Za-z_]\w*)\"?\s+ADD\s+(?:COLUMN\s+)?(?:IF\s+NOT\s+EXISTS\s+)?\"?run_id\"?\s",
    re.IGNORECASE,
)


@pytest.fixture(scope="module")
def gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_check_durable_table_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _column_list(sql: str, start: int) -> str:
    opening = sql.find("(", start)
    if opening < 0:
        return ""
    depth = 0
    for index in range(opening, len(sql)):
        if sql[index] == "(":
            depth += 1
        elif sql[index] == ")":
            depth -= 1
            if depth == 0:
                return sql[opening + 1 : index]
    return sql[opening + 1 :]


def _sql_run_id_tables(gate: ModuleType, sql: str) -> set[str]:
    sql = gate._SQL_COMMENT.sub(" ", sql)
    tables = {
        match.group("name")
        for match in gate._CREATE_TABLE.finditer(sql)
        if not match.group("temp") and _RUN_ID_COLUMN.search(_column_list(sql, match.end()))
    }
    tables.update(match.group("name") for match in _ADD_RUN_ID.finditer(sql))
    return tables


def _is_run_id_column(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", getattr(node.func, "id", None)) == "Column"
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "run_id"
    )


def _op_run_id_table(gate: ModuleType, node: ast.Call, constants: dict[str, str]) -> str | None:
    kind = node.func.attr if isinstance(node.func, ast.Attribute) else None
    if kind not in {"create_table", "add_column"}:
        return None
    if not (isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "op"):
        return None
    if not any(_is_run_id_column(arg) for arg in node.args[1:]):
        return None
    name: str = gate._op_table_name(node, constants, "<scan>")
    return name


def run_id_tables(gate: ModuleType, source: str, *, path: str = "<string>") -> set[str]:
    """Tables a Python module (migration or runtime DDL) declares with a ``run_id``."""
    tree = ast.parse(source, filename=path)
    docstrings = gate._docstring_nodes(tree)
    constants = gate._module_strings(tree)
    tables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                tables |= _sql_run_id_tables(gate, node.value)
        elif isinstance(node, ast.Call):
            name = _op_run_id_table(gate, node, constants)
            if name is not None:
                tables.add(name)
    return tables


def discover_run_id_tables(gate: ModuleType, root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    python_globs = (*gate.MIGRATION_GLOBS, *gate.RUNTIME_DDL_GLOBS)
    for path in gate._files(root, (*python_globs, *gate.SQL_MIGRATION_GLOBS)):
        text = path.read_text()
        if "run_id" not in text:
            continue
        rel = str(path.relative_to(root))
        names = (
            _sql_run_id_tables(gate, text)
            if path.suffix == ".sql"
            else run_id_tables(gate, text, path=rel)
        )
        for name in names:
            found.setdefault(name, []).append(rel)
    return found


def test_every_run_id_table_is_in_the_purge_inventory(gate: ModuleType) -> None:
    discovered = discover_run_id_tables(gate, ROOT)
    missing = {
        table: where for table, where in discovered.items() if table not in RUN_REFERENCING_TABLES
    }
    assert not missing, (
        "tables with a run_id column that the Run purge inventory in "
        f"maistro.runs.retention_scope does not account for: {missing}"
    )


def test_scan_sees_the_known_reference_shapes(gate: ModuleType) -> None:
    discovered = discover_run_id_tables(gate, ROOT)
    # One per discovery shape: op.create_table (035), op.add_column (004), runtime DDL.
    assert {"capability_invocations", "tasks", "capability_approvals"} <= discovered.keys()


def test_inventory_names_no_table_the_schema_lacks(gate: ModuleType) -> None:
    schema = gate.discover(ROOT)
    assert set(RUN_REFERENCING_TABLES) - schema.keys() == set()


def test_a_new_migration_run_id_table_is_reported(gate: ModuleType) -> None:
    source = (
        "import sqlalchemy as sa\nfrom alembic import op\n\n"
        "def upgrade():\n"
        '    op.create_table("run_widgets", sa.Column("id", sa.Text()),'
        ' sa.Column("run_id", sa.Text(), nullable=False))\n'
        '    op.create_table("unrelated", sa.Column("node_run_id", sa.Text()))\n'
    )
    found = run_id_tables(gate, source)
    assert found == {"run_widgets"}
    assert "run_widgets" not in RUN_REFERENCING_TABLES


def test_a_new_runtime_ddl_run_id_table_is_reported(gate: ModuleType) -> None:
    source = (
        '"""CREATE TABLE docstring_only (run_id TEXT)"""\n'
        "SCHEMA = '''\n"
        "CREATE TABLE IF NOT EXISTS run_receipts (\n"
        "    id TEXT PRIMARY KEY,\n"
        "    -- run_id TEXT is a comment, not a column\n"
        "    parent_run_id TEXT\n"
        ");\n"
        "CREATE TABLE IF NOT EXISTS run_marks (\n"
        "    id TEXT PRIMARY KEY, run_id TEXT NOT NULL,\n"
        "    FOREIGN KEY (run_id) REFERENCES canonical_runs(run_id)\n"
        ");\n"
        "ALTER TABLE legacy_rows ADD COLUMN run_id TEXT;\n"
        "'''\n"
    )
    assert run_id_tables(gate, source) == {"run_marks", "legacy_rows"}


def test_every_inventoried_table_has_a_policy_row() -> None:
    doc = retention_scope.__doc__ or ""
    assert [table for table in RUN_REFERENCING_TABLES if table not in doc] == []
