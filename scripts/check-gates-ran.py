#!/usr/bin/env python3
"""Gate: the required checks must have *run* on the head being merged (#262 AC-2).

The gap this closes
-------------------
Every other gate in this repository asks whether the code is good. None asks
whether the gates ran at all on the artefact about to merge. Those are different
questions, and the second has a failure mode the first cannot see: a check that
never reports is not red, it is *absent*, and absence renders as an empty space
where a green tick would go.

For merge-group candidates, specialized service checks may now be legitimately
out of scope. Their execution evidence is represented by one unconditional
``integration-scope`` aggregate, which itself verifies that every classifier-
selected specialized job completed successfully. Pull-request candidates are
path-scoped by the same classifier (#1351): the producers (ci.yml job
conditions, integration-scope) skip exactly the legs a measured changed-file
envelope proves unreachable, so this evaluator may excuse a skipped specialized
check only on that same measured evidence. Protected pushes retain the
per-check execution-evidence contract without path scoping.

A workflow-level ``paths:`` filter is a third producer-scoping mechanism, and
it leaves no check run behind at all (#2059 repair): GitHub evaluates the
filter before any job exists, so a pull request outside the filter -- say a
docs-only PR against ``mutation.yml``'s ``packages/**/*.py`` -- produces no
run, not even ``skipped``. Absence of such a check is excusable exactly when
the measured changed-file envelope proves the trigger cannot match; absence
without that proof stays pending, because only the envelope can tell "will
never report, by design" apart from "has not reported yet". The globs and
their interpretation live in ``check-required-checks.paths_filters()`` plus
this module's conservative matcher, which fails closed: a glob it cannot
model keeps the check required. Producers that cannot run on a merge-group
candidate at all (a ``pull_request``-only job under a workflow with no
``merge_group`` trigger) are named in ``MERGE_GROUP_PR_ONLY_CHECKS`` instead
and are never requested as evidence for a synthetic queue SHA.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIRED_CHECKS_SCRIPT = REPO_ROOT / "scripts" / "check-required-checks.py"

NON_EXECUTED = frozenset({"action_required", "stale", "skipped", "cancelled"})
PENDING_EXIT = 2
INTEGRATION_SCOPE_CHECK = "integration-scope"
# GitHub's pulls.listFiles endpoint exposes at most this many files per pull
# request, even when fully paginated (#1350). The workflow's changed-files
# collector records a response at the cap as `truncated`; a truncated envelope
# is a partial measurement and must never excuse a skipped check. The same
# literal lives in .github/workflows/gates-ran.yml — keep them together
# (tests/test_gates_ran_publisher_contract.py pins the pair).
LIST_FILES_CAP = 3000
# These checks are covered by the aggregate merge-group legs rather than by
# independent jobs on the synthetic queue SHA.
MERGE_GROUP_SPECIALIZED_CHECKS = frozenset(
    {
        "docker-build",
        "hive-conductor-e2e",
        "hive-conductor-e2e-ui",
        "wheel-imports",
        "strike-ladder",
        "durable-events",
        "object storage (MinIO)",
        "postgres (pg17)",
        "postgres (pg18)",
    }
)

# Every required check whose job may be path-scoped belongs here.  The values
# are the reviewed leg names from ci_merge_group_scope.py, rather than a
# second set of path globs.  Keeping the filtering generic means a future
# non-specialized required check gets the same skip handling without changing
# the evaluator's verdict rules.
# Checks whose producer cannot run on a merge-group candidate, so they must
# not be requested as evidence for a synthetic queue SHA:
#
# - ``pr-base`` validates pull-request base policy from pull_request-only
#   payload fields.
# - ``Mutation gate (changed critical lines)`` is a `pull_request`-only job
#   (`if: github.event_name == 'pull_request'`) under a workflow whose
#   triggers carry no ``merge_group`` key, so GitHub never attaches the name
#   to a queue SHA (#2059 repair). Its PR-event enforcement still covers the
#   diff before the queue, and the nightly mutation run measures the full
#   critical set independently. Same class as ``pr-base``, arrived later
#   (#2270) without being added here.
MERGE_GROUP_PR_ONLY_CHECKS = frozenset(
    {
        "pr-base",
        "Mutation gate (changed critical lines)",
    }
)

PATH_SCOPED_CHECKS = {
    "postgres (pg17)": "postgres",
    "postgres (pg18)": "postgres",
    "object storage (MinIO)": "object_storage",
    "durable-events": "durable_events",
    "strike-ladder": "strike_ladder",
    "hive-conductor-e2e": "hive_e2e",
    "hive-conductor-e2e-ui": "hive_e2e",
    "wheel-imports": "wheel_imports",
    "docker-build": "docker_build",
}


def _load_required_checks_module() -> Any:
    """Load the workflow-contract module this evaluator judges against."""
    spec = importlib.util.spec_from_file_location("check_required_checks", REQUIRED_CHECKS_SCRIPT)
    if spec is None or spec.loader is None:  # pragma: no cover - packaging accident
        raise RuntimeError(f"cannot load {REQUIRED_CHECKS_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def required_check_names(
    *,
    base_branch: str | None = None,
    event_name: str | None = None,
) -> list[str]:
    """Return the required execution-evidence set for one candidate."""
    module = _load_required_checks_module()
    rows = module.collect()

    names = {name for _workflow, name, _scope in rows}
    if base_branch != "main":
        names -= {name for _workflow, name in module.base_coupled(rows)}
    if event_name == "merge_group":
        names -= MERGE_GROUP_SPECIALIZED_CHECKS
        names -= MERGE_GROUP_PR_ONLY_CHECKS
        names.add(INTEGRATION_SCOPE_CHECK)
    return sorted(names)


# ─── workflow-level `paths:` filters (#2059 repair) ─────────────────────────
#
# A workflow whose pull_request trigger carries `paths:` never runs outside
# the filter, so the check it produces is absent -- not `skipped` -- for PRs
# the producer scoped off. GitHub gives the evaluator no record of that
# decision, so the only honest source is the measured changed-file envelope:
# if none of the changed paths can match the producer's globs, the check's
# absence is by producer design; otherwise it is still "has not reported
# yet" and stays pending.


def _segment_regex(segment: str) -> str | None:
    """Translate one `/`-free glob segment, or None when it is not modeled."""
    out: list[str] = []
    i = 0
    while i < len(segment):
        ch = segment[i]
        if ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            end = segment.find("]", i + 1)
            if end == -1:
                return None  # unclosed class: not modeled, fail closed
            body = segment[i + 1 : end]
            if not body:
                return None
            negated = body[0] in "!^"
            if negated:
                body = body[1:]
            if not body:
                return None
            # Keep `-` unescaped so ranges survive; every other class member
            # is escaped literally.
            rendered = "".join("-" if c == "-" else re.escape(c) for c in body)
            out.append("[" + ("^" if negated else "") + rendered + "]")
            i = end + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


def _glob_regex(pattern: str) -> str | None:
    """Translate one GitHub Actions `paths:` glob into a fullmatch regex.

    GitHub's documented filter characters are `*` (within a path segment),
    `**` (across segments), `?` and `[...]`; a leading `!` negates, and the
    last matching pattern decides. Anything beyond that -- escapes, braces,
    extglobs, a `**` fused inside a segment -- is not modeled and yields
    None: the caller then cannot prove exclusion and keeps the check
    required. Failing closed costs a pended gate on exotic globs; guessing
    could cost a merged head that skipped a required gate.
    """
    if not pattern:
        return None
    if any(ch in pattern for ch in "\\{}@+"):
        return None
    segments = pattern.split("/")
    regex = ""
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            # Trailing `**` covers everything under the previous segment; the
            # `/` it sits behind was already emitted by the joiner above (and
            # does not exist at all when the glob starts with `**`).
            regex += ".*" if last else "(?:[^/]+/)*"
        else:
            if "**" in segment:
                return None  # fused globstar: ambiguous, fail closed
            piece = _segment_regex(segment)
            if piece is None:
                return None
            regex += piece
        if not last:
            # A non-last `**` group already ends in `/`; every other segment
            # needs the explicit separator ahead of the next one, so
            # `packages/**/*.py` cannot match `packagesfoo.py`.
            regex += "" if segment == "**" else "/"
    return regex


def _provably_excluded(globs: Sequence[str], files: Sequence[str]) -> bool:
    """True when none of `files` can match the trigger's glob list.

    GitHub fires a `paths:`-filtered trigger when at least one changed path
    matches a positive glob and the *last* matching glob is not a negation.
    This mirrors that ordering, returning False whenever any path can still
    fire the trigger -- including when a glob is unmodelable, so the check
    stays required rather than being excused on a guess.
    """
    compiled: list[tuple[int, bool, re.Pattern[str]]] = []
    for index, raw in enumerate(globs):
        negated = raw.startswith("!")
        regex = _glob_regex(raw[1:] if negated else raw)
        if regex is None:
            return False
        compiled.append((index, negated, re.compile(regex)))
    if not any(not negated for _index, negated, _rx in compiled):
        # No positive pattern: the trigger cannot fire for any file.
        return True
    for file in files:
        matches = [
            (index, negated) for index, negated, rx in compiled if rx.fullmatch(file) is not None
        ]
        if not matches:
            continue  # this path cannot fire the trigger
        last = max(matches, key=lambda match: match[0])
        if not last[1]:
            return False  # a positive pattern matched: the trigger can fire
    return True


@dataclass
class Verdict:
    """What the head's check runs say about whether the gates reached it."""

    absent: list[str] = field(default_factory=list)
    not_executed: list[str] = field(default_factory=list)
    unfinished: list[str] = field(default_factory=list)
    ran: list[str] = field(default_factory=list)
    #: Required checks whose absence (or bare skip) is excused by proof that
    #: the producer's trigger cannot fire for this candidate at all (#2059
    #: repair). Recorded so the ok-path can name what was excused; never a
    #: finding, and never counted as evidence that something ran.
    excused: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.absent and not self.not_executed and not self.unfinished

    @property
    def pending(self) -> bool:
        return not self.not_executed and bool(self.absent or self.unfinished)


