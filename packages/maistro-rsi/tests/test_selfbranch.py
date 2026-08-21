"""Tests tied to SPEC.md §3 (self-branch workflow) acceptance criteria selfbranch-1..8."""

from __future__ import annotations

from pathlib import Path

import pytest

import maistro_rsi.selfbranch as selfbranch
from maistro_rsi.quarantine import QuarantineVerdict
from maistro_rsi.selfbranch import new_attempt, paths_touched_by_diff, run_self_branch_attempt


class FakeSandbox:
    def __init__(self, exec_result=(0, "tests passed")) -> None:
        self.exec_result = exec_result
        self.exec_calls: list[str] = []

    async def exec(self, command, timeout=60):
        self.exec_calls.append(command)
        return self.exec_result


class FakeGitOps:
    """Records call order (shared with the patch callback) and lets a test force any step to fail."""

    def __init__(self, *, clone_ok: bool = True, order: list[str] | None = None) -> None:
        self.calls: list[str] = order if order is not None else []
        self.clone_ok = clone_ok
        self.pr_created = False

    async def git_clone(self, url, dest):
        self.calls.append("clone")
        return {"ok": self.clone_ok, "exit_code": 0 if self.clone_ok else 1}

    async def git_branch(self, workspace, name, checkout=True):
        self.calls.append("branch")
        return {"ok": True}

    async def git_add(self, workspace):
        self.calls.append("add")
        return {"ok": True}

    async def git_commit(self, workspace, message, add_all=True):
        self.calls.append("commit")
        return {"ok": True}

    async def git_diff(self, workspace, staged=False):
        self.calls.append("diff")
        return {"stdout": "diff --git a/x b/x"}

    async def git_push(self, workspace, branch, set_upstream=True):
        self.calls.append("push")
        return {"ok": True}

    async def github_create_pr(self, repo, branch, title, body, base="main"):
        self.calls.append("create_pr")
        self.pr_created = True
        return {"url": "https://github.com/org/repo/pull/1"}


@pytest.fixture(autouse=True)
def patch_git_ops(monkeypatch):
    """Swap the module-level git function references for a fake we can inspect."""
    fake = FakeGitOps()

    monkeypatch.setattr(selfbranch, "git_clone", fake.git_clone)
    monkeypatch.setattr(selfbranch, "git_branch", fake.git_branch)
    monkeypatch.setattr(selfbranch, "git_add", fake.git_add)
    monkeypatch.setattr(selfbranch, "git_commit", fake.git_commit)
    monkeypatch.setattr(selfbranch, "git_diff", fake.git_diff)
    monkeypatch.setattr(selfbranch, "git_push", fake.git_push)
    monkeypatch.setattr(selfbranch, "github_create_pr", fake.github_create_pr)
    return fake


async def _noop_patch(sandbox, workspace, model=None) -> None:
    pass


class TestNewAttempt:
    def test_branch_names_are_unique_per_call(self):
        """selfbranch-1: new_attempt produces a unique branch name each call."""
        a = new_attempt("https://github.com/org/repo.git", "pytest -q")
        b = new_attempt("https://github.com/org/repo.git", "pytest -q")
        assert a.branch_name != b.branch_name


