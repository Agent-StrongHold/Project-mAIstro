"""The formal security oracle cannot be rewritten with its implementation."""

from __future__ import annotations

import importlib.util
import runpy
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


def test_violations_need_the_oracle_to_change() -> None:
    """Without an oracle change in the diff there is nothing to flag, and the
    absent-at-base exception means an oracle-only diff is an initial landing,
    not a co-change — both early-return before naming implementation paths."""
    assert checker.violations({"docs/notes.md"}) == []
    assert checker.violations({ORACLE, IMPLEMENTATION}, oracle_at_base=False) == []


def test_oracle_presence_at_base_is_read_from_git(
    repository: tuple[Path, str],
) -> None:
    """`oracle_exists_at_base` asks git, and answers False when the trusted
    base predates the governed fixture."""
    repo, base = repository
    assert checker.oracle_exists_at_base(base, root=repo) is True

    bare = repo.parent / "bare"
    bare.mkdir()
    _git(bare, "init", "-q", "-b", "develop")
    doc = bare / "docs" / "x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("x\n", encoding="utf-8")
    bare_base = _commit(bare, "no oracle here")

    assert checker.oracle_exists_at_base(bare_base, root=bare) is False


def test_unreadable_diff_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A base that resolves but a diff that fails is an error, not an empty
    change set — both the reported message and the bare-stderr fallback."""
    real_run = checker.subprocess.run
    failures = iter(["git exploded", ""])

    def fake_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if cmd[1] == "diff":
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr=next(failures))
        return real_run(cmd, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    with pytest.raises(checker.OracleIndependenceError, match="git exploded"):
        checker.changed_paths("HEAD")
    with pytest.raises(checker.OracleIndependenceError, match="git diff failed"):
        checker.changed_paths("HEAD")


def test_main_rejects_a_co_change(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The violation path: exit 1 and the co-change named on stderr."""
    monkeypatch.setattr(checker, "changed_paths", lambda base: {ORACLE, IMPLEMENTATION})
    monkeypatch.setattr(checker, "oracle_exists_at_base", lambda base: True)

    assert checker.main(["--base", "origin/base"]) == 1
    assert "cannot change with security conformance implementation" in capsys.readouterr().err


def test_main_accepts_separated_changes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(checker, "changed_paths", lambda base: {"docs/notes.md"})
    monkeypatch.setattr(checker, "oracle_exists_at_base", lambda base: True)

    assert checker.main(["--base", "origin/base"]) == 0
    assert "OK" in capsys.readouterr().out


def test_main_allows_the_initial_oracle_landing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An oracle diff against a base that predates the fixture is the one
    allowed co-establishment, and says so."""
    monkeypatch.setattr(checker, "changed_paths", lambda base: {ORACLE})
    monkeypatch.setattr(checker, "oracle_exists_at_base", lambda base: False)

    assert checker.main(["--base", "origin/base"]) == 0
    assert "initial oracle contract" in capsys.readouterr().out


def test_main_reports_an_unreadable_diff_as_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(base: str) -> set[str]:
        raise checker.OracleIndependenceError("boom")

    monkeypatch.setattr(checker, "changed_paths", broken)

    assert checker.main(["--base", "origin/base"]) == 2
    assert "ERROR: boom" in capsys.readouterr().err


def test_main_requires_a_base(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("FORMAL_ORACLE_BASE", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        checker.main([])

    assert excinfo.value.code == 2
    assert "--base or FORMAL_ORACLE_BASE is required" in capsys.readouterr().err


def test_main_base_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_changed_paths(base: str) -> set[str]:
        seen.append(base)
        return set()

    monkeypatch.setenv("FORMAL_ORACLE_BASE", "HEAD")
    monkeypatch.setattr(checker, "changed_paths", fake_changed_paths)
    monkeypatch.setattr(checker, "oracle_exists_at_base", lambda base: True)

    assert checker.main([]) == 0
    assert seen == ["HEAD"]


def test_the_script_runs_as_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    """The `__main__` guard: CI shells out, so a file that imports but does
    not run would pass every test above and still fail the pipeline. `HEAD`
    against this checkout is a read-only no-op diff that must exit 0."""
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--base", "HEAD"])

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(str(SCRIPT), run_name="__main__")

    assert excinfo.value.code == 0
