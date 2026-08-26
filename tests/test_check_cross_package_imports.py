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
