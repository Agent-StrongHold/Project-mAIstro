"""The promotion-surface derivation, and the ways a candidate could evade it (#303).

`SENSITIVE_PATH_PATTERNS` used to be a hand-written list, and it was wrong three
times over: `local_loop.py` fast-forwards the baseline, `merge.py` decides which
candidates land, `code_fixer.py` executes candidate code, and none of them
escalated. These tests cover the derivation that replaces the enumeration, and
each named evasion in the issue's acceptance criteria.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check-promotion-surface.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_promotion_surface", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before execution: `@dataclass` under `from __future__ import
    # annotations` resolves its field types through `sys.modules[__name__]`,
    # and a module loaded by path is not there unless we put it there.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    return _module()


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body), encoding="utf-8")


@pytest.fixture
def tree(tmp_path: Path, checker: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A miniature repo with the same shape as the real one."""
    src = tmp_path / "packages" / "pkg" / "src"
    _write(src / "loop" / "__init__.py", "")
    _write(src / "loop" / "promote.py", "from helper import util\n")
    _write(src / "helper" / "__init__.py", "")
    _write(src / "helper" / "util.py", "")
    monkeypatch.setattr(checker, "REPO", tmp_path)
    monkeypatch.setattr(checker, "BASELINE_PATH", tmp_path / "quality" / "baseline.json")
    monkeypatch.setattr(checker, "PROMOTION_ROOTS", {"loop.promote": "promotes"})
    return tmp_path


class TestTheRealDefect:
    """The three modules #303 names, against the shipped patterns."""

    @pytest.mark.parametrize(
        "path",
        [
            "packages/maistro-rsi/src/maistro_rsi/local_loop.py",
            "packages/maistro-rsi/src/maistro_rsi/merge.py",
            "packages/maistro-rsi/src/maistro_rsi/code_fixer.py",
        ],
    )
    def test_the_promotion_appliers_escalate(self, checker: ModuleType, path: str) -> None:
        assert checker._matcher()(path)

    def test_they_are_reachable_from_the_declared_roots(self, checker: ModuleType) -> None:
        """Not merely protected — protected *because* the derivation reaches them.

        A pattern added by hand would pass the test above while leaving the
        method that produced the omission untouched.
        """
        modules = checker.index_modules()
        closure = checker.reachable(checker.PROMOTION_ROOTS, modules)

        assert {"maistro_rsi.local_loop", "maistro_rsi.merge", "maistro_rsi.code_fixer"} <= closure


class TestTheRepositoryPasses:
    def test_the_real_tree_has_no_gap(self, checker: ModuleType) -> None:
        findings, _ = checker.audit()

        assert findings == [], "\n".join(str(f) for f in findings)

    def test_every_tolerated_module_carries_a_reason(self, checker: ModuleType) -> None:
        """A baseline entry with an empty reason is an allowlist entry."""
        for path, reason in checker.load_baseline().items():
            assert reason.strip(), path
            assert not reason.startswith("TODO"), path

    def test_every_declared_root_resolves(self, checker: ModuleType) -> None:
        modules = checker.index_modules()

        assert [r for r in checker.PROMOTION_ROOTS if r not in modules] == []

    def test_each_root_states_why_it_is_one(self, checker: ModuleType) -> None:
        for root, why in checker.PROMOTION_ROOTS.items():
            assert why.strip(), root


class TestReachability:
    def test_an_import_pulls_its_target_into_the_closure(
        self, tree: Path, checker: ModuleType
    ) -> None:
        closure = checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules())

        # `helper` itself, not only `helper.util`: `from helper import util`
        # executes the package's `__init__.py`, which can re-export anything it
        # likes. A closure that skipped packages would leave that unprotected.
        assert closure == {"loop.promote", "helper", "helper.util"}

    def test_an_unimported_module_stays_out(self, tree: Path, checker: ModuleType) -> None:
        _write(tree / "packages" / "pkg" / "src" / "helper" / "unused.py", "")

        assert "helper.unused" not in checker.reachable(
            checker.PROMOTION_ROOTS, checker.index_modules()
        )

    def test_the_walk_is_transitive(self, tree: Path, checker: ModuleType) -> None:
        src = tree / "packages" / "pkg" / "src"
        _write(src / "helper" / "util.py", "from helper import deep\n")
        _write(src / "helper" / "deep.py", "")

        assert "helper.deep" in checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules())

    def test_an_import_cycle_terminates(self, tree: Path, checker: ModuleType) -> None:
        src = tree / "packages" / "pkg" / "src"
        _write(src / "helper" / "util.py", "from loop import promote\n")

        assert checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules()) == {
            "loop",
            "loop.promote",
            "helper",
            "helper.util",
        }

    def test_a_third_party_import_is_not_walked(self, tree: Path, checker: ModuleType) -> None:
        """Only first-party source is indexed, so `import httpx` resolves to nothing."""
        src = tree / "packages" / "pkg" / "src"
        _write(src / "loop" / "promote.py", "import httpx\nimport json\n")

        assert checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules()) == {
            "loop.promote"
        }


