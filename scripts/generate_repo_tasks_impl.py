#!/usr/bin/env python3
"""Generate post-cutoff bug-fix tasks from this repository's own git history.

Implements SPEC-281 §4. Every task is a real commit that fixed a real bug in
this codebase, admitted only when the fail-to-pass transition is *observed by
execution* rather than inferred from the commit message.

Why this benchmark exists
-------------------------
Every public benchmark corpus is in some model's weights. The one contamination
defence nothing can defeat is chronological: a bug fixed after a model's
training cutoff cannot have been memorised. This repository produces such tasks
continuously, for free, and the corpus gets *fresher* over time instead of
saturating — the opposite of every corpus in ``benchmarks/third_party/``.

How a commit becomes a task
---------------------------
The construction is SWE-bench's, and one detail carries it: a commit that *adds*
a test cannot be run against its parent, because the test does not exist there.
So the commit's diff is split.

    test_patch  = changes to test files only
    gold_patch  = changes to everything else (the actual fix)

    check out parent in a scratch worktree
    apply test_patch                 -> named tests MUST FAIL
    apply gold_patch on top          -> named tests MUST PASS

Tests already passing before ``gold_patch`` mean the commit is a refactor or a
test-only change, not a fix. Tests still failing after it mean the commit is
broken or environment-dependent. Only the fail→pass transition admits a task,
which is what makes "fix typo" commits and aspirational commit messages
disappear without anyone curating a list.

At scoring time a genome sees ``repo_state + test_patch`` and the issue text. It
never sees ``gold_patch``.

Honest limits
-------------
Stated here as well as in the spec, because a home-made benchmark is exactly the
kind that gets quoted out of context:

* **Never comparable to a published number.** No ``official_comparable`` flag can
  be true for this corpus. It measures the ability to fix bugs in *this*
  codebase.
* **Difficulty is uncontrolled and drifts.** Absolute scores are not comparable
  across regenerations. Pin the task set by commit range for any comparison that
  matters, and compare genomes only within one snapshot.
* **Small.** This repo yields tens of tasks, not thousands. Never quote a
  percentage without ``samples_evaluated`` beside it.
* **Per-model validity.** A task only defeats contamination for models whose
  training cutoff predates its commit date. The corpus records each date;
  filtering is the consumer's job (``repo_history.load_repo_tasks``).

Usage
-----
    python3 scripts/generate_repo_tasks.py --limit 20
    python3 scripts/generate_repo_tasks.py --since 2026-07-01 --output corpus.json
    python3 scripts/generate_repo_tasks.py --resume     # continue a partial run
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = (
    REPO
    / "packages"
    / "maistro-evolve"
    / "src"
    / "maistro_evolve"
    / "benchmarks"
    / "corpora"
    / "repo_history_tasks.json"
)

_SRC_RE = re.compile(r"^packages/[^/]+/(src|backend)/.*\.py$")
# Test files, at any depth under a tests/ directory.
#
# The earlier form anchored conftest directly under tests/ (`tests?/conftest\.py$`),
# so a NESTED conftest — `tests/benchmarks/conftest.py` — classified as source.
# That is not cosmetic: an unclassified conftest lands in the gold patch, which
# means applying test_patch alone omits the fixtures the new tests need. The
# tests then fail for a missing-fixture reason rather than the actual bug, the
# gold patch restores the conftest, and the commit registers a fail->pass
# transition it did not earn. The generator would admit the task and score
# genomes against a bug that was never there.
_TEST_RE = re.compile(r"(^|/)tests?/(.*/)?(test_[^/]*|conftest)\.py$")

# Generation is the expensive step (two pytest runs per candidate), so it is
# bounded and checkpointed rather than assumed to finish in one sitting.
_DEFAULT_TIMEOUT_S = 300

# Size ceilings on the gold patch. A fail->pass transition is necessary but not
# sufficient for a *useful* task: this repo's history contains commits that add
# an entire vendored corpus (4,919 lines across 12 files) and legitimately flip
# their tests from fail to pass. Handing a genome a commit message and expecting
# it to reproduce that is not a benchmark — every genome scores zero and the
# task discriminates nothing.
#
# SWE-bench applies the same kind of filter for the same reason; its tasks are
# small and localized (median patch well under 50 lines). These ceilings are
# deliberately generous relative to that, and are recorded in the corpus so a
# consumer knows how it was filtered rather than having to infer it.
_DEFAULT_MAX_PATCH_LINES = 300
_DEFAULT_MAX_SRC_FILES = 5

# The issue text is the entire problem statement a genome gets. Below some
# length it is not a task, it is a guess: the first corpus admitted a merge
# commit whose complete issue text was "Develop (#243)", which measures
# clairvoyance rather than debugging.
#
# Deliberately low. The aim is to exclude commits carrying no statement at all,
# not to impose a house style — a terse but specific subject like
# "fix(rsi): trim resumed transcripts to fit the smallest context" is a perfectly
# good task and is well under any threshold that would start rejecting real work.
_DEFAULT_MIN_ISSUE_CHARS = 40

# ...and an upper bound, which turned out to be the one that mattered. The first
# corpus admitted `Develop (#243)`, a squash-merge whose issue text is 72,263
# characters of changelog covering dozens of unrelated PRs. It was originally
# diagnosed here as having *no* problem statement — that was a misreading of a
# truncated display; the real defect is the opposite. Either way it is not a
# task: a genome handed a wall of text describing thirty changes and asked to
# produce one specific fix is being tested on extraction, not debugging.
#
# A genuine bug report in this repo runs a few hundred to a couple of thousand
# characters. 4,000 leaves generous room for a detailed one while excluding
# anything that is plainly an aggregated changelog.
_DEFAULT_MAX_ISSUE_CHARS = 4000

# Commits authored by the RSI loop itself. Excluded for INDEPENDENCE, not for
# quality — they are genuine fail-to-pass transitions with real messages, so no
# length or size filter catches them. Scoring the loop on bugs it introduced and
# then fixed is measuring it against its own homework: the fix is drawn from the
# same distribution as the failure, so a genome that shares its predecessor's
# blind spots is flattered rather than tested.
_SELF_AUTHORED_RE = re.compile(
    r"^(RSI cycle \d+|\[?spawn-[0-9a-f]+|autorun cycle)\b", re.IGNORECASE
)


@dataclass
class Task:
    """One admitted fail-to-pass task."""

    task_id: str  # the fixing commit's sha
    repo_state: str  # parent sha — the buggy tree
    commit_date: str  # ISO-8601; the whole basis of the contamination claim
    issue_text: str  # commit subject + body, diff stripped
    failing_tests: list[str]  # pytest node ids / files that flip fail->pass
    test_patch: str  # applied to repo_state before the genome sees anything
    gold_patch: str  # reference only — never shown to a genome
    src_files: list[str] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=dict)


@dataclass
class Rejection:
    """A candidate that did not become a task, and precisely why.

    Kept and reported because the rejection rate is the interesting number: a
    generator that silently drops 95% of candidates looks identical to one that
    works, and the reasons are how you tell whether the filter is too strict.
    """

    sha: str
    reason: str


def _git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd or REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def _changed_files(sha: str) -> list[str]:
    out = _git("show", "--name-only", "--format=", sha)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _classify(files: list[str]) -> tuple[list[str], list[str]]:
    """Split changed files into (source, test)."""
    src = [f for f in files if _SRC_RE.match(f) and not _TEST_RE.search(f)]
    tests = [f for f in files if _TEST_RE.search(f)]
    return src, tests


def candidates(since: str | None, until: str | None, limit: int | None) -> list[str]:
    """Commits touching both source and tests, newest first."""
    args = ["log", "--format=%H", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    out: list[str] = []
    for sha in _git(*args).splitlines():
        sha = sha.strip()
        if not sha:
            continue
        src, tests = _classify(_changed_files(sha))
        if src and tests:
            out.append(sha)
        if limit and len(out) >= limit:
            break
    return out


def _diff_for(sha: str, paths: list[str]) -> str:
    if not paths:
        return ""
    return _git("diff", f"{sha}^", sha, "--", *paths)


def _run_pytest(worktree: Path, test_files: list[str], timeout_s: int) -> tuple[bool, str]:
    """Run the named test files in ``worktree``. Returns (passed, tail_of_output).

    The worktree's own ``pyproject.toml`` supplies ``pythonpath`` and the rest of
    the pytest config, so the run reproduces how the suite is actually invoked at
    that commit. Two things this deliberately does NOT do:

    * **No ``--timeout``.** It requires pytest-timeout, which is not a declared
      dependency here; passing it makes pytest exit 4 with "unrecognized
      arguments" *before running anything*, which this generator would then read
      as "the tests fail". That produced a 0% admission rate with every candidate
      rejected as "tests still fail after gold patch" — a wrong verdict on every
      commit, and the reason the wall-clock bound below is enforced by
      ``subprocess.run(timeout=...)`` instead.
    * **No ``PYTHONPATH`` override.** Forcing it to ``packages/*/src`` drops the
      repo root, which the config includes and conftest collection needs.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *test_files,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_s,
        env=_base_env(),
    )
    tail = (proc.stdout + proc.stderr)[-1500:]
    # Exit 4 is a usage error (bad args, collection config), not a test verdict.
    # Treating it as "tests failed" is exactly the bug described above, so it is
    # surfaced as an error rather than silently counted as a fail->pass signal.
    if proc.returncode == 4:
        raise RuntimeError(f"pytest usage error (exit 4), not a test result: {tail[-300:]}")
    return proc.returncode == 0, tail


def _gist(pytest_output: str) -> str:
    """One-line signature of why pytest failed, for the rejection histogram.

    Collapses to the error *class* rather than the message, so that twenty
    commits failing on the same missing dependency aggregate into one row
    instead of twenty near-identical ones.
    """
    for line in pytest_output.splitlines():
        line = line.strip()
        if line.startswith(("ModuleNotFoundError", "ImportError", "collection error")):
            return line.split(":")[0] + ": " + line.split(":")[-1].strip()[:40]
        if line.startswith("E   ") and len(line) > 4:
            return line[4:].split("(")[0].strip()[:60]
    return "assertion/other"


def _base_env() -> dict[str, str]:
    import os

    env = dict(os.environ)
    # Never let a user site-packages or a stale cache change a verdict.
    env["PYTHONNOUSERSITE"] = "1"
    env.pop("PYTHONPATH", None)
    return env


def _apply(worktree: Path, patch: str) -> bool:
    if not patch.strip():
        return True
    proc = subprocess.run(
        ["git", "apply", "--whitespace=nowarn", "-"],
        cwd=worktree,
        input=patch,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


_Prepared = tuple[list[str], list[str], str, str, int]


def _issue_text(sha: str) -> str:
    return _git("log", "-1", "--format=%s%n%n%b", sha).strip()


def _prepare(
    sha: str,
    max_patch_lines: int,
    max_src_files: int,
    min_issue_chars: int = _DEFAULT_MIN_ISSUE_CHARS,
    max_issue_chars: int = _DEFAULT_MAX_ISSUE_CHARS,
    allow_self_authored: bool = False,
) -> tuple[_Prepared | None, Rejection | None]:
    """Cheap checks and patch construction, before any pytest run.

    Split out so a commit that cannot yield a usable task is rejected without
    paying for two test runs — and so ``validate`` stays readable.
    """
    issue = _issue_text(sha)
    subject = issue.splitlines()[0] if issue else ""
    if not allow_self_authored and _SELF_AUTHORED_RE.match(subject):
        return None, Rejection(sha, "authored by the RSI loop (independence)")
    if len(issue) < min_issue_chars:
        return None, Rejection(sha, f"issue text too thin ({len(issue)} < {min_issue_chars} chars)")
    if len(issue) > max_issue_chars:
        return None, Rejection(
            sha, f"issue text is an aggregated changelog ({len(issue)} > {max_issue_chars} chars)"
        )

    files = _changed_files(sha)
    src_files, test_files = _classify(files)
    if not src_files or not test_files:
        return None, Rejection(sha, "no src+test overlap")
    if len(src_files) > max_src_files:
        return None, Rejection(sha, f"too many source files ({len(src_files)} > {max_src_files})")

    # The split is test-files vs EVERYTHING ELSE, not tests vs source-.py.
    # A fix routinely includes non-Python files the tests depend on — vendored
    # corpora, fixtures, config. Restricting the gold patch to `src/**.py`
    # produced an incomplete fix, so every such commit failed its own tests and
    # was rejected as "still failing" when the real cause was a patch this
    # generator had truncated. That bug rejected 100% of candidates.
    non_test = [f for f in files if f not in set(test_files)]
    test_patch = _diff_for(sha, test_files)
    gold_patch = _diff_for(sha, non_test)
    if not gold_patch.strip():
        return None, Rejection(sha, "empty gold patch (test-only commit)")
    gold_lines = len(gold_patch.splitlines())
    if gold_lines > max_patch_lines:
        return None, Rejection(
            sha, f"gold patch too large ({gold_lines} > {max_patch_lines} lines)"
        )
    return (src_files, test_files, test_patch, gold_patch, gold_lines), None


def validate(
    sha: str,
    timeout_s: int,
    max_patch_lines: int = _DEFAULT_MAX_PATCH_LINES,
    max_src_files: int = _DEFAULT_MAX_SRC_FILES,
    min_issue_chars: int = _DEFAULT_MIN_ISSUE_CHARS,
    max_issue_chars: int = _DEFAULT_MAX_ISSUE_CHARS,
    allow_self_authored: bool = False,
) -> tuple[Task | None, Rejection | None]:
    """Admit ``sha`` as a task iff its tests flip fail -> pass. Executes both runs."""
    prepared, rejection = _prepare(
        sha,
        max_patch_lines,
        max_src_files,
        min_issue_chars,
        max_issue_chars,
        allow_self_authored,
    )
    if prepared is None:
        return None, rejection
    src_files, test_files, test_patch, gold_patch, gold_lines = prepared
    parent = _git("rev-parse", f"{sha}^").strip()

    worktree = Path(tempfile.mkdtemp(prefix="repotask-"))
    try:
        _git("worktree", "add", "--detach", str(worktree), parent)
        try:
            if not _apply(worktree, test_patch):
                return None, Rejection(sha, "test patch does not apply to parent")

            # Gate 1: the bug must actually be observable.
            passed_before, _ = _run_pytest(worktree, test_files, timeout_s)
            if passed_before:
                return None, Rejection(sha, "tests already pass at parent (not a fix)")

            # Gate 2: the real fix must actually fix it.
            if not _apply(worktree, gold_patch):
                return None, Rejection(sha, "gold patch does not apply")
            passed_after, out_after = _run_pytest(worktree, test_files, timeout_s)
            if not passed_after:
                # Carry the failure signature. This rejection has two very
                # different causes — a genuinely broken commit, or a missing
                # dependency at that older tree — and only the output tells
                # them apart. Without it the reason histogram is useless.
                return None, Rejection(
                    sha, f"tests still fail after gold patch :: {_gist(out_after)}"
                )

            return (
                Task(
                    task_id=sha,
                    repo_state=parent,
                    commit_date=_git("log", "-1", "--format=%cI", sha).strip(),
                    issue_text=_issue_text(sha),
                    failing_tests=test_files,
                    test_patch=test_patch,
                    gold_patch=gold_patch,
                    src_files=src_files,
                    stats={
                        "gold_patch_lines": gold_lines,
                        "test_files": len(test_files),
                        "src_files": len(src_files),
                    },
                ),
                None,
            )
        finally:
            _git("worktree", "remove", "--force", str(worktree), check=False)
    except subprocess.TimeoutExpired:
        return None, Rejection(sha, f"pytest exceeded {timeout_s}s")
    except Exception as exc:
        return None, Rejection(sha, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(worktree, ignore_errors=True)


def _write_corpus(
    path: Path,
    tasks: list[Task],
    rejections: list[Rejection],
    filters: dict[str, int] | None = None,
) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "schema": "maistro.repo_history_tasks/1",
        "generated_from": _git("rev-parse", "HEAD").strip(),
        # Deliberately NOT a benchmark name that implies comparability. Nothing
        # here can ever be `official_comparable`.
        "benchmark": "repo_history",
        # How this corpus was filtered. Recorded so a consumer can see the
        # selection criteria rather than infer them from what survived.
        "filters": filters or {},
        "tasks": [asdict(t) for t in sorted(tasks, key=lambda t: t.commit_date)],
        "rejections": [asdict(r) for r in rejections],
        "counts": {
            "admitted": len(tasks),
            "rejected": len(rejections),
            "candidates": len(tasks) + len(rejections),
        },
    }
    serialized = json.dumps(body, indent=2, sort_keys=True) + "\n"
    path.write_text(serialized, encoding="utf-8")
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only commits after this date (git --since)")
    ap.add_argument("--until", help="only commits before this date (git --until)")
    ap.add_argument("--limit", type=int, help="stop after N candidates")
    ap.add_argument("--timeout", type=int, default=_DEFAULT_TIMEOUT_S)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--resume", action="store_true", help="keep tasks already in --output")
    ap.add_argument(
        "--max-patch-lines",
        type=int,
        default=_DEFAULT_MAX_PATCH_LINES,
        help="reject fixes larger than this (default %(default)s)",
    )
    ap.add_argument(
        "--min-issue-chars",
        type=int,
        default=_DEFAULT_MIN_ISSUE_CHARS,
        help="reject commits whose problem statement is shorter (default %(default)s)",
    )
    ap.add_argument(
        "--max-issue-chars",
        type=int,
        default=_DEFAULT_MAX_ISSUE_CHARS,
        help="reject aggregated-changelog commits above this size (default %(default)s)",
    )
    ap.add_argument(
        "--allow-self-authored",
        action="store_true",
        help="include commits the RSI loop authored (excluded by default: independence)",
    )
    ap.add_argument(
        "--max-src-files",
        type=int,
        default=_DEFAULT_MAX_SRC_FILES,
        help="reject fixes touching more source files than this (default %(default)s)",
    )
    args = ap.parse_args()

    tasks: list[Task] = []
    seen: set[str] = set()
    if args.resume and args.output.is_file():
        prior = json.loads(args.output.read_text(encoding="utf-8"))
        tasks = [Task(**t) for t in prior.get("tasks", [])]
        seen = {t.task_id for t in tasks}
        print(f"resuming with {len(tasks)} existing task(s)")

    shas = [s for s in candidates(args.since, args.until, args.limit) if s not in seen]
    print(f"{len(shas)} candidate commit(s) touching both source and tests\n")

    rejections: list[Rejection] = []
    for i, sha in enumerate(shas, 1):
        task, rejection = validate(sha, args.timeout, args.max_patch_lines, args.max_src_files)
        if task is not None:
            tasks.append(task)
            print(f"  [{i}/{len(shas)}] {sha[:8]} ADMITTED  {task.issue_text.splitlines()[0][:60]}")
        else:
            assert rejection is not None
            rejections.append(rejection)
            print(f"  [{i}/{len(shas)}] {sha[:8]} rejected  {rejection.reason}")

    digest = _write_corpus(
        args.output,
        tasks,
        rejections,
        {
            "max_patch_lines": args.max_patch_lines,
            "max_src_files": args.max_src_files,
            "min_issue_chars": args.min_issue_chars,
            "max_issue_chars": args.max_issue_chars,
            "allow_self_authored": int(args.allow_self_authored),
        },
    )
    shown = args.output
    with contextlib.suppress(ValueError):  # output may legitimately live outside the repo
        shown = args.output.relative_to(REPO)
    print(f"\nadmitted {len(tasks)} / {len(shas) + len(seen)} candidates")
    print(f"wrote {shown}")
    print(f"sha256 {digest}")
    print("\nPin this digest in benchmarks/repo_history.py before scoring against it.")

    # Rejection reasons, most common first — the filter's own report card.
    if rejections:
        counts: dict[str, int] = {}
        for r in rejections:
            counts[r.reason] = counts.get(r.reason, 0) + 1
        print("\nrejection reasons:")
        for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
