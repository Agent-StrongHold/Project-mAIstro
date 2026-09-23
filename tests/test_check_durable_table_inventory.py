"""Every durable table carries a declared retention, checked against the tree (#325).

`security_violations` and `usage_events` grew forever because nothing required
anyone to say how long their rows should live. The gate makes a new table fail
the build until it has an entry, and an entry fail once nothing creates its
table.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-durable-table-inventory.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("_check_durable_table_inventory", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _names(found) -> list[str]:
    return [item.table for item in found]


class TestDiscovery:
    def test_single_line_create_table(self, check):
        source = (
            'from alembic import op\n\ndef upgrade():\n    op.create_table("a", sa.Column("id"))\n'
        )
        assert _names(check.migration_tables(source)) == ["a"]

    def test_multi_line_create_table(self, check):
        source = (
            "from alembic import op\n\n"
            "def upgrade():\n"
            "    op.create_table(\n"
            '        "multi",\n'
            '        sa.Column("id", sa.Text()),\n'
            "    )\n"
        )
        assert _names(check.migration_tables(source)) == ["multi"]

    def test_create_table_through_a_module_constant(self, check):
        source = '_TABLE = "via_const"\n\ndef upgrade():\n    op.create_table(_TABLE)\n'
        assert _names(check.migration_tables(source)) == ["via_const"]

    def test_create_table_by_keyword(self, check):
        source = 'def upgrade():\n    op.create_table(table_name="kw")\n'
        assert _names(check.migration_tables(source)) == ["kw"]

    def test_unresolvable_create_table_is_an_error_not_a_skip(self, check):
        source = "def upgrade(name):\n    op.create_table(name)\n"
        with pytest.raises(ValueError, match="cannot resolve"):
            check.migration_tables(source)

    def test_raw_ddl_in_a_migration(self, check):
        source = 'def upgrade():\n    op.execute("CREATE TABLE IF NOT EXISTS orgs (id TEXT)")\n'
        assert _names(check.migration_tables(source)) == ["orgs"]

    def test_if_not_exists_ddl(self, check):
        source = '_DDL = """\nCREATE TABLE IF NOT EXISTS usage_events (\n  id TEXT\n)\n"""\n'
        assert _names(check.ddl_tables(source)) == ["usage_events"]

    def test_plain_and_schema_qualified_ddl(self, check):
        source = 'A = "create table plain (id int)"\nB = "CREATE TABLE public.qualified (id int)"\n'
        assert _names(check.ddl_tables(source)) == ["plain", "qualified"]

    def test_docstrings_and_temp_tables_are_not_tables(self, check):
        source = (
            '"""`CREATE TABLE IF NOT EXISTS` behind a migration chain."""\n\n'
            "def f():\n"
            '    """Uses CREATE TABLE widgets for illustration."""\n'
            '    return "CREATE TEMP TABLE scratch (id int)"\n'
        )
        assert _names(check.ddl_tables(source)) == []

    def test_unlogged_ddl(self, check):
        source = 'A = "CREATE UNLOGGED TABLE IF NOT EXISTS fast (id int)"\n'
        assert _names(check.ddl_tables(source)) == ["fast"]

    def test_tablename(self, check):
        source = 'class Order(Base):\n    __tablename__ = "orders"\n'
        assert _names(check.orm_tables(source)) == ["orders"]


def _entry(table: str, **overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "table": table,
        "backends": ["sqlite"],
        "owner_module": "pkg/store.py",
        "data_class": "runtime_state",
        "retention": "undecided",
        "deletion_path": None,
        "issue": "#325",
    }
    entry.update(overrides)
    return entry


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "store.py").write_text("")
    versions = tmp_path / "alembic" / "versions"
    versions.mkdir(parents=True)
    (versions / "001_x.py").write_text(
        "def upgrade():\n"
        '    op.create_table("security_violations")\n'
        '    op.create_table(\n        "kept",\n    )\n'
    )
    src = tmp_path / "packages" / "demo" / "src" / "demo"
    src.mkdir(parents=True)
    (src / "log.py").write_text('DDL = "CREATE TABLE IF NOT EXISTS usage_events (id int)"\n')
    tests = tmp_path / "packages" / "demo" / "tests"
    tests.mkdir()
    (tests / "fixture.py").write_text('DDL = "CREATE TABLE ignored_in_tests (id int)"\n')
    return tmp_path


def _inventory(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"tables": list(entries)}


def _complete() -> list[dict[str, Any]]:
    return [_entry("security_violations"), _entry("kept"), _entry("usage_events")]


class TestGate:
    def test_complete_inventory_passes(self, check, tree):
        report = check.check(tree, _inventory(*_complete()))
        assert report.errors == []
        assert sorted(report.discovered) == ["kept", "security_violations", "usage_events"]

    def test_missing_entry_fails(self, check, tree):
        entries = [e for e in _complete() if e["table"] != "kept"]
        report = check.check(tree, _inventory(*entries))
        assert any("'kept'" in e and "no retention entry" in e for e in report.errors)

    def test_stale_entry_fails(self, check, tree):
        report = check.check(tree, _inventory(*_complete(), _entry("dropped_long_ago")))
        assert any("'dropped_long_ago'" in e and "stale" in e for e in report.errors)

    def test_unresolvable_deletion_path_fails(self, check, tree):
        entries = _complete()
        entries[1]["deletion_path"] = "no_such_module_325:purge"
        report = check.check(tree, _inventory(*entries))
        assert any("does not resolve" in e for e in report.errors)

    def test_missing_attribute_in_deletion_path_fails(self, check, tree):
        entries = _complete()
        entries[1]["deletion_path"] = "json:no_such_function"
        report = check.check(tree, _inventory(*entries))
        assert any("does not resolve" in e for e in report.errors)

    def test_resolvable_deletion_path_passes(self, check, tree):
        entries = _complete()
        entries[1].update(retention="ttl_purge", deletion_path="json:dumps", issue=None)
        assert check.check(tree, _inventory(*entries)).errors == []

    def test_driven_retention_without_deletion_path_fails(self, check, tree):
        entries = _complete()
        entries[1].update(retention="ttl_purge", issue=None)
        report = check.check(tree, _inventory(*entries))
        assert any("names no deletion_path" in e for e in report.errors)

    def test_undecided_without_issue_fails(self, check, tree):
        entries = _complete()
        entries[1]["issue"] = None
        report = check.check(tree, _inventory(*entries))
        assert any("must name the issue" in e for e in report.errors)

    def test_bounded_by_parent_needs_an_inventoried_parent(self, check, tree):
        entries = _complete()
        entries[1].update(retention="bounded_by_parent", parent="nowhere", issue=None)
        report = check.check(tree, _inventory(*entries))
        assert any("parent 'nowhere'" in e for e in report.errors)

    def test_bad_enum_values_fail(self, check, tree):
        entries = _complete()
        entries[1].update(retention="forever", data_class="misc", backends=["oracle"])
        report = check.check(tree, _inventory(*entries))
        joined = "\n".join(report.errors)
        assert "retention 'forever'" in joined
        assert "data_class 'misc'" in joined
        assert "backends" in joined

    def test_malformed_entries_fail(self, check, tree):
        entries = _complete()
        entries[1].update(owner_module="nowhere.py", issue="325", policy_ref="nowhere.md")
        broken = {"table": "kept_too"}
        report = check.check(tree, _inventory(*entries, "not-an-object", broken))
        joined = "\n".join(report.errors)
        assert "owner_module 'nowhere.py'" in joined
        assert "issue must be" in joined
        assert "policy_ref 'nowhere.md'" in joined
        assert "entry 3: not an object" in joined
        assert "'kept_too': missing keys" in joined

    def test_undiscoverable_table_is_reported_not_raised(self, check, tree):
        (tree / "alembic" / "versions" / "002_y.py").write_text(
            "def upgrade(name):\n    op.create_table(name)\n"
        )
        report = check.check(tree, _inventory(*_complete()))
        assert any("table discovery failed" in e for e in report.errors)

    def test_parent_must_be_a_name(self, check, tree):
        entries = _complete()
        entries[1].update(retention="bounded_by_parent", parent=["kept"], issue=None)
        report = check.check(tree, _inventory(*entries))
        assert any("parent must be a table name" in e for e in report.errors)

    def test_non_callable_deletion_path_fails(self, check, tree):
        entries = _complete()
        entries[1]["deletion_path"] = "json:__name__"
        report = check.check(tree, _inventory(*entries))
        assert any("is not callable" in e for e in report.errors)

    def test_deletion_path_needs_a_qualname(self, check):
        with pytest.raises(ValueError, match="module:qualname"):
            check.resolve("json")

    def test_inventory_without_a_tables_list_fails(self, check, tree):
        report = check.check(tree, {"rows": []})
        assert any("'tables' list" in e for e in report.errors)

    def test_duplicate_entry_fails(self, check, tree):
        report = check.check(tree, _inventory(*_complete(), _entry("kept")))
        assert any("declared more than once" in e for e in report.errors)

    @pytest.mark.parametrize("named", ["security_violations", "usage_events"])
    def test_named_tables_cannot_leave_the_inventory(self, check, tree, named):
        entries = [e for e in _complete() if e["table"] != named]
        report = check.check(tree, _inventory(*entries))
        assert any(f"'{named}': must stay" in e for e in report.errors)

    def test_main_exit_codes(self, check, tree, capsys):
        inventory = tree / "inventory.json"
        inventory.write_text(json.dumps(_inventory(*_complete())))
        assert check.main(["--root", str(tree), "--inventory", str(inventory)]) == 0
        inventory.write_text(json.dumps(_inventory(_entry("kept"))))
        assert check.main(["--root", str(tree), "--inventory", str(inventory)]) == 1
        assert "problem(s)" in capsys.readouterr().err


class TestRealTree:
    def test_repository_inventory_covers_the_schema(self, check):
        inventory = json.loads((ROOT / check.INVENTORY).read_text())
        report = check.check(ROOT, inventory)
        assert report.errors == []
        for named in ("security_violations", "usage_events", "task_idempotency"):
            assert named in report.discovered
