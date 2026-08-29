"""Tests for the cross-package import resolver (#293).

The gate exists because ruff, mypy and the test suite all looked at
`from maistro_design.systems.builtins import load_builtins` -- a module with no
file in any version of that package -- and none of them said anything. Two
reasons, and the tests below are organised around them: nothing resolves
imports into a package that is not installed in the checking environment, and a
bare `except Exception` around the import turned the failure into product
behaviour rather than a crash.

So the cases that matter are the two failure directions. A resolver that stops
finding the missing module lets the whole class back in; one that flags
legitimate re-exports gets waived everywhere within a week and then deleted.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-cross-package-imports.py"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_cross_package_imports", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def workspace(tmp_path: Path):
    """A miniature two-package monorepo in the layout the real one uses.

    `packages/<dist>/src/<pkg>/` for the importable libraries; the scanned file
    is written wherever the test wants it, because what imports is not
    constrained to those trees -- hive-conductor's flat backend is the whole
    reason this gate exists.
    """
    pkg = tmp_path / "packages" / "thing" / "src" / "thing"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from thing.real import Widget\n", encoding="utf-8")
    (pkg / "real.py").write_text("class Widget:\n    pass\n\n\nHELPER = 1\n", encoding="utf-8")
    sub = pkg / "systems"
    sub.mkdir()
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "importer.py").write_text("def load_bundled(registry):\n    ...\n", encoding="utf-8")
    return tmp_path


def _scan(check, workspace: Path, body: str, *, name: str = "app.py"):
    """Scan `body` as a file inside `workspace`, against `workspace`'s packages."""
    path = workspace / name
    path.write_text(body, encoding="utf-8")
    roots = {"thing": workspace / "packages" / "thing" / "src" / "thing"}
    return check.scan(path, roots, repo_root=workspace)


class TestTheDefectItWasWrittenFor:
    def test_a_module_that_does_not_exist_is_caught(self, check, workspace):
        """`maistro_design.systems.builtins`, in miniature. The whole bug."""
        (finding,) = _scan(check, workspace, "from thing.systems.builtins import load\n")
        assert finding.target == "thing.systems.builtins"
        assert "no such module" in finding.reason

    def test_a_plain_import_of_a_missing_module_is_caught_too(self, check, workspace):
        """`import x.y` fails identically at runtime; only the syntax differs."""
        (finding,) = _scan(check, workspace, "import thing.systems.builtins\n")
        assert finding.target == "thing.systems.builtins"

    def test_a_name_that_does_not_exist_is_caught(self, check, workspace):
        """One level down, and the one a typo makes: the module resolves, the
        attribute does not. Same ImportError, same bare-except swallow."""
        (finding,) = _scan(check, workspace, "from thing.systems.importer import load_builtins\n")
        assert finding.target == "thing.systems.importer.load_builtins"
        assert "presents no `load_builtins`" in finding.reason

    def test_the_correct_import_resolves(self, check, workspace):
        """The fix #293 actually shipped."""
        assert _scan(check, workspace, "from thing.systems.importer import load_bundled\n") == []


class TestWhatMustNotBeFlagged:
    """Every false positive here is a waiver someone adds, and a gate that is
    mostly waivers stops being read."""

    def test_a_reexport_from_init_resolves(self, check, workspace):
        """`__init__.py` re-export is how most of these packages present an API.
        `Widget` is defined in `thing.real` and only imported by `thing`."""
        assert _scan(check, workspace, "from thing import Widget\n") == []

    def test_a_submodule_is_importable_without_being_named_in_init(self, check, workspace):
        """`from thing import systems` works at runtime even though `thing`'s
        `__init__` never mentions it. Flagging this would hit every package."""
        assert _scan(check, workspace, "from thing import systems\n") == []

    def test_a_module_level_assignment_counts_as_a_name(self, check, workspace):
        assert _scan(check, workspace, "from thing.real import HELPER\n") == []

    def test_third_party_and_stdlib_are_not_our_business(self, check, workspace):
        """This resolves against the workspace only. `pathlib` and `pydantic`
        have no source tree here, and reporting them would be noise at best."""
        body = "import pathlib\nfrom pydantic import BaseModel\nimport does.not.exist\n"
        assert _scan(check, workspace, body) == []

    def test_a_relative_import_is_not_our_business(self, check, workspace):
        """It resolves inside its own package, where the interpreter and that
        package's own tests already catch a wrong one."""
        assert _scan(check, workspace, "from .sibling import thing\n") == []

    def test_a_star_import_is_not_resolved(self, check, workspace):
        """`*` names nothing in particular, so there is nothing to check --
        but the module it comes from still is."""
        assert _scan(check, workspace, "from thing.real import *\n") == []
        (finding,) = _scan(check, workspace, "from thing.nope import *\n")
        assert finding.target == "thing.nope"

    def test_an_unparseable_file_is_skipped_not_reported(self, check, workspace):
        """A syntax error is ruff's finding, reported with a line and a column.
        Reporting it a second time here as an import problem misdirects."""
        assert _scan(check, workspace, "def (\n") == []


