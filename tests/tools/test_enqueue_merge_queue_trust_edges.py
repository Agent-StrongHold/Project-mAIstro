from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "check-enqueue-merge-queue.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_enqueue_merge_queue_trust_edges",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def enqueue() -> ModuleType:
    return load_module()


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "develop")
    git(repo, "config", "user.name", "Queue Trust Test")
    git(repo, "config", "user.email", "queue-trust@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def candidate(enqueue: ModuleType, *, base_sha: str, head_sha: str):
    return enqueue.Candidate(
        number=679,
        head_sha=head_sha,
        base_ref="develop",
        base_sha=base_sha,
        state="open",
        draft=False,
    )


def test_newline_workflow_path_cannot_evade_trusted_policy(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    repo, base_sha = init_repo(tmp_path)
    path = ".github/workflows/evil\n.yml"
    target = repo / path
    target.parent.mkdir(parents=True)
    target.write_text("name: evil\n", encoding="utf-8")
    git(repo, "add", "--", path)
    git(repo, "commit", "-m", "newline workflow")
    head_sha = git(repo, "rev-parse", "HEAD")

    assessment = enqueue.policy_assessment(
        repo,
        candidate(enqueue, base_sha=base_sha, head_sha=head_sha),
    )

    assert assessment.risk == "red"
    assert not assessment.eligible
    assert assessment.changed_files == [path]


def test_non_utf8_candidate_diff_fails_closed_as_runtime_error(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    repo, base_sha = init_repo(tmp_path)
    target = repo / "docs" / "non-utf8.txt"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"candidate-\xff\n")
    git(repo, "add", "docs/non-utf8.txt")
    git(repo, "commit", "-m", "non utf8 candidate")
    head_sha = git(repo, "rev-parse", "HEAD")

    with pytest.raises(RuntimeError, match="non-UTF-8 content; human merge required"):
        enqueue.policy_assessment(
            repo,
            candidate(enqueue, base_sha=base_sha, head_sha=head_sha),
        )


def test_prospective_tree_exposes_base_side_rename_into_trusted_surface(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    repo, _ = init_repo(tmp_path)
    (repo / "safe.yml").write_text("base\n", encoding="utf-8")
    git(repo, "add", "safe.yml")
    git(repo, "commit", "-m", "add safe path")

    git(repo, "switch", "-c", "candidate")
    (repo / "safe.yml").write_text("candidate edit\n", encoding="utf-8")
    git(repo, "commit", "-am", "candidate edit")
    head_sha = git(repo, "rev-parse", "HEAD")

    git(repo, "switch", "develop")
    (repo / ".github" / "workflows").mkdir(parents=True)
    git(repo, "mv", "safe.yml", ".github/workflows/gate.yml")
    git(repo, "commit", "-m", "base renames path into trusted surface")
    base_sha = git(repo, "rev-parse", "HEAD")

    assessment = enqueue.policy_assessment(
        repo,
        candidate(enqueue, base_sha=base_sha, head_sha=head_sha),
    )

    assert assessment.risk == "red"
    assert not assessment.eligible
    assert assessment.changed_files == [".github/workflows/gate.yml"]


def test_nul_name_status_parser_preserves_rename_paths(enqueue: ModuleType) -> None:
    changed = enqueue._parse_name_status_z(b"R100\0safe\nname.yml\0.github/workflows/gate.yml\0")

    assert len(changed) == 1
    assert changed[0].status == "R100"
    assert changed[0].old_path == "safe\nname.yml"
    assert changed[0].path == ".github/workflows/gate.yml"


def test_nul_name_status_parser_fails_closed_on_malformed_records(
    enqueue: ModuleType,
) -> None:
    bad_records = (
        b"M\0path-without-terminator",
        b"\xff\0path\0",
        b"R100\0only-old\0",
        b"M\0",
    )

    for raw in bad_records:
        with pytest.raises(RuntimeError):
            enqueue._parse_name_status_z(raw)


def test_api_uses_fetched_base_and_refuses_queue_if_it_moves(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assessed_bases: list[str] = []

    def initial_git(repo, *args, env=None):
        if args[0] == "rev-parse" and str(args[1]).endswith("pr-679"):
            return "head\n"
        if args[0] == "rev-parse":
            return "current-base\n"
        return ""

    def fake_assessment(repo, current):
        assessed_bases.append(current.base_sha)
        return enqueue.AUTONOMOUS_POLICY.assess([], "", force_autonomous=True)

    monkeypatch.setattr(enqueue, "_git", initial_git)
    monkeypatch.setattr(enqueue, "policy_assessment", fake_assessment)
    api = enqueue.GitHubApi("read", "queue", "owner/repo", Path("."))
    current = candidate(enqueue, base_sha="stale-pr-base", head_sha="head")

    assessment = api.policy_assessment(current)

    assert assessment is not None and assessment.eligible
    assert assessed_bases == ["current-base"]

    def moved_base_git(repo, *args, env=None):
        if args[0] == "rev-parse":
            return "newer-base\n"
        return ""

    monkeypatch.setattr(enqueue, "_git", moved_base_git)
    monkeypatch.setattr(
        api,
        "_request",
        lambda *args, **kwargs: pytest.fail("base-moved candidate must not be enqueued"),
    )

    assert api.enqueue(current) == "base-moved"


def test_stale_policy_revision_refuses_assessment(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A base that advanced past the controller's own checkout may carry a
    tightened policy this process never loaded (Codex, #679). Evidence built
    against that base with the older policy must be refused loudly, not
    classified green by a judge that predates its own rules."""

    def fetched_git(repo, *args, env=None):
        if args[0] == "rev-parse" and str(args[1]).endswith("pr-679"):
            return "head\n"
        if args[0] == "rev-parse":
            return "advanced-base\n"
        return ""

    monkeypatch.setattr(enqueue, "_git", fetched_git)
    monkeypatch.setattr(
        enqueue,
        "policy_assessment",
        lambda repo, current: pytest.fail("stale-policy candidate must not be assessed"),
    )
    api = enqueue.GitHubApi(
        "read",
        "queue",
        "owner/repo",
        Path("."),
        controller_revision="checkout-base",
    )
    current = candidate(enqueue, base_sha="stale-pr-base", head_sha="head")

    with pytest.raises(RuntimeError, match=r"advanced-base.*checkout-base.*stale-policy"):
        api.policy_assessment(current)


def test_matching_policy_revision_assesses_normally(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fetched_git(repo, *args, env=None):
        if args[0] == "rev-parse" and str(args[1]).endswith("pr-679"):
            return "head\n"
        if args[0] == "rev-parse":
            return "checkout-base\n"
        return ""

    monkeypatch.setattr(enqueue, "_git", fetched_git)
    monkeypatch.setattr(
        enqueue,
        "policy_assessment",
        lambda repo, current: enqueue.AUTONOMOUS_POLICY.assess([], "", force_autonomous=True),
    )
    api = enqueue.GitHubApi(
        "read",
        "queue",
        "owner/repo",
        Path("."),
        controller_revision="checkout-base",
    )
    current = candidate(enqueue, base_sha="stale-pr-base", head_sha="head")

    assessment = api.policy_assessment(current)

    assert assessment is not None and assessment.eligible


def test_main_requires_the_controller_revision(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unverifiable policy-to-base binding is a refusal, not a default."""
    monkeypatch.setenv("GH_TOKEN", "read")
    monkeypatch.setenv("MERGE_QUEUE_TOKEN", "queue")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    assert enqueue.main() == 2
    assert "GITHUB_SHA is required" in capsys.readouterr().err
