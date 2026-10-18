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
        self.clone_commit: str | None = None
        # The tip digest the fake resolver hands out ("d"*40 by default); None
        # simulates a remote whose tip cannot be resolved.
        self.resolved_tip: str | None = "d" * 40
        self.resolution_calls = 0

    async def git_clone(self, url, dest, commit=None):
        self.calls.append("clone")
        self.clone_commit = commit
        result = {"ok": self.clone_ok, "exit_code": 0 if self.clone_ok else 1}
        if commit is not None:
            result["pinned_commit"] = commit
        return result

    async def git_remote_tip(self, url):
        self.resolution_calls += 1
        if self.resolved_tip is None:
            return {
                "success": False,
                "exit_code": 128,
                "stdout": "fatal: unavailable",
                "error_code": "remote_tip_unresolved",
                "suggested_action": "resolve manually",
            }
        return {
            "success": True,
            "exit_code": 0,
            "stdout": f"{self.resolved_tip}\tHEAD\n",
            "commit": self.resolved_tip,
        }

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
    monkeypatch.setattr(selfbranch, "git_remote_tip", fake.git_remote_tip)
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


class TestSourceCommitPinning:
    """#404 AC3 on the RSI self-branch surface: candidate source is always
    pinned to a commit digest — an explicit pin is used as-is, and an attempt
    without one resolves the remote's HEAD digest first — and the verified
    digest comes back on the result for audit/scoring."""

    @pytest.mark.asyncio
    async def test_attempt_commit_reaches_git_clone_pin(self, patch_git_ops):
        fake = patch_git_ops
        digest = "a" * 40
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q", commit=digest)

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is None
        assert fake.clone_commit == digest

    @pytest.mark.asyncio
    async def test_unpinned_attempt_resolves_the_remote_tip_and_pins_the_clone(
        self, patch_git_ops
    ) -> None:
        fake = patch_git_ops
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is None
        # None is not "unpinned": the cycle resolves the remote's HEAD digest
        # first and clones that, so the checkout is always digest-verified and
        # the result always names the source object it branched from.
        assert fake.resolution_calls == 1
        assert fake.clone_commit == fake.resolved_tip
        assert result.cloned_commit == fake.resolved_tip

    @pytest.mark.asyncio
    async def test_unresolved_tip_fails_closed_before_the_clone(self, patch_git_ops):
        """No digest, no candidate source: a failed resolution ends the
        attempt before any clone runs — it never degrades to an unpinned
        fetch of whatever the ref points at."""
        fake = patch_git_ops
        fake.resolved_tip = None
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q")

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is not None
        assert "source pin unresolved" in result.error
        assert fake.calls == []  # no clone, no branch, nothing downstream

    @pytest.mark.asyncio
    async def test_explicit_pin_skips_the_resolution(self, patch_git_ops):
        fake = patch_git_ops
        digest = "a" * 40
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q", commit=digest)

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is None
        assert fake.resolution_calls == 0
        assert fake.clone_commit == digest

    @pytest.mark.asyncio
    async def test_verified_pin_is_recorded_on_the_result(self, patch_git_ops):
        digest = "b" * 40
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q", commit=digest)

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        # git_clone reports pinned_commit only after its rev-parse HEAD verdict;
        # the result carries that verified identity downstream.
        assert result.cloned_commit == digest

    @pytest.mark.asyncio
    async def test_clone_failure_leaves_no_cloned_commit(self, patch_git_ops):
        patch_git_ops.clone_ok = False
        digest = "c" * 40
        attempt = new_attempt("https://github.com/org/repo.git", "pytest -q", commit=digest)

        result = await run_self_branch_attempt(FakeSandbox(), "/ws", attempt, _noop_patch)

        assert result.error is not None
        assert result.cloned_commit is None


