#!/usr/bin/env python3
"""One-shot branch reconciler for issue #267. Deleted by its workflow after success."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def patch_ac_state() -> None:
    p = ROOT / "scripts/check-ac-state.py"
    text = p.read_text()
    if "HIVE_BACKEND_TESTS =" not in text:
        text = text.replace(
            'PYPROJECT = ROOT / "pyproject.toml"\n',
            'PYPROJECT = ROOT / "pyproject.toml"\n'
            'HIVE_BACKEND_TESTS = ROOT / "packages" / "hive-conductor" / "backend" / "tests"\n',
        )

    start = text.index("def configured_test_roots() -> list[Path]:")
    end = text.index("\n\n@dataclass\nclass Criterion:", start)
    configured = '''def configured_test_roots() -> list[Path]:
    """Every test tree that has an executable acceptance-evidence recipe.

    Root pytest ``testpaths`` remain the ordinary monorepo recipe. Hive is
    intentionally separate: its backend is a flat-module application whose
    conftest must put ``backend/`` first on ``sys.path``, and it owns extra
    test dependencies such as pytest-bdd. Combining it with the root session
    recreates the module-shadowing/collection failure that #267 identified.

    ``packages/hive-conductor/tests/e2e`` is not included: it is a Playwright
    suite, not a pytest evidence recipe. A future E2E acceptance adapter can
    add it only when it can report criterion outcomes with the same fail-loud
    semantics as the pytest plugin.
    """
    with PYPROJECT.open("rb") as handle:
        paths = tomllib.load(handle)["tool"]["pytest"]["ini_options"]["testpaths"]
    return [*(ROOT / p for p in paths), HIVE_BACKEND_TESTS]
'''
    text = text[:start] + configured + text[end:]

    start = text.index("def passing_ac_ids(test_roots: list[Path]) -> set[str] | None:")
    end = text.index("\n\ndef load_unreachable()", start)
    passing = '''def passing_ac_ids(test_roots: list[Path]) -> set[str] | None:
    """AC ids whose every claiming test passed across every test recipe.

    Each independently executable suite runs in its own pytest process. A
    criterion claimed in more than one recipe passes only when it passes in
    all of them. If any recipe aborts collection or otherwise does not finish,
    the whole passing rung is unmeasured rather than fabricating failures from
    a partial outcome map.
    """
    roots = [r for r in test_roots if r.exists()]
    if not roots:
        return None

    root_roots = [r for r in roots if r != HIVE_BACKEND_TESTS]
    recipes: list[tuple[str, Path, list[Path]]] = []
    if root_roots:
        recipes.append(("root", ROOT, root_roots))
    if HIVE_BACKEND_TESTS in roots:
        recipes.append(("hive-conductor", ROOT, [HIVE_BACKEND_TESTS]))

    claimed_all: set[str] = set()
    failed_anywhere: set[str] = set()
    for recipe_name, cwd, recipe_roots in recipes:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "ac-outcomes.json"
            prior_pythonpath = os.environ.get("PYTHONPATH", "")
            pythonpath = str(ROOT / "scripts")
            if prior_pythonpath:
                pythonpath += os.pathsep + prior_pythonpath
            env = {**os.environ, "AC_OUTCOME_JSON": str(out), "PYTHONPATH": pythonpath}
            args = [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "ac_outcome_plugin",
                "-p",
                "no:randomly",
                "-q",
                "--no-header",
                "-m",
                "ac",
                *(str(r) for r in recipe_roots),
            ]
            try:
                proc = subprocess.run(
                    args, capture_output=True, text=True, timeout=1800, cwd=cwd, env=env
                )
            except (OSError, subprocess.TimeoutExpired):
                return None
            if proc.returncode not in (0, 1) or not out.is_file():
                sys.stderr.write(
                    f"{recipe_name} pytest exited {proc.returncode}; "
                    "the passing rung is unmeasured.\n"
                    f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}\n"
                )
                return None
            payload = json.loads(out.read_text(encoding="utf-8"))
            claimed = set(payload["claimed"])
            passing = set(payload["passing"])
            claimed_all.update(claimed)
            failed_anywhere.update(claimed - passing)

    return claimed_all - failed_anywhere
'''
    p.write_text(text[:start] + passing + text[end:])


def patch_quality() -> None:
    p = ROOT / ".github/workflows/quality.yml"
    text = p.read_text()
    if "install Hive acceptance-test dependencies" in text:
        return
    needle = "      - name: install maistro-evolve\n        run: uv pip install -e packages/maistro-evolve\n"
    replacement = needle + (
        "\n      # check-ac-state executes Hive AC tests as an isolated recipe (#267).\n"
        "      - name: install Hive acceptance-test dependencies\n"
        "        run: uv pip install -r packages/hive-conductor/backend/requirements.txt\n"
    )
    if needle not in text:
        raise RuntimeError("quality.yml install anchor moved")
    p.write_text(text.replace(needle, replacement, 1))


def patch_adr() -> None:
    p = ROOT / "docs/adr/ADR-082226-ff3c-design-coverage-metric.md"
    text = p.read_text()
    if "AC-8: services.scheduler" not in text:
        text = text.replace(
            "  AC-7: scripts/check-ac-state.py\n",
            "  AC-7: scripts/check-ac-state.py\n  AC-8: services.scheduler\n",
            1,
        )
        text = text.replace(
            "  - tests/test_check_ac_state.py\n",
            "  - tests/test_check_ac_state.py\n"
            "  - tests/test_check_ac_state_hive_recipes.py\n"
            "  - packages/hive-conductor/backend/tests/test_ac_evidence_recipe.py\n",
            1,
        )
        anchor = (
            "`reachable` and not `passing` is the bar: a passing test whose module the import\n"
            "graph cannot reach proves the test runs, not that the system does.\n"
        )
        addition = anchor + '''

**Acceptance evidence may have more than one executable test recipe.** The root
pytest `testpaths` remain one recipe; the Hive backend is a second, isolated
recipe because it is a flat-module application with its own dependency set and
`sys.path` ordering. Markers are scanned only from trees that have such a recipe,
and every recipe must finish successfully enough to produce a complete outcome
map. An aborted collection makes the passing rung unmeasured for the whole run,
never an empty set of failures. The Playwright Hive E2E tree is not pytest
evidence and remains outside this ladder until an outcome adapter exists for it.
'''
        if anchor not in text:
            raise RuntimeError("ADR decision anchor moved")
        text = text.replace(anchor, addition, 1)
        text = text.replace(
            "- [x] **AC-7** The banked precision resolves the smallest move a single\n  criterion can make.",
            "- [x] **AC-7** The banked precision resolves the smallest move a single\n"
            "  criterion can make.\n"
            "- [x] **AC-8** A criterion about a reachable Hive backend module can be\n"
            "  proven by an AC-marked Hive test without joining Hive to the root pytest\n"
            "  session; if that isolated recipe aborts, the passing rung is unmeasured.",
            1,
        )
    p.write_text(text)


def write_tests_and_note() -> None:
    (ROOT / "tests/test_check_ac_state_hive_recipes.py").write_text('''"""Regression tests for #267's independently executable AC recipes."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-ac-state.py"