def _supersedes(candidate: dict[str, Any], incumbent: dict[str, Any]) -> bool:
    """Whether `candidate` should replace `incumbent` as a name's judged attempt.

    Multiple check runs can share one name for one commit: GitHub's own reruns,
    and -- since the quality.yml/security.yml concurrency fix (#1229) -- two
    independently triggered workflow runs (`push` and `pull_request`) landing
    in one concurrency group, where the loser is `cancelled` rather than
    simply absent. A `cancelled`/`skipped`/`stale`/`action_required` run never
    certifies that the enforcement it names ran to a verdict, so it must never
    shadow a sibling run for the same name that did -- regardless of which one
    the API happens to return later. Only when both runs agree on having
    executed (or both failed to) does the greater check-run ID decide. This
    matches integration-scope's attempt ordering, independent of API/page order.
    Do not compare workflow run IDs or run_attempt (not check-run fields), nor
    timestamps: queued checks may have no start time, and old jobs can start or
    finish after their replacements. Legacy caller payloads without numeric
    check-run IDs retain their ordered-list contract.
    """
    candidate_executed = candidate.get("conclusion") not in NON_EXECUTED
    incumbent_executed = incumbent.get("conclusion") not in NON_EXECUTED
    if candidate_executed != incumbent_executed:
        return candidate_executed
    candidate_id = candidate.get("id")
    incumbent_id = incumbent.get("id")
    if type(candidate_id) is int and type(incumbent_id) is int:
        return candidate_id > incumbent_id
    return True