class TestItLooksWhereTheBugWas:
    def test_an_import_inside_a_function_is_checked(self, check, workspace):
        """The real one was inside a function, inside a `try`. An AST walk that
        only read module-level imports would have missed it entirely."""
        body = "def start():\n    try:\n        from thing.systems.builtins import load\n    except Exception:\n        pass\n"
        (finding,) = _scan(check, workspace, body)
        assert finding.target == "thing.systems.builtins"

    def test_the_line_number_points_at_the_import(self, check, workspace):
        body = "x = 1\n\n\nfrom thing.nope import load\n"
        (finding,) = _scan(check, workspace, body)
        assert finding.line_no == 4

    def test_several_names_in_one_statement_are_each_reported(self, check, workspace):
        body = "from thing.real import Widget, Gadget, Gizmo\n"
        assert sorted(f.target for f in _scan(check, workspace, body)) == [
            "thing.real.Gadget",
            "thing.real.Gizmo",
        ]


class TestTheEscapeHatch:
    """A rule with no exception gets deleted the first time someone needs it --
    but an exception that costs nothing to claim is an off switch."""

    def test_a_waiver_on_the_same_line_suppresses(self, check, workspace):
        body = "from thing.nope import load  # cross-package-imports: allow lives elsewhere\n"
        assert _scan(check, workspace, body) == []

    def test_a_waiver_on_the_line_above_suppresses(self, check, workspace):
        """Import lines are long and often already at the limit, so the comment
        goes above as often as beside; accepting only one placement is a rule
        people reformat around."""
        body = "# cross-package-imports: allow lives elsewhere, see #297\nfrom thing.nope import load\n"
        assert _scan(check, workspace, body) == []

    def test_a_waiver_without_a_reason_does_not_suppress(self, check, workspace):
        """The reason is the whole mechanism. A bare marker reads as review in
        the diff while recording nothing."""
        body = "from thing.nope import load  # cross-package-imports: allow\n"
        assert [f.target for f in _scan(check, workspace, body)] == ["thing.nope"]

    def test_a_waiver_two_lines_above_does_not_reach(self, check, workspace):
        """Otherwise one waiver drifts over unrelated imports as a file grows."""
        body = (
            "# cross-package-imports: allow something else entirely\n"
            "import os\n"
            "from thing.nope import load\n"
        )
        assert [f.target for f in _scan(check, workspace, body)] == ["thing.nope"]


class TestTheRepository:
    # Two whole-tree scans -- ~1800 files, and under `coverage --source=scripts`
    # every line of the resolver is traced. Measured at 14s and 6s that way,
    # against the suite's 30s default, so the margin is stated rather than
    # discovered when a slower runner turns it into an intermittent red.
    @pytest.mark.timeout(120)
    def test_the_current_tree_resolves(self, check):
        """The state this gate was written to establish. If this fails, an
        import names something that is not there -- which on the evidence of
        #293 will otherwise be found by a user, months later."""
        roots = check.source_roots()
        findings = [f for path in check.source_files() for f in check.scan(path, roots)]
        assert findings == [], "\n".join(f.render() for f in findings)

    def test_it_finds_every_first_party_package(self, check):
        """A resolver whose root map silently shrank would report a clean tree
        by checking almost nothing."""
        roots = check.source_roots()
        assert {"maistro", "maistro_design", "maistro_canvas"} <= set(roots)

    def test_the_conductor_backend_is_in_scope(self, check):
        """hive-conductor has no wheel, so `verify-wheel-imports.py` skips it by
        design. It is the package the defect shipped in; a scan that missed it
        would be a gate for everything except the thing that broke."""
        files = {str(p.relative_to(check.REPO_ROOT)) for p in check.source_files()}
        assert "packages/hive-conductor/backend/services/design_service.py" in files

    @pytest.mark.timeout(120)
    def test_the_script_exits_zero_on_the_real_tree(self):
        """End to end, the way `lint-and-type-check` invokes it."""
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=ROOT
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "import only modules and names that exist" in proc.stdout


