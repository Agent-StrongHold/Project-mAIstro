"""Self-modification workflow: clone, branch, patch, test, and (optionally)
propose a PR against the RSI agent's own codebase — all from inside an
isolated `MicroVmSandbox`.

Reuses `maistro.tools.git` (clone/branch/commit/push/PR) rather than
reimplementing repo plumbing; the only RSI-specific piece is the `apply_patch`
callback, which the runner supplies and which actually drives the agent that
proposes the change. Keeping that out of this module means the git/sandbox
wiring is testable on its own, with a stub patch function.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import structlog

from maistro.tools.git.server import (
    git_add,
    git_branch,
    git_clone,
    git_commit,
    git_diff,
    git_push,
    github_create_pr,
)
from maistro_rsi.protocols import ApplyPatchFn, MicroVmSandbox, WorkspaceProbeFn
from maistro_rsi.quarantine import QuarantineVerdict

logger = structlog.get_logger()

# Injected by the runner: given the captured diff and the paths it touches,
# decide whether the change may leave the sandbox as a PR. Kept as an
# injected callable (mirroring `apply_patch`) so this module stays testable
# without a live Warden instance.
QuarantineCheckFn = Callable[[str, list[str]], Awaitable[QuarantineVerdict]]

_DIFF_PATH_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)


def paths_touched_by_diff(diff: str) -> list[str]:
    """Extract the set of file paths a unified diff touches, in first-seen order."""
    seen: list[str] = []
    for match in _DIFF_PATH_RE.finditer(diff):
        for path in (match.group(1), match.group(2)):
            if path not in seen:
                seen.append(path)
    return seen


@dataclass
class SelfBranchAttempt:
    """One self-modification attempt: where it happens and how it's judged."""

    branch_name: str
    repo_url: str
    test_command: str
    commit_message: str
    pr_title: str
    pr_body: str = ""
    base_branch: str = "main"


@dataclass
class SelfBranchResult:
    attempt: SelfBranchAttempt
    test_exit_code: int
    test_output: str
    diff: str
    pr_url: str | None = None
    error: str | None = None
    quarantine: QuarantineVerdict | None = None
    # Differential workspace evidence: the same probe run before the patch
    # (baseline) and after it (candidate), so downstream scoring battles over
    # what the change measurably did. None when no probe was supplied.
    baseline_metrics: dict[str, float] | None = None
    candidate_metrics: dict[str, float] | None = None

    @property
    def tests_passed(self) -> bool:
        return self.error is None and self.test_exit_code == 0


def new_attempt(
    repo_url: str,
    test_command: str,
    *,
    base_branch: str = "main",
    label: str = "rsi",
) -> SelfBranchAttempt:
    """Build an attempt with a unique, collision-free branch name."""
    run_id = uuid.uuid4().hex[:10]
    return SelfBranchAttempt(
        branch_name=f"{label}/{run_id}",
        repo_url=repo_url,
        test_command=test_command,
        commit_message=f"RSI attempt {run_id}: self-proposed improvement",
        pr_title=f"[RSI {run_id}] Self-proposed improvement",
        base_branch=base_branch,
    )