def evaluate(
    required: list[str],
    check_runs: list[dict[str, Any]],
    *,
    require_complete: bool,
    scope: Mapping[str, bool] | None = None,
    scope_measured: bool = True,
    untriggerable: frozenset[str] = frozenset(),
) -> Verdict:
    latest: dict[str, dict[str, Any]] = {}
    for run in check_runs:
        name = run.get("name")
        if not isinstance(name, str):
            continue
        incumbent = latest.get(name)
        if incumbent is None or _supersedes(run, incumbent):
            latest[name] = run

    # A measured out-of-scope check may be explicitly skipped.  Absence is
    # still pending for these (we cannot prove why it is absent), and any
    # conclusion other than skipped remains evidence that must be judged
    # normally.  The workflow-level-`paths:` mechanism below is different in
    # exactly one way: for those producers the measured envelope CAN prove
    # why the check is absent, so absence is excusable there (#2059 repair).
    if scope is not None:
        required = [
            name
            for name in required
            if not (
                name in PATH_SCOPED_CHECKS
                and not scope.get(PATH_SCOPED_CHECKS[name], True)
                and latest.get(name, {}).get("conclusion") == "skipped"
            )
        ]

    verdict = Verdict()
    for name in required:
        bucket = _classify_check(
            name,
            latest.get(name),
            require_complete=require_complete,
            scope_measured=scope_measured,
            untriggerable=untriggerable,
        )
        getattr(verdict, bucket).append(name)
    return verdict


