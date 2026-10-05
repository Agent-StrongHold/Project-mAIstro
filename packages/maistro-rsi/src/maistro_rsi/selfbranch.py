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
from typing import Any

import structlog

from maistro.tools.git.server import (
    git_add,
    git_branch,
    git_clone,
    git_commit,
    git_diff,
    git_push,
    git_remote_tip,
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
    """One self-modification attempt: where it happens and how it's judged.

    ``commit`` pins the source checkout (#404 AC3): a full 40- or 64-hex
    digest that `git_clone` fetches directly and verifies with a final
    `rev-parse HEAD` verdict. None is not "unpinned" — the attempt resolves
    the remote's HEAD digest first (`git_remote_tip`, itself policy-gated and
    pin-enforced) and clones *that*, so a ref moving mid-cycle cannot change
    what gets branched and the result always names the source object it
    started from. Operators with their own provenance supply an explicit
    digest instead of whatever the remote's tip is when the cycle runs.
    """

    branch_name: str
    repo_url: str
    test_command: str
    commit_message: str
    pr_title: str
    pr_body: str = ""
    base_branch: str = "main"
    commit: str | None = None


@dataclass
class SelfBranchResult:
    attempt: SelfBranchAttempt
    test_exit_code: int
    test_output: str
    diff: str
    pr_url: str | None = None
    error: str | None = None
    # The verified content identity of the cloned source (#404): the digest
    # the attempt pinned — explicitly, or by resolving the remote tip — and
    # `git_clone` proved via `rev-parse HEAD`. Set on every successful run, so
    # downstream scoring/audit always knows exactly which source object the
    # cycle branched from. None means the source was never checked out.
    cloned_commit: str | None = None
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
    commit: str | None = None,
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
        commit=commit,
    )


async def _resolve_source_pin(attempt: SelfBranchAttempt) -> tuple[str | None, str | None]:
    """Resolve the attempt's source pin (#404 AC3): an explicit digest is
    used as-is; otherwise the remote's HEAD is resolved to a digest first
    (via `git_remote_tip`, itself policy-gated and pin-enforced), so the
    clone is always fetch-by-digest with a verified checkout — never
    "whatever the ref points at when the fetch happens".

    Returns ``(pin, failure)``; exactly one is None. A resolution failure
    must fail the attempt before any clone: no pin, no candidate source.
    Operators with their own provenance supply an explicit digest instead
    of whatever the remote's tip is when the cycle runs.
    """
    if attempt.commit is not None:
        return attempt.commit, None
    resolved = await git_remote_tip(attempt.repo_url)
    if not resolved.get("success") or not resolved.get("commit"):
        return None, f"source pin unresolved: {resolved}"
    return str(resolved["commit"]), None


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
    # Resolve the pin (#404 AC3): explicit digest as-is, else the remote's
    # HEAD resolved to a digest first — the clone below is always
    # fetch-by-digest against a verified object, never "whatever the ref
    # points at when the fetch happens".
    pin, pin_failure = await _resolve_source_pin(attempt)
    if pin_failure is not None:
        return SelfBranchResult(
            attempt=attempt,
            test_exit_code=1,
            test_output="",
            diff="",
            error=pin_failure,
        )
    clone = await git_clone(attempt.repo_url, workspace, commit=pin)
    if not clone.get("ok", True) or clone.get("exit_code", 0) != 0:
        return SelfBranchResult(
            attempt=attempt,
            test_exit_code=1,
            test_output="",
            diff="",
            error=f"clone failed: {clone}",
        )
    # The verified source identity when the attempt pinned (#404): a digest
    # git_clone already proved with a post-fetch `rev-parse HEAD` verdict.
    cloned_commit = clone.get("pinned_commit")

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

    pr_url: str | None = None
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
            body=attempt.pr_body or _default_pr_body(attempt, output),
            base=attempt.base_branch,
        )
        pr_url = _pr_url_of(pr)

    await logger.ainfo(
        "rsi_self_branch_attempt_complete",
        branch=attempt.branch_name,
        tests_passed=exit_code == 0,
        quarantine_cleared=quarantine_verdict.cleared if quarantine_verdict else None,
        opened_pr=pr_url is not None,
    )

    return SelfBranchResult(
        attempt=attempt,
        test_exit_code=exit_code,
        test_output=output,
        diff=diff,
        pr_url=pr_url,
        cloned_commit=cloned_commit,
        quarantine=quarantine_verdict,
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
    )


def _repo_slug(repo_url: str) -> str:
    """Extract `owner/repo` from a git URL for the GitHub CLI."""
    cleaned = repo_url.removesuffix(".git")
    return "/".join(cleaned.split("/")[-2:])


def _pr_url_of(pr: dict[str, Any]) -> str | None:
    """The created PR's URL, tolerating either key the result carries."""
    return pr.get("url") or pr.get("pr_url")


def _default_pr_body(attempt: SelfBranchAttempt, test_output: str) -> str:
    return (
        "Self-proposed change generated by an RSI cycle. Tests passed before "
        "this PR was opened.\n\n"
        f"Test command: `{attempt.test_command}`\n\n"
        "<details><summary>Test output (tail)</summary>\n\n"
        "```\n" + test_output[-2000:] + "\n```\n</details>"
    )