class TestRunSelfBranchAttempt:
    @pytest.mark.asyncio
    async def test_clone_failure_short_circuits_and_records_error(self, patch_git_ops):
        """selfbranch-2: a failed clone runs no further steps and sets `error`."""
        fake = patch_git_ops
        fake.clone_ok = False
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is not None
        assert fake.calls == ["clone"]

    @pytest.mark.asyncio
    async def test_successful_clone_runs_branch_then_patch_then_commit_in_order(self, monkeypatch):
        """selfbranch-3: branch -> apply_patch -> add -> diff -> commit happen in that
        order before tests. add/diff must precede commit so the captured diff is
        non-empty (diff is read from the staged tree, not from HEAD after commit)."""
        order: list[str] = []
        fake = FakeGitOps(order=order)
        monkeypatch.setattr(selfbranch, "git_clone", fake.git_clone)
        monkeypatch.setattr(selfbranch, "git_branch", fake.git_branch)
        monkeypatch.setattr(selfbranch, "git_add", fake.git_add)
        monkeypatch.setattr(selfbranch, "git_commit", fake.git_commit)
        monkeypatch.setattr(selfbranch, "git_diff", fake.git_diff)
        monkeypatch.setattr(selfbranch, "git_push", fake.git_push)
        monkeypatch.setattr(selfbranch, "github_create_pr", fake.github_create_pr)

        async def tracking_patch(sandbox, workspace, model=None):
            order.append("patch")

        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")
        await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, tracking_patch)

        assert (
            order.index("branch")
            < order.index("patch")
            < order.index("add")
            < order.index("diff")
            < order.index("commit")
        )

    @pytest.mark.asyncio
    async def test_tests_passed_true_only_when_exit_zero_and_no_error(self, patch_git_ops):
        """selfbranch-4: tests_passed requires exit code 0 AND no recorded error."""
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        passing = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
        )
        assert passing.tests_passed is True

        failing = await run_self_branch_attempt(
            FakeSandbox(exec_result=(1, "boom")),
            "/ws",
            attempt,
            _noop_patch,
        )
        assert failing.tests_passed is False

    @pytest.mark.asyncio
    async def test_clone_failure_never_reads_as_tests_passed(self, patch_git_ops):
        """selfbranch-4: a clone failure must not be reported as tests_passed."""
        fake = patch_git_ops
        fake.clone_ok = False
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)
        assert result.tests_passed is False

    @pytest.mark.asyncio
    async def test_pr_opened_only_when_open_pr_true_and_tests_pass(self, patch_git_ops):
        """selfbranch-5: PR creation requires open_pr=True AND a passing test command."""
        fake = patch_git_ops
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        # open_pr=False, tests pass -> no PR
        r1 = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=False,
        )
        assert r1.pr_url is None
        assert "create_pr" not in fake.calls

        # open_pr=True, tests fail -> no PR
        fake.calls.clear()
        r2 = await run_self_branch_attempt(
            FakeSandbox(exec_result=(1, "fail")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=True,
        )
        assert r2.pr_url is None
        assert "create_pr" not in fake.calls

        # open_pr=True, tests pass, quarantine cleared -> PR opened. The
        # cleared verdict is REQUIRED: shipping without any quarantine check
        # used to fail open, and the safety property of a self-modifying
        # system was held up by a comment asking callers to pass the param.
        async def cleared(diff: str, touched: list[str]) -> QuarantineVerdict:
            return QuarantineVerdict(cleared=True, requires_adversarial_review=False, flags=())

        fake.calls.clear()
        r3 = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=True,
            quarantine_check=cleared,
        )
        assert r3.pr_url == "https://github.com/org/repo/pull/1"
        assert "create_pr" in fake.calls

    @pytest.mark.asyncio
    async def test_no_quarantine_check_means_no_pr(self, patch_git_ops):
        """A missing quarantine check is a deny, not a bypass: open_pr=True
        with passing tests and NO check must not push or open a PR."""
        fake = patch_git_ops
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")
        result = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=True,
        )
        assert result.pr_url is None
        assert "create_pr" not in fake.calls
        assert "push" not in fake.calls

    @pytest.mark.asyncio
    async def test_diff_reflects_captured_git_diff_output(self, patch_git_ops):
        """selfbranch-6: returned diff carries the captured `git diff` output."""
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")
        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)
        assert result.diff == "diff --git a/x b/x"

    @pytest.mark.asyncio
    async def test_pr_blocked_when_quarantine_check_does_not_clear(self, patch_git_ops):
        """selfbranch-5: a passing test suite and open_pr=True are not enough — an uncleared
        quarantine verdict must still block the PR."""
        fake = patch_git_ops
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        async def uncleared_check(diff, touched_paths):
            return QuarantineVerdict(
                cleared=False, requires_adversarial_review=True, flags=("flagged",)
            )

        result = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=True,
            quarantine_check=uncleared_check,
        )

        assert result.pr_url is None
        assert "create_pr" not in fake.calls

    @pytest.mark.asyncio
    async def test_pr_opened_when_quarantine_check_clears(self, patch_git_ops):
        """selfbranch-5: open_pr=True + passing tests + a cleared quarantine verdict opens the PR."""
        fake = patch_git_ops
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        async def cleared_check(diff, touched_paths):
            return QuarantineVerdict(cleared=True, requires_adversarial_review=False, flags=())

        result = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            open_pr=True,
            quarantine_check=cleared_check,
        )

        assert result.pr_url == "https://github.com/org/repo/pull/1"
        assert "create_pr" in fake.calls

    @pytest.mark.asyncio
    async def test_quarantine_field_carries_returned_verdict(self, patch_git_ops):
        """selfbranch-8: the result's `quarantine` field carries the verdict `quarantine_check`
        returned, verbatim, so callers don't have to re-derive it."""
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")
        verdict = QuarantineVerdict(
            cleared=False,
            requires_adversarial_review=True,
            flags=("flagged",),
            reason="pending",
        )

        async def returning_check(diff, touched_paths):
            return verdict

        result = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "ok")),
            "/ws",
            attempt,
            _noop_patch,
            quarantine_check=returning_check,
        )

        assert result.quarantine is verdict