class TestTheReport:
    def test_a_finding_carries_the_file_line_and_reason(self, check, workspace):
        (finding,) = _scan(check, workspace, "from thing.nope import load\n")
        rendered = finding.render()
        assert "app.py:1" in rendered
        assert "thing.nope" in rendered

    def test_main_fails_and_names_the_waiver_syntax(self, check, workspace, monkeypatch, capsys):
        """A gate that says only "no" gets worked around rather than followed."""
        path = workspace / "app.py"
        path.write_text("from thing.nope import load\n", encoding="utf-8")
        monkeypatch.setattr(check, "REPO_ROOT", workspace)
        monkeypatch.setattr(
            check, "source_roots", lambda: {"thing": workspace / "packages/thing/src/thing"}
        )
        monkeypatch.setattr(check, "source_files", lambda: [path])
        assert check.main() == 1
        out = capsys.readouterr().out
        assert "thing.nope" in out
        assert "cross-package-imports: allow <reason>" in out

    def test_finding_no_packages_at_all_is_a_failure(self, check, monkeypatch, capsys):
        """An empty root map would let this report "ok" while resolving nothing
        -- the same false green as a gate that never ran."""
        monkeypatch.setattr(check, "source_roots", dict)
        assert check.main() == 1
        assert "no first-party packages" in capsys.readouterr().err

    def test_finding_no_files_at_all_is_a_failure(self, check, monkeypatch, capsys):
        monkeypatch.setattr(check, "source_files", list)
        assert check.main() == 1
        assert "no first-party Python files" in capsys.readouterr().err