async def run_self_branch_attempt(
    sandbox: MicroVmSandbox,
    workspace: str,
    attempt: SelfBranchAttempt,
    apply_patch: ApplyPatchFn,
    *,
    open_pr: bool = False,
    quarantine_check: QuarantineCheckFn | None = None,
    model: str | None = None,
    probe: WorkspaceProbeFn | None = None,
) -> SelfBranchResult:
    """Run one clone → branch → (probe) → patch → (probe) → test → quarantine → (PR) cycle.

    A PR requires passing tests *and* a cleared quarantine verdict — a
    self-modifying agent doesn't get to propose changes to its own codebase
    that fail its own test suite, and it doesn't get to ship anything,
    including changes to its own harness, that hasn't been scanned (and, for
    sensitive-surface diffs, adversarially reviewed) first. See
    `maistro_rsi.quarantine` for what "cleared" requires.

    When ``probe`` is supplied it runs twice against the same checkout — right
    after the branch (pre-patch baseline) and right after the patch is
    committed (candidate) — so callers score the *measured differential* of the
    change. Probes that need test artifacts should run those commands
    themselves; the probe sees the workspace state, not the later test run.
    """
    clone = await git_clone(attempt.repo_url, workspace)
    if not clone.get("ok", True) or clone.get("exit_code", 0) != 0:
        return SelfBranchResult(
            attempt=attempt,
            test_exit_code=1,
            test_output="",
            diff="",
            error=f"clone failed: {clone}",
        )

    await git_branch(workspace, attempt.branch_name, checkout=True)
    baseline_metrics = await probe(sandbox, workspace) if probe is not None else None
    await apply_patch(sandbox, workspace, model)

    # Stage and capture the diff BEFORE committing — after the commit the
    # working tree matches HEAD and `git diff` is empty, which would hand the
    # quarantine gate (and the PR body) a blank change to inspect. Capturing
    # the staged diff pre-commit may include sensitive files that git_commit
    # unstages at commit time, so quarantine sees a superset of what ships —
    # fail-safe in the right direction.
    await git_add(workspace)
    diff_result = await git_diff(workspace, staged=True)
    diff = str(diff_result.get("stdout", ""))

    await git_commit(workspace, attempt.commit_message, add_all=True)
    candidate_metrics = await probe(sandbox, workspace) if probe is not None else None

    exit_code, output = await sandbox.exec(attempt.test_command, timeout=900)

    quarantine_verdict: QuarantineVerdict | None = None
    if quarantine_check is not None:
        quarantine_verdict = await quarantine_check(diff, paths_touched_by_diff(diff))

    result = SelfBranchResult(
        attempt=attempt,
        test_exit_code=exit_code,
        test_output=output,
        diff=diff,
        quarantine=quarantine_verdict,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
    )

    # A missing quarantine check is a DENY, not a bypass: shipping requires an
    # affirmative cleared verdict. The old `is None or ...` made the safety
    # property of a self-modifying system hang on a comment asking callers to
    # please pass the parameter — fail-open by convention. Callers that don't
    # open PRs are unaffected; callers that do must wire quarantine.
    cleared_to_ship = quarantine_verdict is not None and quarantine_verdict.cleared
    if open_pr and exit_code == 0 and cleared_to_ship:
        await git_push(workspace, attempt.branch_name)
        pr = await github_create_pr(
            repo=_repo_slug(attempt.repo_url),
            branch=attempt.branch_name,
            title=attempt.pr_title,
            # Rendered from the attempt's recorded outcomes — the test exit
            # code and the quarantine verdict — never a static success
            # sentence (#820, from #304).
            body=attempt.pr_body or _default_pr_body(attempt, result),
            base=attempt.base_branch,
        )
        result.pr_url = pr.get("url") or pr.get("pr_url")

    await logger.ainfo(
        "rsi_self_branch_attempt_complete",
        branch=attempt.branch_name,
        tests_passed=exit_code == 0,
        quarantine_cleared=quarantine_verdict.cleared if quarantine_verdict else None,
        opened_pr=result.pr_url is not None,
    )

    return result


def _repo_slug(repo_url: str) -> str:
    """Extract `owner/repo` from a git URL for the GitHub CLI."""
    cleaned = repo_url.removesuffix(".git")
    return "/".join(cleaned.split("/")[-2:])


def _default_pr_body(attempt: SelfBranchAttempt, result: SelfBranchResult) -> str:
    """PR text rendered from the attempt's recorded outcomes (#820, from #304).

    Each listed gate is one that actually ran, with its recorded result — the
    test command's exit code, the quarantine verdict. Nothing here asserts a
    pass the record doesn't show: a gate that never ran (e.g. no quarantine
    verdict was recorded) is stated as NOT RUN, and a failed gate renders as
    failed (a PR with such a body can't be opened by ``run_self_branch_attempt``
    — it gates on the same records — but the rendering stays truthful for any
    caller that supplies a body downstream).
    """
    quarantine = result.quarantine
    lines = [
        "Self-proposed change generated by an RSI cycle.",
        "",
        "Recorded gate results (only gates that actually ran are listed):",
        (
            f"- tests: {'passed' if result.tests_passed else 'FAILED'} "
            f"(exit {result.test_exit_code}) — `{attempt.test_command}`"
        ),
    ]
    if quarantine is not None:
        verdict = "cleared" if quarantine.cleared else "DENIED"
        lines.append(
            f"- quarantine: {verdict}" + (f" — {quarantine.reason}" if quarantine.reason else "")
        )
    else:
        lines.append("- quarantine: NOT RUN — no verdict was recorded")
    lines += [
        "",
        "<details><summary>Test output (tail)</summary>",
        "",
        "```",
        result.test_output[-2000:] + "\n```\n</details>",
    ]
    return "\n".join(lines)