class TestPathsTouchedByDiff:
    def test_extracts_deduplicated_paths_in_first_seen_order(self):
        """selfbranch-7: paths_touched_by_diff extracts every a/... and b/... path from
        diff --git headers, de-duplicated and in first-seen order."""
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "index 1234567..89abcde 100644\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "diff --git a/bar/baz.py b/bar/baz_renamed.py\n"
            "--- a/bar/baz.py\n"
            "+++ b/bar/baz_renamed.py\n"
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
        )

        assert paths_touched_by_diff(diff) == ["foo.py", "bar/baz.py", "bar/baz_renamed.py"]

    def test_empty_diff_yields_no_paths(self):
        """selfbranch-7: a diff with no `diff --git` headers touches no paths."""
        assert paths_touched_by_diff("") == []


class TestCapturedDiffIsNonEmpty:
    """Regression test against real git (no fakes): the diff captured for the
    quarantine gate and PR body must reflect the actual patch, not an empty
    diff against a tree that already matches HEAD after commit."""

    @pytest.fixture(autouse=True)
    def patch_git_ops(self):
        """Shadow the module-level autouse fixture — this class needs real git,
        not FakeGitOps, to exercise the actual clone/add/diff/commit sequence."""
        yield None

    @pytest.mark.asyncio
    async def test_diff_reflects_a_real_file_added_by_the_patch(self, tmp_path, monkeypatch):
        import subprocess

        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=origin, check=True)
        (origin / "README.md").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=origin, check=True)

        workspace_root = tmp_path / "maistro-workspace"
        monkeypatch.setattr(
            "maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS",
            (workspace_root,),
        )
        # The scrub hardened `git_clone` with a scheme allowlist so an agent
        # cannot hand git a local path or a `-`-prefixed flag. Production
        # clones over https; a hermetic test of *real* git needs a local
        # origin, so it opts into `file://` here rather than the allowlist
        # being widened for everyone -- the same shape as the
        # ALLOWED_HOST_ROOTS relaxation just above.
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "git://", "ssh://", "file://"),
        )
        workspace = str(workspace_root / "run1")

        async def add_a_file(_sandbox, ws: str, model=None) -> None:
            (Path(ws) / "new_feature.py").write_text("print('patched')\n")

        attempt = new_attempt(f"file://{origin}", "true", base_branch="main")
        result = await run_self_branch_attempt(FakeSandbox(), workspace, attempt, add_a_file)

        assert "new_feature.py" in result.diff
        assert "print('patched')" in result.diff
        assert paths_touched_by_diff(result.diff) == ["new_feature.py"]