def _classify_check(
    name: str,
    candidate: dict[str, Any] | None,
    *,
    require_complete: bool,
    scope_measured: bool,
    untriggerable: frozenset[str],
) -> str:
    """Return the verdict bucket a single required check belongs in."""
    if candidate is None:
        if name in untriggerable:
            # The measured envelope proves this producer's `paths:`
            # filter cannot match, so the check is absent by producer
            # design rather than still arriving (#2059 repair).
            return "excused"
        return "absent"
    conclusion = candidate.get("conclusion")
    if conclusion in NON_EXECUTED:
        if name in untriggerable and conclusion == "skipped":
            return "excused"
        if not scope_measured and name in PATH_SCOPED_CHECKS and conclusion == "skipped":
            return "unfinished"
        return "not_executed"
    if candidate.get("status") != "completed":
        return "unfinished" if require_complete else "ran"
    return "ran"


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path}: unreadable JSON payload") from exc


def _load(path: Path) -> list[dict[str, Any]]:
    payload = _read_json(path)
    runs: Any
    if isinstance(payload, list):
        runs = payload
    elif isinstance(payload, dict):
        runs = payload.get("check_runs")
    else:
        raise ValueError(f"{path}: expected an object or a list, got {type(payload).__name__}")
    if not isinstance(runs, list):
        raise ValueError(f"{path}: no `check_runs` array")
    return [run for run in runs if isinstance(run, dict)]


