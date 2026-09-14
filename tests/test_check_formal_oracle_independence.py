"""The formal security oracle cannot be rewritten with its implementation."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-formal-oracle-independence.py"
spec = importlib.util.spec_from_file_location("check_formal_oracle_independence", SCRIPT)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = checker
spec.loader.exec_module(checker)


ORACLE = "formal/fixtures/security_oracle.json"
IMPLEMENTATION = "packages/maistro-core/src/maistro/security/patterns.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=test@example.com", "-c", "user.name=test", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repository(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "develop")
    for path in (ORACLE, IMPLEMENTATION):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("base\n", encoding="utf-8")
    base = _commit(repo, "trusted base")
    return repo, base


def test_candidate_cochange_is_rejected(repository: tuple[Path, str]) -> None:
    repo, base = repository
    (repo / ORACLE).write_text("candidate oracle\n", encoding="utf-8")
    (repo / IMPLEMENTATION).write_text("candidate implementation\n", encoding="utf-8")
    _commit(repo, "co-change")

    paths = checker.changed_paths(base, root=repo)

    assert checker.violations(paths)


def test_oracle_only_change_is_allowed(repository: tuple[Path, str]) -> None:
    repo, base = repository
    (repo / ORACLE).write_text("new governed cases\n", encoding="utf-8")
    _commit(repo, "oracle-only change")

    assert checker.violations(checker.changed_paths(base, root=repo)) == []


def test_unresolvable_base_fails_closed(repository: tuple[Path, str]) -> None:
    repo, _base = repository

    with pytest.raises(checker.OracleIndependenceError, match="not found"):
        checker.changed_paths("not-a-commit", root=repo)
