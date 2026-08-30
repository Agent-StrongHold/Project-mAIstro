#!/usr/bin/env python3
"""Coordinate AC-state review and merge-time regression checks (#620).

The implementation module owns measurement, branch-note validation, and the
per-change mandate. This stable entry point separates two questions that used
to be conflated:

* review time asks whether the candidate regresses from the trusted bound;
  an improvement is useful evidence, but it is not a reason to rewrite branch
  bookkeeping; and
* merge time asks whether the exact candidate preserves the *actual measured
  state* of the immutable base it is about to replace.

Merge groups and protected-branch pushes measure that base revision in a
detached worktree and compare the candidate against it. That comparison is the
serialization point that makes improvements durable. Requiring every open PR
to bank the same improvement as develop moves only recreates the synchronization
lock the per-branch note scheme was meant to remove.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import check_ac_state_impl as _impl  # noqa: E402
from ci_base_revision import BaseRevisionError, resolve_base_revision_from_env  # noqa: E402

# Preserve the public module surface: unit tests and local callers historically
# load scripts/check-ac-state.py by path and call helpers such as `ratchet`.
for _name, _value in vars(_impl).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)

_PROTECTED_PUSH_REFS = {
    "refs/heads/develop",
    "refs/heads/integration",
    "refs/heads/main",
}
_BASE_MEASUREMENT = "AC_STATE_BASE_MEASUREMENT"

# Review-time exactness used to make every improvement a required bookkeeping
# edit. The merge-group guard below now measures the actual immutable base, so
# it is the stronger oracle: a later PR cannot spend an improvement because the
# next merge group re-measures develop itself. Keep the implementation's policy
# available for merge-group diagnostics, but make review-time slack
# informational rather than a branch mutation requirement.
_ORIGINAL_SLACK_POLICY = _impl._slack_this_run_enforces


def _review_slack_policy(improvements: list[str]) -> list[str]:
    """Do not serialize contributors merely because the measurement improved.

    A pull request still fails on regressions. Improvements are made durable at
    the merge serialization point by `_guard_actual_base`, which measures the
    actual base tree rather than trusting a candidate-authored note. Requiring a
    note here adds no safety and is exactly the rebase/re-bank tax this project
    is removing.
    """
    if not improvements:
        return []
    if os.environ.get("GITHUB_EVENT_NAME") == "merge_group":
        return _ORIGINAL_SLACK_POLICY(improvements)
    print(
        "review-time AC-state improvement observed; no bank is required.\n"
        "The merge-group actual-base guard re-measures the immutable develop base "
        "and owns monotonicity, so branch notes are not a synchronization requirement.\n  "
        + "\n  ".join(improvements)
    )
    return []


def _with_review_slack(callable_: Any, *args: Any, **kwargs: Any) -> Any:
    """Run an implementation entry point with review-time slack informational."""
    previous = _impl._slack_this_run_enforces
    _impl._slack_this_run_enforces = _review_slack_policy
    try:
        return callable_(*args, **kwargs)
    finally:
        _impl._slack_this_run_enforces = previous


def _run_impl(argv: list[str]) -> int:
    return int(_with_review_slack(_impl.main, argv))


def ratchet(totals: dict[str, Any], measured: bool, bank: bool) -> int:
    """Public ratchet surface with the same no-rebank review policy as the CLI."""
    return int(_with_review_slack(_impl.ratchet, totals, measured, bank))


def _protected_push() -> bool:
    return (
        os.environ.get("GITHUB_EVENT_NAME") == "push"
        and os.environ.get("GITHUB_REF") in _PROTECTED_PUSH_REFS
    )


def _needs_actual_base() -> bool:
    return os.environ.get("GITHUB_EVENT_NAME") == "merge_group" or _protected_push()


def _actual_base_revision() -> str:
    """The immutable revision this synthetic/protected result replaces."""
    return resolve_base_revision_from_env()


def _out_path(argv: list[str]) -> Path:
    for index, arg in enumerate(argv):
        if arg == "--out" and index + 1 < len(argv):
            return Path(argv[index + 1])
        if arg.startswith("--out="):
            return Path(arg.split("=", 1)[1])
    return _impl.DEFAULT_OUT


def _without_ratchet(argv: list[str]) -> list[str]:
    """Protected pushes use actual-parent regression, not review-time exactness."""
    return [arg for arg in argv if arg != "--ratchet"]


def _measure_base(base_rev: str, report: Path) -> str | None:
    """Measure `base_rev` with its own code and dependencies, fail closed."""
    root = _impl.ROOT
    with tempfile.TemporaryDirectory(prefix="maistro-ac-base-") as tmp:
        worktree = Path(tmp) / "tree"
        added = subprocess.run(
            ["git", "worktree", "add", "--detach", str(worktree), base_rev],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if added.returncode != 0:
            return f"could not create base worktree for {base_rev}: {added.stderr.strip()}"
        try:
            env = {
                **os.environ,
                _BASE_MEASUREMENT: "1",
                # A base measurement asks only what the tree proves. It is not
                # itself a merge-group policy run, and its unit tests must not
                # inherit the outer job's event classification.
                "GITHUB_EVENT_NAME": "pull_request",
            }
            measured = subprocess.run(
                [
                    "uv",
                    "run",
                    "--project",
                    str(worktree),
                    "--locked",
                    "--all-extras",
                    "python",
                    "scripts/check-ac-state.py",
                    "--out",
                    str(report),
                    "--run-tests",
                ],
                cwd=worktree,
                env=env,
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
            if measured.returncode != 0 or not report.is_file():
                tail = (measured.stdout + measured.stderr)[-4000:]
                return f"could not measure actual AC-state base {base_rev}:\n{tail}"
            return None
        finally:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )


def _report_totals(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("measured") is not True:
        raise ValueError(f"{path} is not a --run-tests AC-state measurement")
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        raise ValueError(f"{path} records no totals")
    missing = [name for name in (*_impl.RATCHETED, *_impl.FLOORED) if name not in totals]
    if missing:
        raise ValueError(f"{path} is missing bounded counters: {', '.join(missing)}")
    return totals


def _actual_base_regressions(
    base: dict[str, Any],
    candidate: dict[str, Any],
    floors: dict[str, float],
) -> list[str]:
    """Only worse-than-base movement; improvement becomes the next base itself.

    `floors` is applied to the *base* before comparing, for the same reason the
    note comparison applies it: an authorized fall is a correction of a number
    that was never true, and a comparison that does not know that reports it as
    a regression (#662 review). Without this the whole mechanism worked on the
    branch and then failed in the merge queue — which is the only place the
    fall it exists for could ever have landed.
    """
    regressions, _improvements = _impl._compare(_impl._lowered(base, floors), candidate)
    return regressions


def _spent_grants_removed(
    base: dict[str, Any],
    candidate: dict[str, Any],
    floors: dict[str, float],
) -> list[str] | None:
    """Grants this push relies on and no longer ships, or None if unreadable.

    "Relies on" is measured, not assumed: a grant counts only where the counter
    does *not* regress with it and *does* without. That keeps the honest cases
    passing -- a push that prunes a grant the base has already overtaken
    regresses nothing without it, so it has nothing to answer for, and a push
    that neither spends nor touches one is unaffected -- and it keeps a push
    that falls below even the granted floor being reported for that fall rather
    than for the removal.
    """
    # Read first, and whatever the base says. A protected push that adds the
    # *first* grant has no base floors at all, so returning early on `not
    # floors` skipped the only validation this path performs -- and `--ratchet`
    # is stripped here, so nothing else looks. A malformed record then passed
    # with unchanged measurements and became the base every later run reads and
    # refuses (Codex, #693).
    try:
        present = _impl.candidate_grants()
    except _impl.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}")
        return None
    if not floors:
        return []
    load_bearing = {
        counter
        for counter in floors
        if not _regresses(base, candidate, {counter: floors[counter]}, counter)
        and _regresses(base, candidate, {}, counter)
    }
    return sorted(
        f"{counter}@{floors[counter]}"
        for counter in load_bearing
        if present.get(counter) != floors[counter]
    )


def _regresses(
    base: dict[str, Any],
    candidate: dict[str, Any],
    floors: dict[str, float],
    counter: str,
) -> bool:
    """Whether one counter regresses under `floors`.

    The status, not the formatted line (Codex, #693). Comparing the rendered
    lists made a counter that regresses *either way* look load-bearing, because
    the two messages name different floors -- base 20, grant 15, candidate 12
    reports "floor still says 15" with the grant and "20" without. The push
    would then be refused for removing a grant rather than for the deeper fall
    it actually took, which is the more serious of the two and the one an
    operator needs told.
    """
    prefix = f"{counter}: "
    return any(
        line.startswith(prefix) for line in _actual_base_regressions(base, candidate, floors)
    )


def _guard_actual_base(
    base_report: Path,
    candidate_report: Path,
    base_rev: str,
    *,
    check_retention: bool = False,
) -> int:
    """Compare the candidate against the actual measured base.

    `check_retention` is the protected-push path and only that path. A merge
    group keeps `--ratchet`, so `ratchet()` runs there and its
    `_removed_binding_grants` already answers the retention question; asking it
    twice would enforce the same rule in two places and make either one look
    optional. A protected push strips `--ratchet`, and that is the gap (#685).
    """
    try:
        base = _report_totals(base_report)
        candidate = _report_totals(candidate_report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"FAIL: actual-base AC-state comparison could not be read: {exc}")
        return 1
    try:
        floors, _reasons = _impl.authorized_floors(base_rev)
    except _impl.RatchetProvenanceError as exc:
        print(f"FAIL: {exc}")
        return 1
    # A protected push strips `--ratchet`, so `ratchet()` never runs and neither
    # does its retention bookkeeping: on this path a commit could spend an
    # authorized fall and delete the grant that permitted it, and the guard
    # below -- which applies that grant to the base -- would pass (#685). This
    # is the hole #672 finding 2 closed for the PR path, still open on the one
    # path with no review in front of it.
    spent = _spent_grants_removed(base, candidate, floors) if check_retention else []
    if spent is None:
        return 1
    if spent:
        print(f"FAIL: this push spends an authorized floor and removes it: {', '.join(spent)}\n")
        print(
            "  Without the grant the comparison against the actual base "
            f"{base_rev} reports a regression, so the fall is only permitted "
            "because the grant is there -- and this commit takes it away in the "
            "same breath. Spend it or prune it, not both: a grant nothing can "
            "read is not a record of why the number moved."
        )
        return 1

    regressions = _actual_base_regressions(base, candidate, floors)
    if regressions:
        print(f"FAIL: AC-state regressed from the actual measured base {base_rev}\n")
        for line in regressions:
            print(f"  - {line}")
        print(
            "\nThis comparison is independent of branch notes: a merge-group-only "
            "improvement becomes part of the next base measurement, so a later "
            "PR cannot spend it even when no author could have pre-banked it."
        )
        if floors:
            print(
                "Authorized floors were applied to the base before comparing: "
                + ", ".join(f"{name}@{value}" for name, value in sorted(floors.items()))
            )
        return 1
    print(
        f"OK: candidate preserves the actual measured AC-state of base {base_rev}; "
        "any improvement becomes the next base measurement."
    )
    return 0


def main(argv: list[str]) -> int:
    # The detached base invokes the same public path. Do not recursively measure
    # another base from inside that measurement.
    if os.environ.get(_BASE_MEASUREMENT) == "1" or not _needs_actual_base():
        return _run_impl(argv)

    try:
        base_rev = _actual_base_revision()
    except BaseRevisionError as exc:
        print(f"FAIL: this run requires an immutable AC-state base revision: {exc}")
        return 1

    with tempfile.TemporaryDirectory(prefix="maistro-ac-guard-") as tmp:
        base_report = Path(tmp) / "base.json"
        error = _measure_base(base_rev, base_report)
        if error is not None:
            print(f"FAIL: {error}")
            return 1

        # A protected-branch push has no author-side review question left to
        # answer. Its invariant is simply no regression from the actual parent.
        # Merge groups still run the ordinary ratchet/mandate as well, which
        # preserves the reviewed branch's regression and touched-criterion
        # contracts while the actual-base guard makes every improvement part of
        # the next base without requiring an author-side bank commit.
        delegated = _without_ratchet(argv) if _protected_push() else argv
        code = _run_impl(delegated)
        if code:
            return code
        candidate_report = _out_path(delegated)
        return _guard_actual_base(
            base_report,
            candidate_report,
            base_rev,
            check_retention=_protected_push(),
        )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