def _load_scope_classifier() -> Any:
    path = REPO_ROOT / "scripts" / "ci_merge_group_scope.py"
    spec = importlib.util.spec_from_file_location("ci_merge_group_scope_for_gates_ran", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _pull_request_scope(path: Path) -> tuple[dict[str, bool] | None, bool]:
    try:
        payload = _read_json(path)
    except ValueError:
        return None, False
    if not isinstance(payload, dict):
        return None, False
    measured = payload.get("measured")
    if type(measured) is not bool or not measured:
        return None, False
    if payload.get("truncated"):
        # A truncated envelope is a *partial* measurement: the paths beyond
        # the cap are unmeasured and may carry every specialized leg, so
        # scope is ambiguous. Raising reaches the CLI as a pending reason via
        # _scope_for_args' ValueError path, never as a scope that could
        # excuse a skipped check.
        raise ValueError(
            f"changed-file set was truncated at GitHub's {LIST_FILES_CAP}-file listFiles cap"
        )
    changed_files = payload.get("files")
    if not isinstance(changed_files, list) or not all(
        isinstance(item, str) for item in changed_files
    ):
        return None, False
    return _load_scope_classifier().classify(changed_files), True


def _measured_changed_files(path: Path) -> list[str]:
    """The envelope's measured paths, or ValueError when it proves nothing.

    The same bar `_pull_request_scope` applies before excusing a skip: an
    unmeasured or truncated envelope is a partial measurement, and a partial
    measurement must never excuse an absent check either.
    """
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError("changed-file payload is not an object")
    measured = payload.get("measured")
    if type(measured) is not bool or not measured:
        raise ValueError("changed-file envelope was not measured")
    if payload.get("truncated"):
        raise ValueError(
            f"changed-file set was truncated at GitHub's {LIST_FILES_CAP}-file listFiles cap"
        )
    files = payload.get("files")
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise ValueError("changed-file payload has no files array of strings")
    return files


def untriggerable_checks(event_name: str | None, changed_files_path: Path | None) -> frozenset[str]:
    """Required checks whose producer's `paths:` filter cannot fire (#2059).

    A workflow-level `paths:` filter is evaluated by GitHub before any job
    exists, so outside the filter the producer leaves no check run at all.
    For each such producer this asks the only answerable question: can the
    measured changed-file set match the reviewed globs at all? When it
    cannot, absence of that check on this head is by producer design and is
    excusable; any other case -- unmeasured envelope, unmodelable glob, a
    file that could still match -- returns nothing, and the absence stays
    pending. Empty on every event other than pull_request: merge-group
    candidates of such producers are handled by MERGE_GROUP_PR_ONLY_CHECKS,
    which needs no envelope.
    """
    if event_name != "pull_request" or changed_files_path is None:
        return frozenset()
    try:
        files = _measured_changed_files(changed_files_path)
        filters = _load_required_checks_module().paths_filters()
    except (
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        ImportError,
        RuntimeError,
    ) as exc:
        # _scope_for_args already reports envelope problems as pending
        # reasons; an unloadable contract module must not silently shrink
        # the required set, so both leave the set untouched here.
        print(f"gates-ran: path-filter exclusion unavailable ({exc})")
        return frozenset()
    return frozenset(name for name, globs in filters.items() if _provably_excluded(globs, files))


def _scope_for_args(
    event_name: str | None, changed_files_path: Path | None
) -> tuple[dict[str, bool] | None, bool]:
    if event_name != "pull_request":
        return None, True
    if changed_files_path is None:
        print("PENDING: path-scoped execution scope is ambiguous (changed files were not measured)")
        return None, False
    try:
        scope, measured = _pull_request_scope(changed_files_path)
        if not measured:
            print(
                "PENDING: path-scoped execution scope is ambiguous (changed-file payload is invalid)"
            )
        return scope, measured
    except (OSError, TypeError, ValueError, json.JSONDecodeError, ImportError, RuntimeError) as exc:
        print(f"PENDING: path-scoped execution scope is ambiguous ({exc})")
        return None, False


def _render_verdict(verdict: Verdict, required: list[str]) -> int:
    """Print the verdict and return its process exit code."""
    if verdict.ok:
        if verdict.excused:
            print(
                f"ok: all {len(required)} required check(s) judged on this head; "
                f"{len(verdict.excused)} absent by measured trigger scope:"
            )
            for name in verdict.excused:
                print(f"    excused, producer cannot trigger: {name}")
        else:
            print(f"ok: all {len(required)} required check(s) ran on this head")
        return 0

    heading = (
        "PENDING: execution evidence is still arriving"
        if verdict.pending
        else "FAIL: the gate set did not reach this commit"
    )
    print(f"{heading}\n")
    if verdict.absent:
        print(f"  not present yet ({len(verdict.absent)}):")
        for name in verdict.absent:
            print(f"    {name}")
    if verdict.not_executed:
        print(f"\n  present but did not execute to a verdict ({len(verdict.not_executed)}):")
        for name in verdict.not_executed:
            print(f"    {name}")
    if verdict.unfinished:
        print(f"\n  started but not finished ({len(verdict.unfinished)}):")
        for name in verdict.unfinished:
            print(f"    {name}")
    return PENDING_EXIT if verdict.pending else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-runs", type=Path, required=True)
    parser.add_argument("--require-complete", action="store_true")
    parser.add_argument("--base-branch")
    parser.add_argument("--event-name")
    parser.add_argument(
        "--changed-files",
        type=Path,
        help="measured PR changed-file envelope used for path-scoped skip handling",
    )
    args = parser.parse_args(argv)

    try:
        runs = _load(args.check_runs)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(
            f"FAIL: the check-run payload is unreadable, so whether the gates ran is unmeasured.\n  {exc}"
        )
        return 1

    required = required_check_names(
        base_branch=args.base_branch,
        event_name=args.event_name,
    )
    if not required:
        print("FAIL: the required-check contract is empty; nothing to verify ran.")
        return 1

    scope, scope_measured = _scope_for_args(args.event_name, args.changed_files)
    untriggerable = untriggerable_checks(args.event_name, args.changed_files)

    verdict = evaluate(
        required,
        runs,
        require_complete=args.require_complete,
        scope=scope,
        scope_measured=scope_measured,
        untriggerable=untriggerable,
    )
    return _render_verdict(verdict, required)


if __name__ == "__main__":
    raise SystemExit(main())
