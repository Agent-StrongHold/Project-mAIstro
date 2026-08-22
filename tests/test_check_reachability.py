"""Tests for the reachability ratchet.

The script is a CI gate, so the property that matters is that it *fails* on a
newly-unreachable module. A gate that silently passes is worse than no gate —
it reads as evidence the defect class is handled.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-reachability.py"
BASELINE = ROOT / "quality" / "reachability-baseline.json"


@pytest.fixture(scope="module")
def check():
    spec = importlib.util.spec_from_file_location("check_reachability", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_baseline_matches_the_tree(check):
    """The committed baseline is the current truth — otherwise the first CI run
    after any merge fails for reasons unrelated to that merge."""
    unreachable, _ = check.unreachable_modules()
    baseline = sorted(json.loads(BASELINE.read_text())["unreachable"])
    stale = sorted(set(baseline) - set(unreachable))
    added = sorted(set(unreachable) - set(baseline))
    if stale:
        print(f"::error title=Reachability baseline stale::{','.join(stale)}")
    if added:
        print(f"::error title=New unreachable modules::{','.join(added)}")
    assert baseline == unreachable


def test_entry_points_are_reachable(check):
    """A graph that roots at nothing reports everything as dead and looks like a
    catastrophic finding. Assert the roots resolved."""
    unreachable, total = check.unreachable_modules()
    assert total > 500
    assert "main" not in unreachable
    assert "maistro.container" not in unreachable
    assert "maistro.conduit" not in unreachable


def test_known_wired_subsystems_are_reachable(check):
    """Regression guard for the wiring this ratchet was built alongside: if any
    of these fall off a call path again, that is the #344/ADR-064 bug returning."""
    unreachable, _ = check.unreachable_modules()
    for mod in (
        "maistro.security.redact",
        "maistro.security.log_redaction",
        "maistro.memory.episodic.decay_driver",
        "maistro.skills.parser",
    ):
        assert mod not in unreachable, f"{mod} lost its production call path"


def test_new_unreachable_module_fails_the_gate(check, tmp_path, monkeypatch, capsys):
    """The gate's whole job. Simulated by shrinking the baseline rather than
    writing a file into packages/, so a crashed test cannot leave a stray module
    behind in the tree."""
    unreachable, _ = check.unreachable_modules()
    assert unreachable, "expected a non-empty baseline to borrow an entry from"

    shrunk = tmp_path / "baseline.json"
    shrunk.write_text(json.dumps({"unreachable": unreachable[1:]}))
    monkeypatch.setattr(check, "BASELINE", shrunk)

    assert check.main() == 1
    assert unreachable[0] in capsys.readouterr().out


def test_module_becoming_reachable_fails_until_the_baseline_is_pruned(
    check, tmp_path, monkeypatch, capsys
):
    """Wiring a module up is good news, and it still has to be banked.

    The baseline is a record of what is *currently* unreachable, so an entry
    that is no longer true is retained slack: it would silently absorb a later
    module going unreachable, and the gate would say nothing. Failing here
    costs one line — delete the stale entry — and the message says which.
    """
    unreachable, _ = check.unreachable_modules()
    grown = tmp_path / "baseline.json"
    grown.write_text(json.dumps({"unreachable": [*unreachable, "maistro.nonexistent_module"]}))
    monkeypatch.setattr(check, "BASELINE", grown)

    assert check.main() == 1
    out = capsys.readouterr().out
    assert "maistro.nonexistent_module" in out
    assert "must shrink" in out


