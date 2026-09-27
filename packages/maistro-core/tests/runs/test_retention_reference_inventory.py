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
import itertools
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


def _module_level_literal_tuple(tree: ast.Module) -> dict[str, ast.expr]:
    tuples: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Tuple | ast.List):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    tuples[target.id] = node.value
    return tuples


def _module_level_literal_dict(tree: ast.Module) -> dict[str, ast.Dict]:
    dicts: dict[str, ast.Dict] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    dicts[target.id] = node.value
    return dicts


def _row_fields(
    node: ast.expr, tuples: dict[str, ast.expr], dicts: dict[str, ast.Dict]
) -> list[list[ast.expr]] | None:
    """A for-loop's ``iter``, resolved to one element-list per row.

    Handles an inline tuple/list of tuples/lists, a module constant bound to
    one (``sqlite_outcomes.py``'s ``_ADDED_COLUMNS``), or ``<dict>.items()``
    on a module-level dict literal (``sqlite_learnings.py``'s legacy-column
    upgrade). Returns ``None`` when the shape is not one of these, so the
    caller can fail loudly on a schema statement it cannot verify rather than
    silently skip it.
    """
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "items"
        and not node.args
        and not node.keywords
        and isinstance(node.func.value, ast.Name)
    ):
        dict_node = dicts.get(node.func.value.id)
        if dict_node is None or len(dict_node.keys) != len(dict_node.values):
            return None
        if any(key is None for key in dict_node.keys):
            return None  # a `**spread` entry -- not a literal key/value pair
        return [
            [key, value]
            for key, value in zip(dict_node.keys, dict_node.values, strict=True)
            if key is not None
        ]
    if isinstance(node, ast.Name):
        resolved = tuples.get(node.id)
        if resolved is None:
            return None
        node = resolved
    if not isinstance(node, ast.Tuple | ast.List) or not node.elts:
        return None
    rows: list[list[ast.expr]] = []
    for element in node.elts:
        if not isinstance(element, ast.Tuple | ast.List):
            return None
        rows.append(list(element.elts))
    return rows


def _bind_tuple_target(
    target: ast.Tuple | ast.List,
    iter_node: ast.expr,
    bindings: dict[str, set[str]],
    tuples: dict[str, ast.expr],
    dicts: dict[str, ast.Dict],
) -> None:
    rows = _row_fields(iter_node, tuples, dicts)
    if rows is None:
        return
    for row in rows:
        for index, element in enumerate(target.elts):
            if not isinstance(element, ast.Name) or index >= len(row):
                continue
            values = _literal_strings(row[index], bindings)
            if values:
                bindings.setdefault(element.id, set()).update(values)


def _bind_module_assigns(tree: ast.Module, bindings: dict[str, set[str]]) -> None:
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


