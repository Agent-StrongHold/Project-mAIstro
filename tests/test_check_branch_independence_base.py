"""Tests for `base_registry` and `main` in check-branch-independence.py (#680).

These build real git repositories rather than faking `git`, because the thing
under test *is* the git plumbing: which commit the trusted base resolves to,
and what happens when that resolution is partial, absent, or unrelated to
HEAD. A mocked `git` would agree with whatever the implementation happened
to do (see tests/test_ratchet_provenance.py for the same reasoning).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check-branch-independence.py"
spec = importlib.util.spec_from_file_location("_branch_independence_base", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

REGISTRY = "quality/branch-independence.json"


def _run(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _commit(repo: Path, message: str) -> str:
    _run(repo, "add", "-A")
    _run(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    return _run(repo, "rev-parse", "HEAD")


def _write(repo: Path, rel: str, payload: object) -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repo whose trunk carries a registry, with `origin/develop` fetched
    (a local clone of ourselves is the cheapest way to have a real
    remote-tracking ref) and a candidate branch one commit ahead of it."""
    monkeypatch.delenv(mod.BASE_ENV, raising=False)
    monkeypatch.delenv(mod.RATCHET_BASE_ENV, raising=False)
    root = tmp_path / "repo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, REGISTRY, {"version": 1, "frozen_legacy_paths": ["quality/old.json"]})
    _commit(root, "trunk registry")
    _run(root, "remote", "add", "origin", str(root))
    _run(root, "fetch", "-q", "origin")
    _run(root, "checkout", "-q", "-b", "candidate")
    _write(root, "work.txt", "candidate work")
    _commit(root, "candidate work")
    return root


def test_reads_the_registry_at_the_implicit_default_base(repo: Path) -> None:
    base = mod.base_registry(repo)

    assert base == {"version": 1, "frozen_legacy_paths": ["quality/old.json"]}


def test_reads_the_registry_at_an_explicit_base(repo: Path) -> None:
    trunk_sha = _run(repo, "rev-parse", "origin/develop")

    base = mod.base_registry(repo, explicit_base=trunk_sha)

    assert base == {"version": 1, "frozen_legacy_paths": ["quality/old.json"]}


def test_returns_none_when_the_implicit_base_ref_is_unresolvable(tmp_path: Path) -> None:
    """No `origin` remote at all -- the bootstrap/no-network case."""
    root = tmp_path / "solo"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, "seed.txt", "seed")
    _commit(root, "solo commit")

    assert mod.base_registry(root) is None


def test_raises_when_an_explicit_base_ref_is_unresolvable(repo: Path) -> None:
    with pytest.raises(mod.BranchIndependenceError, match="cannot be resolved"):
        mod.base_registry(repo, explicit_base="origin/no-such-branch")


def test_returns_none_when_the_implicit_base_has_no_common_ancestor(tmp_path: Path) -> None:
    """A shallow checkout can resolve `origin/develop` to a commit without
    sharing history with HEAD; an orphan branch reproduces the same
    merge-base failure without needing an actual shallow clone."""
    root = tmp_path / "unrelated"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, "seed.txt", "seed")
    _commit(root, "develop commit")
    _run(root, "checkout", "-q", "--orphan", "island")
    _run(root, "rm", "-rf", "--cached", ".")
    _write(root, REGISTRY, {"version": 1, "frozen_legacy_paths": []})
    _commit(root, "unrelated history")
    # HEAD must stay off the island: --orphan switches to it, and fetching it
    # as origin/develop while HEAD is still there would make merge-base trivially
    # succeed against itself.
    _run(root, "checkout", "-q", "develop")
    _run(root, "remote", "add", "origin", str(root))
    # Fetch only the orphan branch as `origin/develop` -- HEAD (develop) and
    # that ref now share no common ancestor, exactly like a shallow checkout
    # that never fetched the real trunk.
    _run(root, "fetch", "-q", "origin", "island:refs/remotes/origin/develop")

    assert mod.base_registry(root) is None