@pytest.fixture()
def check():
    spec = importlib.util.spec_from_file_location("check_ac_state_hive_recipes", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_configured_roots_include_hive_without_replacing_root_testpaths(check) -> None:
    roots = check.configured_test_roots()
    assert check.HIVE_BACKEND_TESTS in roots
    assert check.ROOT / "tests" in roots
    assert check.ROOT / "packages" not in roots


def test_a_failure_in_one_recipe_sinks_a_cross_recipe_claim(check, monkeypatch, tmp_path) -> None:
    root_tests = tmp_path / "root-tests"
    hive_tests = tmp_path / "hive-tests"
    root_tests.mkdir()
    hive_tests.mkdir()
    monkeypatch.setattr(check, "HIVE_BACKEND_TESTS", hive_tests)
    calls = 0

    def fake_run(args, *, capture_output, text, timeout, cwd, env):
        nonlocal calls
        calls += 1
        payload = {"claimed": ["ADR-X/AC-1"], "passing": ["ADR-X/AC-1"]}
        if hive_tests.as_posix() in args:
            payload["passing"] = []
        Path(env["AC_OUTCOME_JSON"]).write_text(json.dumps(payload))
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(check.subprocess, "run", fake_run)
    assert check.passing_ac_ids([root_tests, hive_tests]) == set()
    assert calls == 2


def test_collection_abort_in_hive_makes_passing_unmeasured(check, monkeypatch, tmp_path) -> None:
    root_tests = tmp_path / "root-tests"
    hive_tests = tmp_path / "hive-tests"
    root_tests.mkdir()
    hive_tests.mkdir()
    monkeypatch.setattr(check, "HIVE_BACKEND_TESTS", hive_tests)
    calls = 0

    def fake_run(args, *, capture_output, text, timeout, cwd, env):
        nonlocal calls
        calls += 1
        if calls == 2:
            return subprocess.CompletedProcess(args, 2, stdout="collection error", stderr="")
        Path(env["AC_OUTCOME_JSON"]).write_text(
            json.dumps({"claimed": ["ADR-X/AC-1"], "passing": ["ADR-X/AC-1"]})
        )
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(check.subprocess, "run", fake_run)
    assert check.passing_ac_ids([root_tests, hive_tests]) is None
    assert calls == 2
''')
    (ROOT / "packages/hive-conductor/backend/tests/test_ac_evidence_recipe.py").write_text('''"""Proof that Hive can participate in the repository AC evidence ladder."""
import pytest


@pytest.mark.ac("ADR-082226-ff3c/AC-8")
def test_hive_scheduler_module_is_provable_from_its_isolated_suite() -> None:
    from services import scheduler

    assert scheduler._ScheduleRunner.__module__ == "services.scheduler"
''')
    (ROOT / "docs/testing/inventory-notes/chatgpt-m1-267-hive-ac-evidence.md").write_text('''---
inventory-delta:
  tests/: +3
  packages/hive-conductor/backend/tests: +1
---

# M1 #267 acceptance-evidence recipes

Three root unit tests pin the recipe split, cross-recipe pass folding, and
fail-loud collection semantics. One Hive backend test is the first real
AC-marked criterion in that independently executed suite and proves a reachable
`services.scheduler` module can reach the ladder's top rung.

Hive's Playwright E2E tree is deliberately unchanged: it has no pytest outcome
adapter, so scanning it as though `check-ac-state.py` could execute it would be
another false evidence claim.
''')


if __name__ == "__main__":
    patch_ac_state()
    patch_quality()
    patch_adr()
    write_tests_and_note()