def _string_bindings(tree: ast.Module) -> dict[str, set[str]]:
    """Names that can only hold string literals: module constants and their loop targets.

    Provenance migrations add ``run_id`` as ``for column in _COLUMNS:
    op.add_column(table, sa.Column(column, ...))`` over module-level tuples, so a
    scan that only reads written-out names misses the repository's own idiom.
    The SQLite twins add it as ``for column, ddl in _ADDED_COLUMNS: ... ADD
    COLUMN {column} {ddl}`` (a tuple-unpacking loop, inline or module-level) or
    ``for column, kind in _LEGACY_COLUMNS.items(): ...`` -- both resolved by
    ``_bind_tuple_target`` so a formatted ``ALTER TABLE`` built from either
    shape is not a blind spot.
    """
    bindings: dict[str, set[str]] = {}
    _bind_module_assigns(tree, bindings)
    tuples = _module_level_literal_tuple(tree)
    dicts = _module_level_literal_dict(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        if isinstance(node.target, ast.Name):
            strings = _literal_strings(node.iter, bindings)
            if strings:
                bindings.setdefault(node.target.id, set()).update(strings)
        elif isinstance(node.target, ast.Tuple | ast.List):
            _bind_tuple_target(node.target, node.iter, bindings, tuples, dicts)
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


_DDL_KEYWORD = re.compile(r"ALTER\s+TABLE|CREATE\s+TABLE", re.IGNORECASE)


def _joinedstr_candidates(node: ast.JoinedStr, bindings: dict[str, set[str]]) -> set[str] | None:
    """Every flattened string an f-string can produce, or ``None`` if a part is unresolvable."""
    options: list[list[str]] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            options.append([value.value])
        elif isinstance(value, ast.FormattedValue):
            resolved = _literal_strings(value.value, bindings)
            if not resolved:
                return None
            options.append(sorted(resolved))
        else:
            return None
    combos = itertools.islice(itertools.product(*options), 256)
    return {"".join(combo) for combo in combos}


def _joinedstr_run_id_tables(
    gate: ModuleType, node: ast.JoinedStr, bindings: dict[str, set[str]], *, path: str
) -> set[str]:
    """A runtime schema-upgrade f-string (``sqlite_outcomes.py`` etc.), resolved or refused.

    ``run_id`` reaches these ``ALTER TABLE`` statements through a loop
    variable, not a literal, so the scan must resolve every interpolated part
    to know whether it names ``run_id`` before it can say the statement does
    not. An interpolation this cannot resolve statically is refused rather
    than silently treated as run_id-free: a DDL-shaped f-string this scan
    cannot verify must not let a future run_id column pass unaccounted for.
    """
    resolved = _joinedstr_candidates(node, bindings)
    if resolved is not None:
        tables: set[str] = set()
        for candidate in resolved:
            tables |= _sql_run_id_tables(gate, candidate)
        return tables
    skeleton = "".join(
        value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else "\x00"
        for value in node.values
    )
    assert not _DDL_KEYWORD.search(skeleton), (
        f"{path}:{node.lineno}: formatted SQL DDL with a value this scan cannot resolve "
        "statically, so it cannot verify the interpolated part does not add run_id -- bind "
        "it to a literal the scan can read (see _row_fields), or name the table explicitly"
    )
    return set()


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
        elif isinstance(node, ast.JoinedStr):
            tables |= _joinedstr_run_id_tables(gate, node, bindings, path=path)
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
    # A migration can drop a table an earlier one gave `run_id` (or, within a
    # single .sql file, create and drop it in the same file). `gate.discover`
    # already replays each chain's creates and drops in file order to answer
    # "what does the schema hold now" for the durable-table gate this test
    # reuses; a name that scan does not currently hold does not need a purge
    # policy for a column it no longer has, so it is not required here either.
    schema = gate.discover(root)
    return {table: where for table, where in found.items() if table in schema}


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


def test_a_dropped_table_is_excluded_even_if_an_earlier_migration_added_run_id(
    gate: ModuleType, tmp_path: Path
) -> None:
    # A table an earlier revision gave `run_id` and a later one drops entirely
    # is not part of the current schema `gate.discover` replays to; keeping it
    # in RUN_REFERENCING_TABLES would fail test_inventory_names_no_table_the_
    # schema_lacks, and dropping it from RUN_REFERENCING_TABLES would fail
    # test_every_run_id_table_is_in_the_purge_inventory if this scan still
    # reported it -- there would be no passing inventory state. It must not
    # be reported once dropped.
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "001_create.py").write_text(
        "import sqlalchemy as sa\nfrom alembic import op\n\n"
        "def upgrade():\n"
        '    op.create_table("run_widget_dropped", sa.Column("id", sa.Text()),'
        ' sa.Column("run_id", sa.Text()))\n'
    )
    (versions / "002_drop.py").write_text(
        "from alembic import op\n\ndef upgrade():\n    op.drop_table('run_widget_dropped')\n"
    )
    assert "run_widget_dropped" not in discover_run_id_tables(gate, tmp_path)


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