class TestLiveSourceCommitPinning:
    """Real-git end-to-end for the source pin: same fixture shadow as
    TestCapturedDiffIsNonEmpty — the module-level autouse FakeGitOps is
    disabled so the actual clone/branch/commit sequence runs."""

    @pytest.fixture(autouse=True)
    def patch_git_ops(self):
        """Shadow the module-level autouse fixture — real git, not FakeGitOps."""
        yield None

    @pytest.mark.asyncio
    async def test_live_pinned_attempt_branches_from_the_pinned_object(self, tmp_path, monkeypatch):
        """End-to-end against real git: the attempt pins the origin's HEAD
        digest, and the workspace that gets branched/patched is exactly that
        object — reported as cloned_commit for the cycle's audit trail."""
        import subprocess

        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=origin, check=True)
        (origin / "README.md").write_text("v1\n")
        subprocess.run(["git", "add", "."], cwd=origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=origin, check=True)
        pinned = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=origin, capture_output=True, text=True, check=True
        ).stdout.strip()

        workspace_root = tmp_path / "maistro-workspace"
        monkeypatch.setattr(
            "maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS",
            (workspace_root,),
        )
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "ssh://", "file://"),
        )
        # A clone does not inherit the origin's git identity config; the
        # patch commit below runs in the cloned workspace, so pin the author/
        # committer via git's env contract instead of relying on a global
        # ~/.gitconfig existing in the test environment.
        monkeypatch.setenv("GIT_AUTHOR_NAME", "rsi-test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "rsi-test@example.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "rsi-test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "rsi-test@example.com")
        workspace = str(workspace_root / "run-pinned")

        async def add_a_file(_sandbox, ws: str, model=None) -> None:
            (Path(ws) / "pinned_marker.py").write_text("print('pinned')\n")

        attempt = new_attempt(f"file://{origin}", "true", base_branch="main", commit=pinned)
        result = await run_self_branch_attempt(FakeSandbox(), workspace, attempt, add_a_file)

        assert result.error is None, result.error
        assert result.cloned_commit == pinned
        # The branch was cut from the pinned object: the patch commit sits on
        # top of the pinned digest, so the patched workspace's history starts
        # exactly at the audited object.
        checked_out = subprocess.run(
            ["git", "rev-parse", "HEAD~1"], cwd=workspace, capture_output=True, text=True
        )
        assert checked_out.stdout.strip() == pinned

    @pytest.mark.asyncio
    async def test_live_unpinned_attempt_branches_from_the_resolved_tip(
        self, tmp_path, monkeypatch
    ) -> None:
        """The default path end-to-end against real git: an attempt with no
        explicit pin resolves the origin's HEAD via ls-remote (policy-gated,
        pin-enforced) and the workspace it patches sits exactly on that
        digest — `cloned_commit` is populated, not None."""
        import subprocess

        origin = tmp_path / "origin"
        origin.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=origin, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=origin, check=True)
        (origin / "README.md").write_text("v1\n")
        subprocess.run(["git", "add", "."], cwd=origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=origin, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=origin, check=True)
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=origin, capture_output=True, text=True, check=True
        ).stdout.strip()

        workspace_root = tmp_path / "maistro-workspace"
        monkeypatch.setattr(
            "maistro.tools.sandbox.workspace.ALLOWED_HOST_ROOTS",
            (workspace_root,),
        )
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "ssh://", "file://"),
        )
        monkeypatch.setenv("GIT_AUTHOR_NAME", "rsi-test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "rsi-test@example.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "rsi-test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "rsi-test@example.com")
        workspace = str(workspace_root / "run-resolved")

        async def add_a_file(_sandbox, ws: str, model=None) -> None:
            (Path(ws) / "resolved_marker.py").write_text("print('resolved')\n")

        attempt = new_attempt(f"file://{origin}", "true", base_branch="main")
        assert attempt.commit is None  # the default path, not an explicit pin
        result = await run_self_branch_attempt(FakeSandbox(), workspace, attempt, add_a_file)

        assert result.error is None, result.error
        assert result.cloned_commit == tip
        checked_out = subprocess.run(
            ["git", "rev-parse", "HEAD~1"], cwd=workspace, capture_output=True, text=True
        )
        assert checked_out.stdout.strip() == tip


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
        # cannot hand git a local path or a `-`-prefixed flag, and #404
        # dropped `git://` outright: the git protocol is unauthenticated and
        # unencrypted, so no caller -- and no test knob -- may reintroduce it.
        # Production clones over https; a hermetic test of *real* git needs a
        # local origin, so it opts into `file://` here rather than the
        # allowlist being widened for everyone -- the same shape as the
        # ALLOWED_HOST_ROOTS relaxation just above.
        monkeypatch.setattr(
            "maistro.tools.git.server._ALLOWED_CLONE_SCHEMES",
            ("https://", "ssh://", "file://"),
        )
        workspace = str(workspace_root / "run1")

        async def add_a_file(_sandbox, ws: str, model=None) -> None:
            (Path(ws) / "new_feature.py").write_text("print('patched')\n")

        attempt = new_attempt(f"file://{origin}", "true", base_branch="main")
        result = await run_self_branch_attempt(FakeSandbox(), workspace, attempt, add_a_file)

        assert "new_feature.py" in result.diff
        assert "print('patched')" in result.diff
        assert paths_touched_by_diff(result.diff) == ["new_feature.py"]


class TestDefaultPrBodyIsEvidenceDerived:
    """#820: the self-branch PR body states only what this path actually ran —
    the test command, its recorded exit status, and the output digest — and
    claims nothing about gates it never executed."""

    @staticmethod
    async def _body(
        exit_code: int, test_output: str = "3 passed in 0.01s\n", source_pin: str | None = None
    ) -> str:
        from maistro_rsi.selfbranch import _default_pr_body

        attempt = new_attempt("https://github.com/org/repo", "python -m pytest -q")
        return _default_pr_body(attempt, test_output, exit_code, source_pin)

    async def test_names_the_resolved_source_pin_not_attempt_commit(self):
        # Default `new_attempt()` carries commit=None; the body must name the
        # digest the run resolved and verified, never the literal 'unresolved'.
        body = await self._body(0, source_pin="a" * 40)
        assert f"source pin {'a' * 40}" in body
        assert "unresolved" not in body

    async def test_names_the_recorded_command_and_exit_status(self):
        body = await self._body(0)
        assert "`python -m pytest -q` exited 0" in body

    async def test_names_the_output_digest(self):
        import hashlib

        output = "3 passed in 0.01s\n"
        body = await self._body(0, output)
        digest = "sha256:" + hashlib.sha256(output.encode()).hexdigest()
        assert digest in body

    async def test_disclaims_every_gate_this_path_did_not_run(self):
        body = await self._body(0)
        assert "No other gates were executed on this path" in body
        # The literal success claims #820 removes, and the scorecard's gate
        # names, appear nowhere: this path ran one test command, that is all
        # the body may imply.
        assert "Tests passed before" not in body
        assert "full fitness scorecard" not in body
        for gate in ("bandit", "ruff", "mypy", "coverage"):
            assert gate not in body

    async def test_a_failed_run_is_stated_as_failed_not_passed(self):
        body = await self._body(3, "2 failed\n")
        assert "exited 3" in body
        assert "passed" not in body

    async def test_the_opened_pr_body_is_the_default_evidence_body(
        self, patch_git_ops, monkeypatch
    ):
        """run_self_branch_attempt hands the recorded exit code to the default
        body: what ships is derived from the run, not a static template."""
        captured: dict[str, str] = {}

        async def capture(repo, branch, title, body, base="main"):
            captured["body"] = body
            return await patch_git_ops.github_create_pr(repo, branch, title, body, base=base)

        monkeypatch.setattr(selfbranch, "github_create_pr", capture)

        async def cleared_check(diff, touched_paths):
            return QuarantineVerdict(cleared=True, requires_adversarial_review=False, flags=())

        attempt = new_attempt("https://github.com/org/repo", "python -m pytest -q")
        result = await run_self_branch_attempt(
            FakeSandbox(exec_result=(0, "5 passed\n")),
            "/tmp/w",
            attempt,
            _noop_patch,
            open_pr=True,
            quarantine_check=cleared_check,
        )
        assert result.pr_url is not None
        assert "`python -m pytest -q` exited 0" in captured["body"]
        assert "No other gates were executed" in captured["body"]