class TestOnlyModuleScopeCounts:
    """#413. `_names_in` walked the whole tree, so a local variable inside a
    function counted as a module attribute and `from target import local_name`
    resolved against something no importer can reach — the exact
    missing-attribute case this gate exists to catch, passing it."""

    def test_a_function_local_is_not_a_module_attribute(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "local.py").write_text(
            "def build():\n    helper = 1\n    return helper\n", encoding="utf-8"
        )
        (finding,) = _scan(check, workspace, "from thing.local import helper\n")
        assert finding.target == "thing.local.helper"

    def test_a_name_imported_only_inside_a_function_is_not_either(self, check, workspace):
        """The shape that made the old behaviour plausible: the name *is* in the
        file, just not reachable from outside."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "lazy.py").write_text(
            "def go():\n    from json import dumps\n    return dumps\n", encoding="utf-8"
        )
        assert [f.target for f in _scan(check, workspace, "from thing.lazy import dumps\n")] == [
            "thing.lazy.dumps"
        ]

    def test_a_class_attribute_is_not_a_module_attribute(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "cls.py").write_text("class Holder:\n    VALUE = 1\n", encoding="utf-8")
        assert [f.target for f in _scan(check, workspace, "from thing.cls import VALUE\n")] == [
            "thing.cls.VALUE"
        ]
        assert _scan(check, workspace, "from thing.cls import Holder\n") == []

    def test_a_name_bound_in_a_module_level_try_still_counts(self, check, workspace):
        """`try: import x except ImportError: x = None` is how these packages
        do optional dependencies. Still module scope, so still an attribute."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "opt.py").write_text(
            "try:\n    from json import dumps\nexcept ImportError:\n    dumps = None\n",
            encoding="utf-8",
        )
        assert _scan(check, workspace, "from thing.opt import dumps\n") == []

    def test_a_name_bound_under_type_checking_is_not_a_runtime_name(self, check, workspace):
        """#413 review. The block never executes, so a runtime import of that
        name fails — and an earlier version of this test asserted the opposite,
        which was a false green written into the suite.

        `maistro.archive` is the live instance: it declares `S3ArchiveStore`
        under TYPE_CHECKING and serves it from a `__getattr__`. Accepting the
        type-only binding would pass a runtime import with that `__getattr__`
        deleted."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "tc.py").write_text(
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    Alias = int\n",
            encoding="utf-8",
        )
        (finding,) = _scan(check, workspace, "from thing.tc import Alias\n")
        assert "only under TYPE_CHECKING" in finding.reason

    def test_a_type_checking_import_may_use_a_type_only_name(self, check, workspace):
        """The other half of the rule: an importer that is itself under
        TYPE_CHECKING only has to satisfy a type checker."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "tc.py").write_text(
            "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    Alias = int\n",
            encoding="utf-8",
        )
        body = (
            "from typing import TYPE_CHECKING\n\n"
            "if TYPE_CHECKING:\n    from thing.tc import Alias\n"
        )
        assert _scan(check, workspace, body) == []

    def test_an_else_branch_of_type_checking_is_runtime(self, check, workspace):
        """`if TYPE_CHECKING: ... else: ...` — the else runs."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "both.py").write_text(
            "from typing import TYPE_CHECKING\n\n"
            "if TYPE_CHECKING:\n    Only = int\nelse:\n    Real = 1\n",
            encoding="utf-8",
        )
        assert _scan(check, workspace, "from thing.both import Real\n") == []

    def test_a_getattr_export_is_trusted_as_far_as_dunder_all(self, check, workspace):
        """A module-level `__getattr__` can produce names no static read finds,
        so what it publishes in `__all__` counts as runtime-present."""
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "lazy.py").write_text(
            '__all__ = ["Widget"]\n\n\ndef __getattr__(name):\n    raise AttributeError(name)\n',
            encoding="utf-8",
        )
        assert _scan(check, workspace, "from thing.lazy import Widget\n") == []

    def test_a_getattr_without_dunder_all_publishes_nothing_verifiable(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "opaque.py").write_text(
            "def __getattr__(name):\n    raise AttributeError(name)\n", encoding="utf-8"
        )
        assert [f.target for f in _scan(check, workspace, "from thing.opaque import X\n")] == [
            "thing.opaque.X"
        ]

    def test_a_tuple_unpack_at_module_scope_counts(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "tup.py").write_text("LEFT, RIGHT = 1, 2\n", encoding="utf-8")
        assert _scan(check, workspace, "from thing.tup import LEFT\n") == []

    def test_an_annotated_assignment_counts(self, check, workspace):
        pkg = workspace / "packages" / "thing" / "src" / "thing"
        (pkg / "ann.py").write_text("COUNT: int = 3\n", encoding="utf-8")
        assert _scan(check, workspace, "from thing.ann import COUNT\n") == []


class TestTheScanCoversWhatItClaims:
    """#413. The docstring promised "every first-party Python file, tests
    included" and gave the reason — a missing *name* can sit inside a
    `pytest.raises` and never say so — while the glob covered `packages/`
    only. The repository's own root trees, including the ones that reason
    names, were outside a check advertised as covering them."""

    def test_the_root_test_tree_is_scanned(self, check):
        files = {str(p.relative_to(check.REPO_ROOT)) for p in check.source_files()}
        assert "tests/test_check_cross_package_imports.py" in files

    def test_the_tools_tree_is_scanned(self, check):
        """#413 review. `tools/` holds first-party importers too — one of its
        scripts is run by a workflow — so leaving it out kept the same
        overclaim alive one directory over."""
        files = {str(p.relative_to(check.REPO_ROOT)) for p in check.source_files()}
        assert any(f.startswith("tools/") for f in files)

    def test_the_scripts_tree_is_scanned(self, check):
        """A gate that cannot import what it names is a gate that does not run,
        and #262 is the record of what an absent check looks like."""
        files = {str(p.relative_to(check.REPO_ROOT)) for p in check.source_files()}
        assert "scripts/check-ac-state.py" in files

    def test_the_packages_tree_is_still_scanned(self, check):
        files = {str(p.relative_to(check.REPO_ROOT)) for p in check.source_files()}
        assert "packages/hive-conductor/backend/services/design_service.py" in files

    def test_widening_did_not_cost_coverage_elsewhere(self, check):
        """Measured when the roots were added: 207 further files, zero new
        findings. If this ever drops, a tree stopped being scanned."""
        assert len(check.source_files()) > 2000