def test_raises_when_an_explicit_base_has_no_common_ancestor(tmp_path: Path) -> None:
    root = tmp_path / "unrelated-explicit"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, "seed.txt", "seed")
    _commit(root, "develop commit")
    _run(root, "checkout", "-q", "--orphan", "island")
    _run(root, "rm", "-rf", "--cached", ".")
    _write(root, REGISTRY, {"version": 1, "frozen_legacy_paths": []})
    island_sha = _commit(root, "unrelated history")
    _run(root, "checkout", "-q", "develop")

    with pytest.raises(mod.BranchIndependenceError, match="cannot resolve merge base"):
        mod.base_registry(root, explicit_base=island_sha)


def test_returns_none_when_the_registry_is_absent_at_the_base(tmp_path: Path) -> None:
    """The bootstrap case: the contract did not exist yet at the base commit."""
    root = tmp_path / "bootstrap"
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    _write(root, "seed.txt", "seed")
    _commit(root, "trunk without a registry")
    _run(root, "remote", "add", "origin", str(root))
    _run(root, "fetch", "-q", "origin")
    _run(root, "checkout", "-q", "-b", "candidate")
    _write(root, REGISTRY, {"version": 1, "frozen_legacy_paths": []})
    _commit(root, "candidate adds the registry")

    assert mod.base_registry(root) is None


def _repo_with_trunk_content(root: Path, rel: str, body: str) -> Path:
    """A trunk whose *initial* commit already carries `body` at `rel` -- the
    merge-base with any later candidate commit is this same commit, so its
    content is what a base read actually returns."""
    root.mkdir()
    _run(root, "init", "-q", "-b", "develop")
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(body, encoding="utf-8")
    _commit(root, "trunk content")
    _run(root, "remote", "add", "origin", str(root))
    _run(root, "fetch", "-q", "origin")
    _run(root, "checkout", "-q", "-b", "candidate")
    _write(root, "work.txt", "candidate work")
    _commit(root, "candidate work")
    return root


def test_raises_when_the_registry_at_the_base_is_invalid_json(tmp_path: Path) -> None:
    root = _repo_with_trunk_content(tmp_path / "invalid-json", REGISTRY, "{not json")

    with pytest.raises(mod.BranchIndependenceError, match="invalid JSON"):
        mod.base_registry(root)


def test_raises_when_the_registry_at_the_base_is_not_an_object(tmp_path: Path) -> None:
    root = _repo_with_trunk_content(tmp_path / "not-an-object", REGISTRY, "[]")

    with pytest.raises(mod.BranchIndependenceError, match="is not an object"):
        mod.base_registry(root)


class TestMain:
    def test_prints_pass_and_exits_zero_on_a_clean_repository(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = {
            "version": 1,
            "quality_roots": ["quality"],
            "frozen_legacy_paths": [],
            "surfaces": [
                {
                    "id": "reg",
                    "kind": "specification",
                    "paths": [REGISTRY],
                    "reason": "self-describing",
                }
            ],
        }
        _write(repo, REGISTRY, registry)
        _commit(repo, "self-describing registry")

        code = mod.main(["--root", str(repo)])

        assert code == 0
        assert "PASS" in capsys.readouterr().out

    def test_reports_contract_violations_and_exits_one(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(repo, REGISTRY, {"version": 1, "quality_roots": [], "frozen_legacy_paths": []})
        _commit(repo, "invalid registry")

        code = mod.main(["--root", str(repo)])

        assert code == 1
        err = capsys.readouterr().err
        assert "FAIL: branch-independence contract" in err
        assert "quality_roots must be a non-empty list of paths" in err

    def test_reports_evaluation_failure_for_an_unresolvable_explicit_base(
        self, repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = {
            "version": 1,
            "quality_roots": ["quality"],
            "frozen_legacy_paths": [],
            "surfaces": [
                {
                    "id": "reg",
                    "kind": "specification",
                    "paths": [REGISTRY],
                    "reason": "self-describing",
                }
            ],
        }
        _write(repo, REGISTRY, registry)
        _commit(repo, "self-describing registry")

        code = mod.main(["--root", str(repo), "--base", "origin/no-such-branch"])

        assert code == 2
        assert "could not be evaluated" in capsys.readouterr().err