class TestTheEvasions:
    """Each acceptance criterion's named bypass, as an executable case."""

    def test_an_aliased_import_is_still_followed(self, tree: Path, checker: ModuleType) -> None:
        """`import x as y` records `x`: the AST keeps the real name."""
        src = tree / "packages" / "pkg" / "src"
        _write(src / "loop" / "promote.py", "import helper.util as anything_else\n")

        assert "helper.util" in checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules())

    def test_a_generated_wrapper_is_pulled_in_with_its_importer(
        self, tree: Path, checker: ModuleType
    ) -> None:
        """Routing promotion through a new module does not move it off the surface.

        For the wrapper to have any effect something in the closure must import
        it, and that import is what puts it in the closure.
        """
        src = tree / "packages" / "pkg" / "src"
        _write(src / "loop" / "promote.py", "from shim import wrapper\n")
        _write(src / "shim" / "__init__.py", "")
        _write(src / "shim" / "wrapper.py", "from helper import util\n")

        closure = checker.reachable(checker.PROMOTION_ROOTS, checker.index_modules())

        assert {"shim.wrapper", "helper.util"} <= closure

    def test_a_rename_is_followed_because_the_graph_is_not_path_based(
        self, tree: Path, checker: ModuleType
    ) -> None:
        src = tree / "packages" / "pkg" / "src"
        (src / "helper" / "util.py").rename(src / "helper" / "renamed.py")
        _write(src / "loop" / "promote.py", "from helper import renamed\n")

        assert "helper.renamed" in checker.reachable(
            checker.PROMOTION_ROOTS, checker.index_modules()
        )

    def test_a_symlinked_source_file_is_reported(self, tree: Path, checker: ModuleType) -> None:
        """A symlink lets one file be edited under two names, so the path a diff
        declares stops being the path a reviewer classified."""
        src = tree / "packages" / "pkg" / "src"
        (src / "helper" / "util.py").unlink()
        (src / "helper" / "util.py").symlink_to(src / "loop" / "promote.py")

        modules = checker.index_modules()
        findings = checker._symlinked_sources({"helper.util"}, modules)

        assert [f.detail for f in findings] == ["source file is a symlink"]

    def test_deleting_a_root_fails_rather_than_shrinking_the_walk(
        self, tree: Path, checker: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The one omission the derivation cannot fix for itself."""
        monkeypatch.setattr(checker, "PROMOTION_ROOTS", {"loop.gone": "promotes"})

        findings, tolerated = checker.audit()

        assert tolerated == []
        assert len(findings) == 1
        assert "declared promotion root does not exist" in findings[0].detail


class TestTheLedgerIsCheckedBothWays:
    def _baseline(self, tree: Path, checker: ModuleType, tolerated: dict[str, str]) -> None:
        checker.BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        checker.BASELINE_PATH.write_text(json.dumps({"tolerated": tolerated}), encoding="utf-8")

    def test_an_unprotected_reachable_module_fails(self, tree: Path, checker: ModuleType) -> None:
        findings, _ = checker.audit()

        assert {f.path for f in findings} == {
            "packages/pkg/src/loop/promote.py",
            "packages/pkg/src/helper/__init__.py",
            "packages/pkg/src/helper/util.py",
        }

    def test_a_baselined_module_is_tolerated_and_printed(
        self, tree: Path, checker: ModuleType
    ) -> None:
        self._baseline(
            tree,
            checker,
            {
                "packages/pkg/src/helper/__init__.py": "an empty package marker",
                "packages/pkg/src/helper/util.py": "a data carrier",
                "packages/pkg/src/loop/promote.py": "under test",
            },
        )

        findings, tolerated = checker.audit()

        assert findings == []
        assert len(tolerated) == 3
        assert any("a data carrier" in line for line in tolerated)

    def test_a_baselined_module_that_became_protected_fails(
        self, tree: Path, checker: ModuleType, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Otherwise the file quietly becomes a permanent allowlist."""
        self._baseline(
            tree,
            checker,
            {
                "packages/pkg/src/helper/__init__.py": "an empty package marker",
                "packages/pkg/src/helper/util.py": "a data carrier",
                "packages/pkg/src/loop/promote.py": "under test",
            },
        )
        monkeypatch.setattr(checker, "_matcher", lambda: lambda path: "helper/" in path)

        findings, _ = checker.audit()

        assert [f.path for f in findings] == [
            "packages/pkg/src/helper/__init__.py",
            "packages/pkg/src/helper/util.py",
        ]
        assert all("delete the entry" in f.detail for f in findings)

    def test_a_baselined_module_that_left_the_closure_fails(
        self, tree: Path, checker: ModuleType
    ) -> None:
        """A stale entry would otherwise silently re-tolerate a later re-entry."""
        self._baseline(
            tree,
            checker,
            {
                "packages/pkg/src/helper/__init__.py": "an empty package marker",
                "packages/pkg/src/helper/util.py": "a data carrier",
                "packages/pkg/src/loop/promote.py": "under test",
                "packages/pkg/src/helper/gone.py": "deleted long ago",
            },
        )

        findings, _ = checker.audit()

        assert [f.path for f in findings] == ["packages/pkg/src/helper/gone.py"]
        assert "no longer reachable" in findings[0].detail


class TestTheClassifierIsProtectedWithItsTests:
    """AC: a candidate cannot modify the classifier or its tests in the same
    change used to authorize itself."""

    @pytest.mark.parametrize(
        "path",
        [
            "packages/maistro-rsi/src/maistro_rsi/sensitive_paths.py",
            "packages/maistro-rsi/src/maistro_rsi/quarantine.py",
            "packages/maistro-rsi/tests/test_quarantine.py",
            "packages/maistro-rsi/tests/test_sensitive_paths.py",
            "scripts/check-promotion-surface.py",
            "scripts/check_enumerations.py",
            "tests/test_check_promotion_surface.py",
            "tests/test_check_enumerations.py",
        ],
    )
    def test_the_gate_and_its_evidence_escalate(self, checker: ModuleType, path: str) -> None:
        assert checker._matcher()(path)


class TestTheCommandLine:
    def test_a_clean_tree_exits_zero(self, checker: ModuleType, capsys) -> None:
        assert checker.main([]) == 0
        assert "promotion surface: ok" in capsys.readouterr().out

    def test_a_gap_exits_one_and_names_the_remedy(
        self, tree: Path, checker: ModuleType, capsys
    ) -> None:
        assert checker.main([]) == 1
        captured = capsys.readouterr()
        assert "promotion-surface gap" in captured.err
        assert "sensitive_paths.py" in captured.err

    def test_write_baseline_records_the_gaps_with_a_placeholder_reason(
        self, tree: Path, checker: ModuleType
    ) -> None:
        assert checker.main(["--write-baseline"]) == 0

        tolerated = json.loads(checker.BASELINE_PATH.read_text())["tolerated"]
        assert set(tolerated) == {
            "packages/pkg/src/helper/__init__.py",
            "packages/pkg/src/helper/util.py",
            "packages/pkg/src/loop/promote.py",
        }
        # A placeholder, not a reason — and `test_every_tolerated_module_carries
        # _a_reason` above is what refuses to let one reach the repository.
        assert all(reason.startswith("TODO") for reason in tolerated.values())

    def test_write_baseline_keeps_reasons_already_written(
        self, tree: Path, checker: ModuleType
    ) -> None:
        checker.BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
        checker.BASELINE_PATH.write_text(
            json.dumps({"tolerated": {"packages/pkg/src/helper/util.py": "a data carrier"}}),
            encoding="utf-8",
        )

        checker.main(["--write-baseline"])

        tolerated = json.loads(checker.BASELINE_PATH.read_text())["tolerated"]
        assert tolerated["packages/pkg/src/helper/util.py"] == "a data carrier"
