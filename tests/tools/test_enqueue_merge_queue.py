from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import urllib.error
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "check-enqueue-merge-queue.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_enqueue_merge_queue", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def enqueue() -> ModuleType:
    return load_module()


def candidate(enqueue: ModuleType, **overrides: object):
    values = {
        "number": 568,
        "head_sha": "abc123",
        "base_ref": "develop",
        "base_sha": "base123",
        "state": "open",
        "draft": False,
        "auto_merge_requested": False,
    }
    values.update(overrides)
    return enqueue.Candidate(**values)


def raw_pr(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "number": 568,
        "state": "open",
        "draft": False,
        "head": {"sha": "abc123"},
        "base": {"ref": "develop", "sha": "base123"},
        "auto_merge": None,
    }
    values.update(overrides)
    return values


def green_statuses() -> list[dict[str, str]]:
    return [
        {
            "context": "gates-ran",
            "state": "success",
            "created_at": "2026-08-28T23:59:00Z",
        }
    ]


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
    git(repo, "config", "user.name", "Queue Test")
    git(repo, "config", "user.email", "queue@example.invalid")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "base")
    return repo, git(repo, "rev-parse", "HEAD")


def commit_file(repo: Path, path: str, text: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", path)
    git(repo, "commit", "-m", f"change {path}")
    return git(repo, "rev-parse", "HEAD")


def assess_change(
    enqueue: ModuleType,
    tmp_path: Path,
    path: str,
):
    repo, base_sha = init_repo(tmp_path)
    head_sha = commit_file(repo, path, "safe = True\n")
    current = candidate(
        enqueue,
        base_sha=base_sha,
        head_sha=head_sha,
    )
    return enqueue.policy_assessment(repo, current)


def green_assessment(enqueue: ModuleType):
    return enqueue.AUTONOMOUS_POLICY.assess([], "", force_autonomous=True)


def red_assessment(enqueue: ModuleType):
    changed = [
        enqueue.AUTONOMOUS_POLICY.ChangedFile(
            status="M",
            path="scripts/check-gates-ran.py",
        )
    ]
    return enqueue.AUTONOMOUS_POLICY.assess(
        changed,
        "+safe = True",
        force_autonomous=True,
    )


def test_admission_requires_exact_head_gates_and_policy_green(
    enqueue: ModuleType,
) -> None:
    assert enqueue.is_admissible(
        candidate(enqueue),
        green_statuses(),
        policy_eligible=True,
    )
    assert not enqueue.is_admissible(
        candidate(enqueue),
        [],
        policy_eligible=True,
    )
    assert not enqueue.is_admissible(
        candidate(enqueue),
        green_statuses(),
        policy_eligible=False,
    )


def test_trusted_workflow_change_is_human_only(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    assessment = assess_change(
        enqueue,
        tmp_path,
        ".github/workflows/gates-ran.yml",
    )

    assert assessment.risk == "red"
    assert not assessment.eligible


def test_yellow_high_blast_radius_change_is_human_only(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    assessment = assess_change(
        enqueue,
        tmp_path,
        "packages/maistro-core/src/maistro/graph/router.py",
    )

    assert assessment.risk == "yellow"
    assert not assessment.eligible


def test_green_change_is_bot_eligible(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    assessment = assess_change(
        enqueue,
        tmp_path,
        "packages/maistro-core/src/maistro/router/scorer.py",
    )

    assert assessment.risk == "green"
    assert assessment.eligible


def test_generated_ledger_remains_human_only_until_562_converts_it(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    assessment = assess_change(enqueue, tmp_path, "quality/ac-state.json")

    assert assessment.risk == "red"
    assert not assessment.eligible


def test_policy_uses_merge_base_not_moving_develop_tip(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    repo, common = init_repo(tmp_path)
    git(repo, "switch", "-c", "pr")
    head_sha = commit_file(repo, "docs/canary.md", "candidate\n")
    git(repo, "switch", "develop")
    base_sha = commit_file(
        repo,
        ".github/workflows/new-trusted-gate.yml",
        "name: trusted\n",
    )

    assessment = enqueue.policy_assessment(
        repo,
        candidate(enqueue, base_sha=base_sha, head_sha=head_sha),
    )

    assert git(repo, "merge-base", base_sha, head_sha) == common
    assert assessment.risk == "green"
    assert assessment.eligible
    assert assessment.changed_files == ["docs/canary.md"]


def test_auto_merge_request_and_base_sha_are_recorded(enqueue: ModuleType) -> None:
    parsed = enqueue.candidate_from_pr(raw_pr(auto_merge={"enabled_by": {"login": "human"}}))

    assert parsed.auto_merge_requested
    assert parsed.base_sha == "base123"


def test_wrong_base_draft_closed_and_already_requested_are_refused(
    enqueue: ModuleType,
) -> None:
    for pr in (
        candidate(enqueue, base_ref="main"),
        candidate(enqueue, draft=True),
        candidate(enqueue, state="closed"),
        candidate(enqueue, auto_merge_requested=True),
    ):
        assert not enqueue.is_admissible(
            pr,
            green_statuses(),
            policy_eligible=True,
        )


def test_queue_request_is_sha_bound_squash_only(enqueue: ModuleType) -> None:
    payload = enqueue.merge_async_payload(candidate(enqueue, head_sha="deadbeef"))

    assert payload == {
        "sha": "deadbeef",
        "merge_action": "merge_queue",
    }
    # The queue mutation takes the head SHA + merge_action only: echoing
    # merge_method (SQUASH lives in .github/merge-queue.json, not here) is
    # rejected with HTTP 422 and burst-failed the 09-02 enqueues.
    assert "merge_method" not in payload
    assert "direct_merge" not in payload.values()


def test_object_fetch_is_exact_head_bound(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    assessed = False

    def fake_git(repo, *args, env=None):
        calls.append(args)
        if args[0] == "rev-parse":
            return "abc123\n"
        return ""

    def fake_assessment(repo, current):
        nonlocal assessed
        assessed = True
        return green_assessment(enqueue)

    monkeypatch.setattr(enqueue, "_git", fake_git)
    monkeypatch.setattr(enqueue, "policy_assessment", fake_assessment)
    api = enqueue.GitHubApi("read", "queue", "owner/repo", Path("."))

    result = api.policy_assessment(candidate(enqueue))

    assert result is not None
    assert assessed
    fetch = next(call for call in calls if call[0] == "fetch")
    assert "+refs/heads/develop:refs/remotes/origin/develop" in fetch
    assert "+refs/pull/568/head:refs/remotes/maistro-queue/pr-568" in fetch
    assert ("cat-file", "-e", "base123^{commit}") in calls
    assert ("cat-file", "-e", "abc123^{commit}") in calls


def test_object_fetch_refuses_head_race(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_git(repo, *args, env=None):
        if args[0] == "rev-parse":
            return "new-head\n"
        return ""

    monkeypatch.setattr(enqueue, "_git", fake_git)
    api = enqueue.GitHubApi("read", "queue", "owner/repo", Path("."))

    assert api.policy_assessment(candidate(enqueue)) is None


def test_run_rechecks_current_pr_and_refuses_retarget(enqueue: ModuleType) -> None:
    class RetargetedApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            assert number == 568
            return raw_pr(base={"ref": "main", "sha": "base123"})

        def statuses(self, sha: str):
            assert sha == "abc123"
            return green_statuses()

        def policy_assessment(self, current):
            return green_assessment(enqueue)

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = RetargetedApi()
    assert enqueue.run(api) == 0
    assert not api.enqueued


def test_run_never_enqueues_trusted_surface(enqueue: ModuleType) -> None:
    class TrustedApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            return red_assessment(enqueue)

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = TrustedApi()
    assert enqueue.run(api) == 0
    assert not api.enqueued


def test_run_enqueues_green_surface(enqueue: ModuleType) -> None:
    class GreenApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            return green_assessment(enqueue)

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = GreenApi()
    assert enqueue.run(api) == 0
    assert api.enqueued


def test_run_does_not_repeat_an_existing_auto_merge_request(enqueue: ModuleType) -> None:
    class AlreadyRequestedApi:
        def __init__(self) -> None:
            self.enqueued = False
            self.statuses_read = False

        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr(auto_merge={"enabled_by": {"login": "human"}})

        def statuses(self, sha: str):
            self.statuses_read = True
            return green_statuses()

        def policy_assessment(self, current):
            raise AssertionError("policy should not be evaluated")

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = AlreadyRequestedApi()
    assert enqueue.run(api) == 0
    assert not api.enqueued
    assert not api.statuses_read


def test_policy_evidence_failure_is_loud_and_fail_closed(enqueue: ModuleType) -> None:
    class BrokenEvidenceApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            raise RuntimeError("cannot prove candidate diff")

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = BrokenEvidenceApi()
    assert enqueue.run(api) == 1
    assert not api.enqueued


def test_422_after_auto_merge_race_is_idempotent(enqueue: ModuleType) -> None:
    class RacingApi(enqueue.GitHubApi):
        def __init__(self) -> None:
            super().__init__("read", "queue", "owner/repo")

        def _request(self, method, path, payload=None, *, token=None):
            if path.endswith("/merge-async"):
                raise urllib.error.HTTPError(
                    "https://api.github.test/merge-async",
                    422,
                    "Unprocessable Entity",
                    {},
                    io.BytesIO(b'{"message":"already queued"}'),
                )
            if path.endswith("/pulls/568"):
                return raw_pr(auto_merge={"enabled_by": {"login": "human"}})
            raise AssertionError(path)

    assert RacingApi().enqueue(candidate(enqueue)) == "already-requested"


def test_unarmed_400_and_422_preserve_github_error_body(enqueue: ModuleType) -> None:
    class RejectingApi(enqueue.GitHubApi):
        def __init__(self, code: int) -> None:
            super().__init__("read", "queue", "owner/repo")
            self.code = code

        def _request(self, method, path, payload=None, *, token=None):
            if path.endswith("/merge-async"):
                raise urllib.error.HTTPError(
                    "https://api.github.test/merge-async",
                    self.code,
                    "Rejected",
                    {},
                    io.BytesIO(b'{"message":"validation failed","errors":["reason"]}'),
                )
            if path.endswith("/pulls/568"):
                return raw_pr()
            raise AssertionError(path)

    for code in (400, 422):
        with pytest.raises(RuntimeError, match="validation failed"):
            RejectingApi(code).enqueue(candidate(enqueue))


def test_git_failure_preserves_command_status_and_stderr(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = subprocess.CompletedProcess(
        args=["git"],
        returncode=7,
        stdout="",
        stderr="fetch broke\n",
    )
    monkeypatch.setattr(enqueue.subprocess, "run", lambda *args, **kwargs: failed)

    with pytest.raises(RuntimeError, match=r"git fetch failed \(7\): fetch broke"):
        enqueue._git(Path("."), "fetch")


def test_git_auth_env_rejects_invalid_config_count(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "not-an-integer")

    with pytest.raises(RuntimeError, match="GIT_CONFIG_COUNT is not an integer"):
        enqueue._git_auth_env("read-token")


def test_policy_requires_a_merge_base(
    enqueue: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(enqueue, "_git", lambda repo, *args, env=None: "\n")

    with pytest.raises(RuntimeError, match="no merge base"):
        enqueue.policy_assessment(Path("."), candidate(enqueue))


def test_policy_classifies_merge_tree_conflicts_as_unqueueable(
    enqueue: ModuleType,
    tmp_path: Path,
) -> None:
    repo, _ = init_repo(tmp_path)
    git(repo, "checkout", "-b", "candidate")
    head_sha = commit_file(repo, "README.md", "candidate\n")
    git(repo, "checkout", "develop")
    base_sha = commit_file(repo, "README.md", "develop\n")

    with pytest.raises(enqueue.UnmergeableCandidate, match="does not merge cleanly"):
        enqueue.policy_assessment(
            repo,
            candidate(enqueue, base_sha=base_sha, head_sha=head_sha),
        )


def test_http_error_detail_survives_unreadable_body(enqueue: ModuleType) -> None:
    class UnreadableError:
        reason = "response body unavailable"

        def read(self):
            raise OSError("body stream failed")

    assert enqueue._http_error_detail(UnreadableError()) == "response body unavailable"


def test_run_waits_when_exact_head_gates_are_not_green(enqueue: ModuleType) -> None:
    class PendingGatesApi:
        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return []

        def policy_assessment(self, current):
            raise AssertionError("policy should not be evaluated before exact-head gates")

        def enqueue(self, current):
            raise AssertionError("queue should not be mutated before exact-head gates")

    assert enqueue.run(PendingGatesApi()) == 0


def test_run_waits_when_head_moves_during_object_fetch(enqueue: ModuleType) -> None:
    class HeadMovedApi:
        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            return None

        def enqueue(self, current):
            raise AssertionError("stale head must never be enqueued")

    assert enqueue.run(HeadMovedApi()) == 0


def test_run_skips_conflicted_candidates_without_failing_controller(
    enqueue: ModuleType,
) -> None:
    class ConflictedApi:
        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            raise enqueue.UnmergeableCandidate("candidate conflicts with develop")

        def enqueue(self, current):
            raise AssertionError("conflicted candidate must not be enqueued")

    assert enqueue.run(ConflictedApi()) == 0


def test_queue_request_failure_is_loud_and_nonzero(enqueue: ModuleType) -> None:
    class BrokenQueueApi:
        def merge_group_runs(self):
            return []

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            return green_assessment(enqueue)

        def enqueue(self, current):
            raise RuntimeError("queue transport failed")

    assert enqueue.run(BrokenQueueApi()) == 1


# --- failed-candidate quarantine ------------------------------------------
#
# GitHub builds one entry branch per queued PR, `gh-readonly-queue/develop/
# pr-N-<parent>`, where <parent> is the head of the entry ahead (or the base
# head at the front). Observed on develop 2026-09-13: `pr-1381-62cfc8…` sat on
# the `pr-1384` entry whose runs had head_sha `62cfc8…`. That link is what
# these tests exercise: a failure is the entry's own unless the chain it was
# built on reaches an entry that did not verify.


def queue_run(
    pr: int,
    parent: str,
    head: str,
    conclusion: str | None,
    *,
    name: str = "CI",
    created_at: str = "2026-09-14T01:00:00Z",
    base: str = "develop",
    event: str = "merge_group",
) -> dict[str, object]:
    return {
        "event": event,
        "name": name,
        "head_branch": f"gh-readonly-queue/{base}/pr-{pr}-{parent}",
        "head_sha": head,
        "conclusion": conclusion,
        "created_at": created_at,
    }


def test_a_failed_entry_at_the_front_owns_its_failure(enqueue: ModuleType) -> None:
    failures = enqueue.own_queue_failures(
        [
            queue_run(568, "base0", "h568", "failure", name="CI"),
            queue_run(568, "base0", "h568", "success", name="quality"),
            queue_run(568, "base0", "h568", "failure", name="Gate C"),
        ]
    )
    assert set(failures) == {568}
    (failure,) = failures[568]
    assert failure.parent == "base0"
    assert failure.workflows == ("CI", "Gate C")
    assert failure.created_at == enqueue._parse_time("2026-09-14T01:00:00Z")


def test_entries_rebuilt_behind_a_failed_entry_are_not_blamed(enqueue: ModuleType) -> None:
    """ALLGREEN ejects the failing entry and rebuilds the ones behind it. The
    cancelled runs behind it — and a run that managed to conclude `failure`
    before the cancel reached it — are the batch's cost, not a bad head."""
    failures = enqueue.own_queue_failures(
        [
            queue_run(568, "base0", "h568", "failure"),
            queue_run(570, "h568", "h570", "cancelled"),
            queue_run(572, "h570", "h572", "failure"),
        ]
    )
    assert set(failures) == {568}


def test_an_entry_behind_a_green_entry_owns_its_failure(enqueue: ModuleType) -> None:
    failures = enqueue.own_queue_failures(
        [
            queue_run(568, "base0", "h568", "success"),
            queue_run(570, "h568", "h570", "failure"),
        ]
    )
    assert set(failures) == {570}


def test_a_parent_outside_the_window_reads_as_the_base_head(enqueue: ModuleType) -> None:
    """Fail closed: when the entry ahead scrolled out of the fetched history the
    controller cannot show it failed, so the entry keeps its own failure."""
    failures = enqueue.own_queue_failures([queue_run(570, "unseen", "h570", "failure")])
    assert set(failures) == {570}


def test_cancelled_and_still_running_entries_are_not_failures(enqueue: ModuleType) -> None:
    failures = enqueue.own_queue_failures(
        [
            queue_run(568, "base0", "h568", "cancelled"),
            queue_run(570, "h568", "h570", None),
        ]
    )
    assert failures == {}


def test_foreign_bases_and_non_queue_runs_are_ignored(enqueue: ModuleType) -> None:
    failures = enqueue.own_queue_failures(
        [
            queue_run(1, "base0", "h1", "failure", base="main"),
            queue_run(568, "base0", "h568", "failure", event="push"),
            {"event": "merge_group", "head_branch": "develop", "conclusion": "failure"},
        ]
    )
    assert failures == {}


def test_a_failed_run_without_a_usable_timestamp_is_loud(enqueue: ModuleType) -> None:
    with pytest.raises(RuntimeError, match="unusable timestamp"):
        enqueue.own_queue_failures([queue_run(568, "base0", "h568", "failure", created_at="")])


def test_a_queue_failure_binds_to_the_head_whose_gates_it_postdates(
    enqueue: ModuleType,
) -> None:
    """No entry for a head can exist before that head's gates-ran first
    succeeded, so a failure at or after that moment belongs to this head; an
    older one belongs to a head that has since moved."""
    failures = {
        568: [
            enqueue.QueueFailure(
                number=568,
                parent="base0",
                created_at=enqueue._parse_time("2026-09-14T01:00:00Z"),
                workflows=("CI",),
            )
        ]
    }
    earlier = [{"context": "gates-ran", "state": "success", "created_at": "2026-09-14T00:30:00Z"}]
    later = [{"context": "gates-ran", "state": "success", "created_at": "2026-09-14T02:00:00Z"}]
    assert enqueue.queue_failure_for_head(candidate(enqueue), earlier, failures) is not None
    assert enqueue.queue_failure_for_head(candidate(enqueue), later, failures) is None
    assert enqueue.queue_failure_for_head(candidate(enqueue), earlier, {}) is None


def test_the_earliest_gates_success_is_the_bound(enqueue: ModuleType) -> None:
    """A re-run of Gates Ran publishes gates-ran again; the queue entry may
    already have been created after the first success, so the first one
    bounds the quarantine, not the latest."""
    failures = {
        568: [
            enqueue.QueueFailure(
                number=568,
                parent="base0",
                created_at=enqueue._parse_time("2026-09-14T01:00:00Z"),
                workflows=("CI",),
            )
        ]
    }
    statuses = [
        {"context": "gates-ran", "state": "success", "created_at": "2026-09-14T02:00:00Z"},
        {"context": "gates-ran", "state": "success", "created_at": "2026-09-14T00:30:00Z"},
        {"context": "other", "state": "success", "created_at": "2026-09-13T00:00:00Z"},
    ]
    assert enqueue.queue_failure_for_head(candidate(enqueue), statuses, failures) is not None


def test_run_quarantines_a_head_that_already_failed_in_the_queue(
    enqueue: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    class QuarantinedApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return [queue_run(568, "base0", "h568", "failure", created_at="2026-09-14T01:00:00Z")]

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()  # gates-ran success at 2026-08-28T23:59:00Z

        def policy_assessment(self, current):
            raise AssertionError("a quarantined head must not be assessed")

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = QuarantinedApi()
    assert enqueue.run(api) == 0
    assert not api.enqueued
    out = capsys.readouterr().out
    assert "PR #568: quarantined on abc123" in out
    assert "failed CI at 2026-09-14T01:00:00Z" in out


def test_run_requeues_a_head_pushed_after_the_queue_failure(enqueue: ModuleType) -> None:
    class PushedSinceApi:
        def __init__(self) -> None:
            self.enqueued = False

        def merge_group_runs(self):
            return [queue_run(568, "base0", "h568", "failure", created_at="2026-08-01T00:00:00Z")]

        def open_develop_prs(self):
            return [raw_pr()]

        def pull_request(self, number: int):
            return raw_pr()

        def statuses(self, sha: str):
            return green_statuses()

        def policy_assessment(self, current):
            return green_assessment(enqueue)

        def enqueue(self, current):
            self.enqueued = True
            return "accepted"

    api = PushedSinceApi()
    assert enqueue.run(api) == 0
    assert api.enqueued


def test_unreadable_queue_history_refuses_every_admission(
    enqueue: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    class BlindApi:
        def merge_group_runs(self):
            raise urllib.error.URLError("actions listing down")

        def open_develop_prs(self):
            raise AssertionError("no admission may be scanned without queue history")

    assert enqueue.run(BlindApi()) == 1
    assert "refusing every admission" in capsys.readouterr().err


def test_merge_group_runs_page_until_a_short_page(enqueue: ModuleType) -> None:
    api = enqueue.GitHubApi("read", "queue", "acme/widgets")
    pages = {1: [{"id": i} for i in range(100)], 2: [{"id": 100}]}
    seen: list[str] = []

    def fake_request(method: str, path: str, payload=None, *, token=None):
        seen.append(path)
        assert method == "GET" and token is None
        page = int(path.rsplit("page=", 1)[1])
        return {"workflow_runs": pages[page]}

    api._request = fake_request  # type: ignore[method-assign]
    runs = api.merge_group_runs()
    assert len(runs) == 101
    assert seen == [
        "/repos/acme/widgets/actions/runs?event=merge_group&per_page=100&page=1",
        "/repos/acme/widgets/actions/runs?event=merge_group&per_page=100&page=2",
    ]


def test_merge_group_runs_reject_a_malformed_listing(enqueue: ModuleType) -> None:
    api = enqueue.GitHubApi("read", "queue", "acme/widgets")
    api._request = lambda *args, **kwargs: {"workflow_runs": "nope"}  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="invalid workflow-run listing"):
        api.merge_group_runs()
