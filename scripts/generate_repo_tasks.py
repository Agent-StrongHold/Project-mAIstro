#!/usr/bin/env python3
"""Generate repo-history tasks from the retained development history.

The implementation lives in ``generate_repo_tasks_impl``. This CLI wrapper owns
history selection and argument plumbing so tree-only promotion commits on
``integration``/``main`` cannot hide the individual development commits the
benchmark is intended to mine.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

import generate_repo_tasks_impl as _impl
from generate_repo_tasks_impl import Rejection, Task, validate  # re-export public API

# Preserve the module-level admission-filter surface used by the benchmark tests.
# These helpers intentionally remain implemented in generate_repo_tasks_impl;
# the CLI wrapper only re-exports them so importing this historical script path
# behaves the same way it did before the implementation was split out.
_SELF_AUTHORED_RE = _impl._SELF_AUTHORED_RE
_DEFAULT_MIN_ISSUE_CHARS = _impl._DEFAULT_MIN_ISSUE_CHARS
_DEFAULT_MAX_ISSUE_CHARS = _impl._DEFAULT_MAX_ISSUE_CHARS
_DEFAULT_MAX_PATCH_LINES = _impl._DEFAULT_MAX_PATCH_LINES
_DEFAULT_MAX_SRC_FILES = _impl._DEFAULT_MAX_SRC_FILES
_classify = _impl._classify


def _development_history_ref() -> str:
    """Return an explicit retained develop ref instead of implicitly using HEAD."""
    for ref in ("refs/remotes/origin/develop", "develop"):
        if _impl._git("rev-parse", "--verify", "--quiet", ref, check=False).strip():
            return ref
    raise RuntimeError(
        "develop history is unavailable; fetch it first (for example: git fetch origin develop)"
    )


def candidates(since: str | None, until: str | None, limit: int | None) -> list[str]:
    """Commits touching both source and tests from retained develop history."""
    args = ["log", "--format=%H", "--no-merges"]
    if since:
        args.append(f"--since={since}")
    if until:
        args.append(f"--until={until}")
    args.append(_development_history_ref())

    out: list[str] = []
    for sha in _impl._git(*args).splitlines():
        sha = sha.strip()
        if not sha:
            continue
        src, tests = _impl._classify(_impl._changed_files(sha))
        if src and tests:
            out.append(sha)
        if limit and len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", help="only commits after this date (git --since)")
    ap.add_argument("--until", help="only commits before this date (git --until)")
    ap.add_argument("--limit", type=int, help="stop after N candidates")
    ap.add_argument("--timeout", type=int, default=_impl._DEFAULT_TIMEOUT_S)
    ap.add_argument("--output", type=Path, default=_impl.DEFAULT_OUTPUT)
    ap.add_argument("--resume", action="store_true", help="keep tasks already in --output")
    ap.add_argument(
        "--max-patch-lines",
        type=int,
        default=_impl._DEFAULT_MAX_PATCH_LINES,
        help="reject fixes larger than this (default %(default)s)",
    )
    ap.add_argument(
        "--min-issue-chars",
        type=int,
        default=_impl._DEFAULT_MIN_ISSUE_CHARS,
        help="reject commits whose problem statement is shorter (default %(default)s)",
    )
    ap.add_argument(
        "--max-issue-chars",
        type=int,
        default=_impl._DEFAULT_MAX_ISSUE_CHARS,
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
        default=_impl._DEFAULT_MAX_SRC_FILES,
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
        task, rejection = validate(
            sha,
            args.timeout,
            args.max_patch_lines,
            args.max_src_files,
            args.min_issue_chars,
            args.max_issue_chars,
            args.allow_self_authored,
        )
        if task is not None:
            tasks.append(task)
            print(f"  [{i}/{len(shas)}] {sha[:8]} ADMITTED  {task.issue_text.splitlines()[0][:60]}")
        else:
            assert rejection is not None
            rejections.append(rejection)
            print(f"  [{i}/{len(shas)}] {sha[:8]} rejected  {rejection.reason}")

    digest = _impl._write_corpus(
        args.output,
        tasks,
        rejections,
        {
            "history_ref": _development_history_ref(),
            "max_patch_lines": args.max_patch_lines,
            "max_src_files": args.max_src_files,
            "min_issue_chars": args.min_issue_chars,
            "max_issue_chars": args.max_issue_chars,
            "allow_self_authored": int(args.allow_self_authored),
        },
    )
    shown = args.output
    with contextlib.suppress(ValueError):
        shown = args.output.relative_to(_impl.REPO)
    print(f"\nadmitted {len(tasks)} / {len(shas) + len(seen)} candidates")
    print(f"wrote {shown}")
    print(f"sha256 {digest}")
    print("\nPin this digest in benchmarks/repo_history.py before scoring against it.")

    if rejections:
        counts: dict[str, int] = {}
        for rejection in rejections:
            counts[rejection.reason] = counts.get(rejection.reason, 0) + 1
        print("\nrejection reasons:")
        for reason, n in sorted(counts.items(), key=lambda item: -item[1]):
            print(f"  {n:>3}  {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