def test_a_tuple_unpacking_ddl_fstring_column_is_reported(gate: ModuleType) -> None:
    # sqlite_outcomes.py's shape: a module-level tuple-of-pairs, unpacked in
    # the for target, spliced into a runtime `ALTER TABLE ... ADD COLUMN`
    # f-string -- an ast.JoinedStr the plain-Constant scan never visits.
    source = (
        "_ADDED = (\n"
        '    ("project_id", "TEXT"),\n'
        '    ("run_id", "TEXT"),\n'
        ")\n\n"
        "async def ensure_schema(conn):\n"
        "    for column, ddl in _ADDED:\n"
        '        await conn.execute(f"ALTER TABLE outcomes ADD COLUMN {column} {ddl}")\n'
    )
    assert run_id_tables(gate, source) == {"outcomes"}


def test_a_dict_items_ddl_fstring_column_is_reported(gate: ModuleType) -> None:
    # sqlite_learnings.py's shape: a module-level dict, unpacked via `.items()`.
    source = (
        '_LEGACY = {"run_id": "TEXT", "team_id": "TEXT"}\n\n'
        "async def ensure_schema(conn):\n"
        "    for column, column_type in _LEGACY.items():\n"
        '        await conn.execute(f"ALTER TABLE learnings ADD COLUMN {column} {column_type}")\n'
    )
    assert run_id_tables(gate, source) == {"learnings"}


def test_an_unresolvable_ddl_fstring_fails_loudly(gate: ModuleType) -> None:
    # A column name the scan cannot resolve statically (here, a function
    # parameter) must not be treated as run_id-free just because it is not
    # a literal "run_id" -- the scan refuses rather than passing silently.
    source = (
        "def ensure_schema(conn, column):\n"
        '    conn.execute(f"ALTER TABLE widgets ADD COLUMN {column} TEXT")\n'
    )
    with pytest.raises(AssertionError, match="formatted SQL DDL"):
        run_id_tables(gate, source)


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


def _policy_row_names(doc: str) -> set[str]:
    """Table names named by an actual row of the docstring's policy table.

    A bare substring check passes if a name merely occurs anywhere in the
    docstring -- in another row, or in surrounding prose -- even after its
    own row is deleted. This instead isolates the table between its bounding
    ``====`` separators and reads the Reference cell of each data row (the
    text before the first run of 2+ spaces), splitting a row that names
    several tables (``tasks.run_id, session_turns.run_id`` or
    ``learnings/outcomes/...``) on ``,``/``/``.
    """
    lines = doc.splitlines()
    separators = [index for index, line in enumerate(lines) if line.startswith("====")]
    assert len(separators) >= 3, "retention_scope docstring is missing its policy table"
    names: set[str] = set()
    for line in lines[separators[1] + 1 : separators[2]]:
        if not line.strip():
            continue
        reference = re.split(r"\s{2,}", line.strip(), maxsplit=1)[0]
        for chunk in re.split(r"[,/]", reference):
            name = chunk.strip().split(".", 1)[0].strip()
            if name:
                names.add(name.split()[0])
    return names


def test_every_inventoried_table_has_a_policy_row() -> None:
    doc = retention_scope.__doc__ or ""
    named = _policy_row_names(doc)
    missing = [table for table in RUN_REFERENCING_TABLES if table not in named]
    assert not missing, (
        "tables with no policy row (by name, not merely mentioned somewhere in the "
        f"docstring) in maistro.runs.retention_scope: {missing}"
    )


def test_a_table_named_only_in_prose_is_not_a_policy_row() -> None:
    # A bare substring check would pass this: "ghost_table" occurs in the
    # docstring, just not as the Reference cell of any row of its own.
    fake_doc = (
        "Intro prose that happens to mention ghost_table in passing.\n\n"
        "==========  ==========  ==========\n"
        "Reference   Constraint  Policy\n"
        "==========  ==========  ==========\n"
        "real_table.run_id   none   Preserve.\n"
        "==========  ==========  ==========\n"
    )
    named = _policy_row_names(fake_doc)
    assert "real_table" in named
    assert "ghost_table" not in named