class TestEagerImportSweep:
    """A package that registers its plugins with ``importlib.import_module``.

    The node catalog does this: a literal tuple of sibling module names, imported
    in a loop at package-import time so every kind self-registers. Those imports
    are real — the modules run whenever the package is imported — but an AST walk
    over `import` statements cannot see them, so an honest catalog looked like
    eighteen dead modules. The recogniser must be narrow enough that a wrong
    "reachable" verdict stays impossible, since that is the failure the whole
    gate exists to prevent.
    """

    @staticmethod
    def _sweep(check, source: str) -> set[str]:
        import ast

        return check._eager_sweep(ast.parse(source), "pkg")

    def test_a_name_bound_tuple_swept_in_a_loop_is_followed(self, check):
        source = """
import importlib

def _load():
    module_names = ("alpha", "beta")
    for name in module_names:
        importlib.import_module(f"{__name__}.{name}")
"""
        assert self._sweep(check, source) == {"pkg.alpha", "pkg.beta"}

    def test_an_inline_literal_sequence_is_followed(self, check):
        source = """
from importlib import import_module

def _load():
    for name in ["alpha"]:
        import_module(f"{__name__}.{name}")
"""
        assert self._sweep(check, source) == {"pkg.alpha"}

    def test_a_non_literal_iterable_is_not_guessed_at(self, check):
        """Names computed at run time stay unresolved. Reporting them reachable
        would be a guess, and a wrong one is invisible."""
        source = """
import importlib

def _load():
    for name in discover_plugins():
        importlib.import_module(f"{__name__}.{name}")
"""
        assert self._sweep(check, source) == set()

    def test_a_loop_over_strings_without_the_import_is_not_a_sweep(self, check):
        """Any function may loop over a tuple of strings. Only the one that
        imports them counts."""
        source = """
def _labels():
    for name in ("alpha", "beta"):
        print(name)
"""
        assert self._sweep(check, source) == set()

    def test_a_differently_shaped_interpolation_is_not_matched(self, check):
        """Only ``f"{__name__}.{loop_variable}"`` resolves. A nested or
        prefixed target would name a different module than the one computed."""
        source = """
import importlib

def _load():
    for name in ("alpha",):
        importlib.import_module(f"{__name__}.backends.{name}")
        importlib.import_module(f"other.{name}")
"""
        assert self._sweep(check, source) == set()

    def test_the_loop_variable_must_be_the_one_interpolated(self, check):
        source = """
import importlib

def _load():
    for name in ("alpha",):
        importlib.import_module(f"{__name__}.{other}")
"""
        assert self._sweep(check, source) == set()

    def test_a_flat_module_shadowed_by_a_package_is_refused(self, check, tmp_path):
        """The blind spot this gate could not report on itself. `foo.py` beside
        `foo/__init__.py` never runs — Python resolves the import to the package
        — and because modules are keyed by dotted name, one silently overwrote
        the other and only one was ever analysed."""
        pkg = tmp_path / "packages" / "demo" / "src" / "demo"
        (pkg / "shadowed").mkdir(parents=True)
        (pkg / "shadowed" / "__init__.py").write_text("REAL = 1\n")
        (pkg / "shadowed.py").write_text("DEAD = 1\n")

        with pytest.raises(RuntimeError) as excinfo:
            check._validate_no_shadowed_modules(tmp_path)
        assert "shadowed by a same-named package" in str(excinfo.value)
        assert "shadowed.py" in str(excinfo.value)

    def test_a_directory_without_an_init_does_not_shadow(self, check, tmp_path):
        """A namespace directory loses to a real module, so it is not a
        collision — `hive-conductor/backend/config/` holds only a TOML file
        beside `config.py` and must not fail the build."""
        pkg = tmp_path / "packages" / "demo" / "src" / "demo"
        (pkg / "assets").mkdir(parents=True)
        (pkg / "assets" / "models.toml").write_text("x = 1\n")
        (pkg / "assets.py").write_text("REAL = 1\n")

        check._validate_no_shadowed_modules(tmp_path)

    def test_the_repository_has_no_shadowed_modules(self, check):
        check._validate_no_shadowed_modules(ROOT)

    def test_a_binding_from_another_function_does_not_resolve_a_loop(self, check):
        """The scope leak this recogniser must not have. Hoisting one function's
        locals into module scope would resolve a loop that raises NameError at
        run time — claiming a module reachable on code that cannot execute."""
        source = """
import importlib

def unrelated():
    names = ("ghost",)

def _load():
    for name in names:
        importlib.import_module(f"{__name__}.{name}")
"""
        assert self._sweep(check, source) == set()

    def test_a_module_level_binding_read_inside_a_function_still_resolves(self, check):
        """Closing the leak must not break the legitimate direction: a function
        may read a module-level tuple, and that is ordinary Python scoping."""
        source = """
import importlib

MODULES = ("alpha",)

def _load():
    for name in MODULES:
        importlib.import_module(f"{__name__}.{name}")
"""
        assert self._sweep(check, source) == {"pkg.alpha"}

    def test_the_node_catalog_is_reachable_through_its_sweep(self, check):
        """The regression this recogniser exists for: every node module the
        catalog imports must be reachable, since the catalog itself is."""
        unreachable, _ = check.unreachable_modules()
        swept = [module for module in unreachable if module.startswith("maistro.graph.nodes.")]
        assert swept == []
