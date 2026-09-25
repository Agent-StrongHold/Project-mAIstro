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


def _string_bindings(tree: ast.Module) -> dict[str, set[str]]:
    """Names that can only hold string literals: module constants and their loop targets.

    Provenance migrations add ``run_id`` as ``for column in _COLUMNS:
    op.add_column(table, sa.Column(column, ...))`` over module-level tuples, so a
    scan that only reads written-out names misses the repository's own idiom.
    """
    bindings: dict[str, set[str]] = {}
    for node in tree.body:
        value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
        targets = node.targets if isinstance(node, ast.Assign) else []
        if isinstance(node, ast.AnnAssign):
            targets = [node.target]
        strings = _literal_strings(value, bindings)
        if strings:
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = strings
    for node in ast.walk(tree):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name):
            strings = _literal_strings(node.iter, bindings)
            if strings:
                bindings.setdefault(node.target.id, set()).update(strings)
    return bindings


def _literal_strings(node: ast.expr | None, bindings: dict[str, set[str]]) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.Name):
        return set(bindings.get(node.id, ()))
    if isinstance(node, ast.Tuple | ast.List | ast.Set) and node.elts:
        values = [_literal_strings(element, bindings) for element in node.elts]
        if all(values):
            return set().union(*values)
    return set()


def _declares_run_id(node: ast.expr, bindings: dict[str, set[str]]) -> bool:
    return (
        isinstance(node, ast.Call)
        and getattr(node.func, "attr", getattr(node.func, "id", None)) == "Column"
        and bool(node.args)
        and "run_id" in _literal_strings(node.args[0], bindings)
    )


def _op_run_id_tables(node: ast.Call, bindings: dict[str, set[str]]) -> set[str]:
    func = node.func
    if not (
        isinstance(func, ast.Attribute)
        and func.attr in {"create_table", "add_column"}
        and getattr(func.value, "id", None) == "op"
    ):
        return set()
    arguments = [*node.args[1:], *(k.value for k in node.keywords if k.arg != "table_name")]
    if not any(_declares_run_id(argument, bindings) for argument in arguments):
        return set()
    table = (
        node.args[0]
        if node.args
        else next((k.value for k in node.keywords if k.arg == "table_name"), None)
    )
    tables = _literal_strings(table, bindings)
    assert tables, f"line {node.lineno}: op.{func.attr} adds run_id to a table the scan cannot name"
    return tables


def _orm_run_id_tables(tree: ast.Module) -> set[str]:
    tables: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        name: str | None = None
        has_run_id = False
        for statement in node.body:
            targets = statement.targets if isinstance(statement, ast.Assign) else []
            if isinstance(statement, ast.AnnAssign):
                targets = [statement.target]
            for target in targets:
                if not isinstance(target, ast.Name):
                    continue
                if target.id == "__tablename__" and isinstance(statement, ast.Assign):
                    value = statement.value
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        name = value.value
                has_run_id = has_run_id or target.id == "run_id"
        if name is not None and has_run_id:
            tables.add(name)
    return tables


def run_id_tables(gate: ModuleType, source: str, *, path: str = "<string>") -> set[str]:
    """Tables a Python module declares with a ``run_id``: migration, DDL or ORM model."""
    tree = ast.parse(source, filename=path)
    docstrings = gate._docstring_nodes(tree)
    bindings = _string_bindings(tree)
    tables = _orm_run_id_tables(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docstrings:
                tables |= _sql_run_id_tables(gate, node.value)
        elif isinstance(node, ast.Call):
            tables |= _op_run_id_tables(node, bindings)
    return tables


def discover_run_id_tables(gate: ModuleType, root: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    globs = (
        *gate.MIGRATION_GLOBS,
        *gate.RUNTIME_DDL_GLOBS,
        *gate.ORM_GLOBS,
        *gate.SQL_MIGRATION_GLOBS,
    )
    for path in gate._files(root, globs):
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
    # One per discovery shape: op.create_table (035), op.add_column (004), a
    # loop-built op.add_column only a migration declares (026), runtime DDL.
    assert {"capability_invocations", "capability_approvals", "design_outputs"} <= discovered.keys()
    assert "alembic/versions/004_task_run_id.py" in discovered["tasks"]
    assert "alembic/versions/026_record_producer_provenance.py" in discovered["design_outputs"]
    assert "packages/maistro-core/src/maistro/memory/store.py" in discovered["tasks"]


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


def test_a_loop_built_run_id_column_is_reported(gate: ModuleType) -> None:
    source = (
        "import sqlalchemy as sa\nfrom alembic import op\n\n"
        '_TABLES = ("run_a", "run_b")\n'
        '_COLUMNS = ("run_id", "node_run_id")\n'
        '_RUN = "run_id"\n\n'
        "def upgrade():\n"
        "    for table in _TABLES:\n"
        "        for column in _COLUMNS:\n"
        "            op.add_column(table, sa.Column(column, sa.Text))\n"
        '    op.add_column(table_name="run_c", column=sa.Column(_RUN, sa.Text))\n'
        '    op.add_column("unrelated", sa.Column("node_run_id", sa.Text))\n'
    )
    assert run_id_tables(gate, source) == {"run_a", "run_b", "run_c"}


def test_an_orm_model_run_id_column_is_reported(gate: ModuleType) -> None:
    source = (
        "class Receipt(Base):\n"
        '    __tablename__ = "run_orm_receipts"\n'
        "    run_id: Mapped[str] = mapped_column(String)\n\n"
        "class Other(Base):\n"
        '    __tablename__ = "no_run"\n'
        "    node_run_id = Column(String)\n"
    )
    assert run_id_tables(gate, source) == {"run_orm_receipts"}


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
