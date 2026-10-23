#!/usr/bin/env python3
"""Scope a cosmic-ray session to the lines a pull request actually changed (#330).

Mutating every mutant of a touched file makes the PR gate pay for the whole
file when the PR touched two lines, which is why #330 scopes mutation to
changed lines. Cosmic-ray has no native diff scope: `init` enumerates every
operator application in the module. Like the annotation filter (#419), this
runs between `init` and `exec` and marks out-of-scope mutants SKIPPED before
they cost a test run — but unlike a heuristic this is a measured scope: the
changed-line set parsed from the PR's own diff against the trusted merge base.

Direction of failure
--------------------
A bug here may over-scope (mutate a neighbouring line) or under-scope (skip a
changed line's mutants). Over-scoping wastes runner minutes. Under-scoping
silently weakens the gate, so:

  - only mutants wholly outside the changed set are skipped; a mutant whose
    span merely touches a changed line stays in;
  - with `--require-intersection`, a session in which NO mutant intersects the
    changed set exits non-zero. Zero mutants on a changed critical file is a
    configuration error (stale diff, wrong file, operator gap) and must not
    look like a clean pass — the same rule `mutation_viability.py gate` mode
    applies to a whole session.

Usage
-----
    python scripts/mutation_diff_scope.py SESSION.sqlite --source PATH \
        --diff PR.diff [--require-intersection] [--report]

The diff must be a unified diff for exactly one file (the workflow produces
`git diff <merge-base> -- <source>`); the changed-line numbers are the *new*
side, which is where cosmic-ray's positions live.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

from cosmic_ray.work_db import WorkDB, use_db
from cosmic_ray.work_item import WorkerOutcome, WorkResult

SKIP_REASON = "Filtered: outside the pull request's changed lines (#330)"

# Open, never create: `use_db` defaults to Mode.create, which reinitialises
# the session and would silently destroy every mutant cosmic-ray enumerated.
_OPEN = WorkDB.Mode.open


@dataclass
class DiffScope:
    """Changed new-side line numbers parsed from a single-file unified diff."""

    lines: set[int] = field(default_factory=set)

    @classmethod
    def from_unified_diff(cls, diff: str) -> DiffScope:
        scope = cls()
        new_line: int | None = None
        for raw in diff.splitlines():
            if raw.startswith("@@"):
                # "@@ -330,7 +331,8 @@ ..." -> new side starts at 331
                try:
                    new_part = raw.split("+", 1)[1].split(" ", 1)[0]
                    new_start = int(new_part.split(",", 1)[0])
                except (IndexError, ValueError) as exc:
                    raise ValueError(f"unparseable hunk header: {raw!r}") from exc
                new_line = new_start
                continue
            if new_line is None:
                continue  # file headers and ---/+++ lines before the first hunk
            if raw.startswith("+"):
                scope.lines.add(new_line)
                new_line += 1
            elif raw.startswith("-") or raw.startswith("\\"):
                continue  # deleted lines have no new-side position
            else:
                new_line += 1  # context line, present on the new side
        return scope

    def intersects(self, start_row: int, end_row: int) -> bool:
        """Whether any line of the mutant's inclusive row span changed."""
        return any(line in self.lines for line in range(start_row, end_row + 1))


def apply_diff_scope(
    work_db,
    source: str,
    scope: DiffScope,
) -> tuple[int, int]:
    """Skip every pending mutant of `source` wholly outside the changed lines.

    `work_db` is a cosmic-ray session (or anything with `pending_work_items`
    and `set_result`). Returns (kept, skipped) counts for pending items.
    Items that already have a result — e.g. annotation-position mutants the
    #419 filter skipped before this ran — are left untouched.
    """
    kept = 0
    skipped = 0
    want = Path(source).as_posix()
    for item in work_db.pending_work_items:
        # `module_path` round-trips from the session as a Path object; compare
        # normalized posix strings, not identities.
        if any(Path(str(m.module_path)).as_posix() != want for m in item.mutations):
            # A multi-module item is out of this script's single-file contract;
            # refusing to guess keeps another module's scope decision local.
            raise ValueError(
                f"work item {item.job_id} spans several modules; "
                "run the diff scope per single-module session"
            )
        if any(scope.intersects(m.start_pos[0], m.end_pos[0]) for m in item.mutations):
            kept += 1
            continue
        work_db.set_result(
            item.job_id,
            WorkResult(worker_outcome=WorkerOutcome.SKIPPED, output=SKIP_REASON),
        )
        skipped += 1
    return kept, skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path, help="cosmic-ray session sqlite")
    parser.add_argument("--source", required=True, help="module path as recorded in the session")
    parser.add_argument(
        "--diff", required=True, help="unified diff of the source vs the trusted merge base"
    )
    parser.add_argument(
        "--require-intersection",
        action="store_true",
        help="fail when no pending mutant intersects the changed lines",
    )
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args(argv)

    diff = Path(args.diff).read_text(encoding="utf-8")
    scope = DiffScope.from_unified_diff(diff)
    if not scope.lines:
        print(
            "::error::changed-line set is empty — the diff contains no additions. "
            "A mutation run against nothing is a configuration error, not a pass.",
            file=sys.stderr,
        )
        return 1

    with use_db(args.session, mode=_OPEN) as db:
        kept, skipped = apply_diff_scope(db, args.source, scope)

    if args.report:
        print(
            f"diff scope for {args.source}: {len(scope.lines)} changed line(s), "
            f"{kept} mutant(s) in scope, {skipped} skipped"
        )

    if args.require_intersection and kept == 0:
        print(
            f"::error::{args.source}: no pending mutant intersects the changed lines "
            f"({len(scope.lines)} changed). Zero mutants is a configuration error, not a pass.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
