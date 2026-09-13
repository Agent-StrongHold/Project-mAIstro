"""Mutation coverage for workflow quality floors (#319)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-workflow-ratchets.py"


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("workflow_ratchets_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=test@example.invalid",
        "-c",
        "user.name=test",
        "commit",
        "-m",
        message,
    )


def _baseline(value: int) -> dict[str, object]:
    return {
        "metric_definition_version": "1",
        "metrics": {
            name: {
                "value": {
                    "coverage": value,
                    "xenon": 77,
                    "pyright": 21,
                    "interrogate:graph/nodes": 38,
                    "interrogate:graph/durable_runs": 45,
                    "interrogate:projects": 63,
                    "interrogate:all": 46,
                }[name],
                "direction": direction,
                "unit": unit,
                "tool": tool,
            }
            for name, (direction, tool, unit) in {
                "coverage": ("minimum", "coverage report --format=total", "percent"),
                "xenon": (
                    "maximum",
                    "xenon --max-absolute B --max-modules B --max-average A",
                    "count",
                ),
                "pyright": ("maximum", "pyright --outputjson packages/maistro-core/src", "errors"),
                "interrogate:graph/nodes": (
                    "minimum",
                    "interrogate -f 0 -v graph/nodes",
                    "percent",
                ),
                "interrogate:graph/durable_runs": (
                    "minimum",
                    "interrogate -f 0 -v graph/durable_runs",
                    "percent",
                ),
                "interrogate:projects": ("minimum", "interrogate -f 0 -v projects", "percent"),
                "interrogate:all": ("minimum", "interrogate -f 0 -v maistro", "percent"),
            }.items()
        },
    }


def test_candidate_floor_edit_cannot_rewrite_trusted_floor(
    checker, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    path = repo / "quality" / "workflow-ratchet-baseline.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_baseline(87)) + "\n", encoding="utf-8")
    _commit(repo, "trusted workflow floors")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "-b", "candidate")

    payload = _baseline(88)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    _commit(repo, "weaken floor beside the candidate regression")

    assert checker._trusted_floors(repo)["coverage"].value == 87
    monkeypatch.setattr(checker, "_measure", lambda _name, root: 86)
    assert checker.check("coverage", root=repo) == 1


def test_candidate_floor_reduction_is_rejected(checker, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    path = repo / "quality" / "workflow-ratchet-baseline.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_baseline(87)) + "\n", encoding="utf-8")
    _commit(repo, "trusted workflow floors")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "-b", "candidate")
    path.write_text(json.dumps(_baseline(1)) + "\n", encoding="utf-8")
    _commit(repo, "weaken the candidate floor")

    with pytest.raises(checker.WorkflowRatchetError, match="weakens the trusted floor"):
        checker._trusted_floors(repo)


def test_first_migration_reads_legacy_floors_from_the_trusted_tree(checker) -> None:
    floors = checker._trusted_floors(ROOT)

    assert floors["coverage"].value == 87
    assert floors["xenon"].value == 77
    assert floors["pyright"].value == 21
    assert floors["interrogate:all"].value == 46


def test_new_workflow_floor_has_no_implicit_empty_trusted_baseline(checker, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _commit(repo, "no quality floor yet")
    _git(repo, "remote", "add", "origin", str(repo))
    _git(repo, "fetch", "-q", "origin")
    _git(repo, "checkout", "-q", "-b", "candidate")
    path = repo / "quality" / "workflow-ratchet-baseline.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_baseline(87)) + "\n", encoding="utf-8")
    _commit(repo, "introduce candidate-controlled floor")

    with pytest.raises(checker.WorkflowRatchetError, match="absent at the trusted base"):
        checker._trusted_floors(repo)


def test_measured_regression_fails_against_the_trusted_floor(checker, monkeypatch) -> None:
    reference = checker._provenance().Baseline(
        text="{}", origin="base", base_sha="a" * 40, path=Path("baseline.json")
    )
    floor = checker.TrustedFloor(reference, 87, "minimum", "coverage", "percent")
    monkeypatch.setattr(checker, "_trusted_floors", lambda _root: {"coverage": floor})
    monkeypatch.setattr(checker, "_measure", lambda _name, root: 86)

    assert checker.check("coverage", root=ROOT) == 1
