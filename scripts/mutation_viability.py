"""Classify surviving cosmic-ray mutants by whether a test could kill them.

The mutation gate scores `killed / total`. That is only a meaningful ratio if
every mutant in the denominator is *killable*. Some are not: a mutation applied
inside a type annotation cannot change runtime behaviour in a module that
carries `from __future__ import annotations`, because annotations are never
evaluated there. cosmic-ray cannot mark those `INCOMPETENT` -- that status is
for mutants which fail to compile, and these compile fine -- so they land in the
survivor list and drag the ratio down permanently.

`graph/durable_runs/executor.py` is the worked example: 139 survivors, of which
66 are annotation-only. Killing every genuinely killable mutant in that file
still leaves the gate short of 90%. The ceiling is a property of the
denominator, not of the test suite.

This module answers three questions, in order:

  locate   -- which surviving mutants are candidates? (query the session,
              scoped to one module)
  confirm  -- is a candidate *provably* non-viable? (compare stripped ASTs,
              only where the future import makes that sound)
  mark     -- emit a report the gate can subtract, naming every exclusion
              individually so nothing is dropped silently.

The confirmation step is a proof rather than a heuristic. For each survivor we
reconstruct the mutated source, strip every annotation from both the pristine
and the mutated AST, and compare. If the two are identical, the mutation lives
entirely in annotation space.

THE FUTURE IMPORT IS LOAD-BEARING. Without `from __future__ import annotations`
an annotation is an ordinary expression evaluated at class/def execution time,
so `str | None` -> `str + None` raises TypeError on import and any test that
imports the module kills it. Stripping annotations from both trees would then
"prove" a killable mutant unobservable and quietly delete it from the
denominator. This module therefore refuses to exclude anything from a source
that lacks the import, and says so in its output.

Residual assumption, stated rather than hidden: even under PEP 563 the mutated
annotation text remains reachable through `__annotations__`,
`inspect.signature`, and `typing.get_type_hints`, so a test that asserts on
annotation *text* -- or a consumer that resolves hints at runtime, such as a
dataclass or a validation framework -- could in principle observe the
difference. Excluding on that basis is a deliberate, narrow judgement: honouring
it would mean never excluding anything, which returns the gate to an
unreachable ceiling. The assumption is printed with every report so a reviewer
weighs it rather than inherits it.

Deliberately *not* excluded:

  - anything whose stripped AST differs, however marginally. `*,` -> `/,` moves
    arguments between `posonlyargs` and `args`, so it stays in.
  - mutants that fail to compile (`invalid`). A non-compiling mutant is
    killable by any test that imports the module; that it survived means the
    scoped tests never import it, which is a coverage gap, not a proof of
    harmlessness. These stay in the denominator.
  - mutants whose diff could not be reconstructed (`undetermined`). A parsing
    failure in this script must never loosen the gate.

Only `non_viable` is ever subtracted.

Usage:
    python scripts/mutation_viability.py SESSION.sqlite MODULE_PATH \\
        [--source PRISTINE.py] [--json report.json]

MODULE_PATH is the path as recorded in the session (cosmic-ray stores it
repo-relative), and doubles as where the pristine source is read from. Pass
`--source` when the pristine text lives elsewhere, e.g. a copy taken with
`git show HEAD:<path>` because cosmic-ray rewrites the working tree in place
during `exec`.
"""

from __future__ import annotations

import argparse
import ast
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_FUTURE_ANNOTATIONS = "annotations"


class _StripAnnotations(ast.NodeTransformer):
    """Remove every annotation, leaving the executable structure intact.

    Annotations are the only construct we are willing to call unobservable, so
    they are the only thing removed. Everything else -- defaults, decorators,
    the argument vector's shape, posonly/kwonly placement -- is preserved
    precisely so that a mutation touching any of it shows up as a difference.
    """

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        node.returns = None
        return self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        node.returns = None
        return self.generic_visit(node)

    def visit_arg(self, node: ast.arg) -> ast.AST:
        node.annotation = None
        return self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST:
        # `x: T = v` -> `x = v`; a bare `x: T` declares nothing at runtime.
        self.generic_visit(node)
        if node.value is None:
            return ast.Pass()
        return ast.Assign(targets=[node.target], value=node.value, type_comment=None)


def has_future_annotations(source: str) -> bool:
    """Does this module defer annotation evaluation (PEP 563)?

    Without it, annotations are live expressions and no annotation mutant can
    be called unobservable.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == "__future__"
        and any(alias.name == _FUTURE_ANNOTATIONS for alias in node.names)
        for node in tree.body
    )


def _normalized(source: str) -> str | None:
    """AST dump with annotations stripped, or None if the source won't parse."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    stripped = ast.fix_missing_locations(_StripAnnotations().visit(tree))
    # include_attributes=False: line/column shifts are not behavioural.
    return ast.dump(stripped, include_attributes=False)


def _parse_hunk(diff: str) -> tuple[int, list[str], list[str]] | None:
    """Split a unified diff into (start_line, removed, added).

    Returns None for any shape this module will not reconstruct: no hunk
    header, an unparseable one, or anything other than exactly one removed
    line with at most one added line.
    """
    start: int | None = None
    removed: list[str] = []
    added: list[str] = []
    for raw in diff.splitlines():
        if raw.startswith("@@"):
            # "@@ -330,7 +330,7 @@" -> 330 (1-based)
            try:
                start = int(raw.split("-", 1)[1].split(",", 1)[0].split()[0])
            except (IndexError, ValueError):
                return None
            removed, added = [], []
        elif raw.startswith(("---", "+++")):
            continue
        elif raw.startswith("-"):
            removed.append(raw[1:])
        elif raw.startswith("+"):
            added.append(raw[1:])
    if start is None or len(removed) != 1 or len(added) > 1:
        return None
    return start, removed, added


def _apply_diff(pristine: str, diff: str) -> str | None:
    """Rebuild the mutated source from a cosmic-ray single-hunk diff.

    Handles both replacement hunks (one removed line, one added) and
    deletion-only hunks (one removed, none added) -- `core/RemoveDecorator` and
    friends emit the latter, and rejecting them would silently park every such
    mutant in `undetermined` where it would never be reported as the coverage
    gap it is.

    Anything with a different shape returns None and is classified
    `undetermined`, which keeps it in the denominator.
    """
    parsed = _parse_hunk(diff)
    if parsed is None:
        return None
    start, removed, added = parsed

    lines = pristine.splitlines(keepends=True)
    target = removed[0]
    # Scan the hunk window for the removed line; hunk headers are 1-based and
    # include leading context, so the changed line is at or after `start`.
    for idx in range(max(0, start - 1), min(len(lines), start + 12)):
        if lines[idx].rstrip("\n") == target.rstrip("\n"):
            out = list(lines)
            if added:
                newline = "\n" if lines[idx].endswith("\n") else ""
                out[idx] = added[0].rstrip("\n") + newline
            else:
                del out[idx]
            return "".join(out)
    return None


@dataclass
class Verdict:
    """One survivor's classification."""

    job_id: str
    row: int
    col: int
    operator: str
    category: str  # "non_viable" | "viable" | "invalid" | "undetermined"
    source_line: str
    mutated_line: str = ""

    @property
    def ident(self) -> str:
        """Stable identifier for a single excluded mutant."""
        return f"{self.job_id[:8]} L{self.row}:{self.col} {self.operator}"


@dataclass
class Report:
    module: str = ""
    total: int = 0
    killed: int = 0
    pending: int = 0
    future_annotations: bool = False
    verdicts: list[Verdict] = field(default_factory=list)

    def _of(self, category: str) -> list[Verdict]:
        return [v for v in self.verdicts if v.category == category]

    @property
    def non_viable(self) -> list[Verdict]:
        return self._of("non_viable")

    @property
    def viable(self) -> list[Verdict]:
        return self._of("viable")

    @property
    def invalid(self) -> list[Verdict]:
        return self._of("invalid")

    @property
    def undetermined(self) -> list[Verdict]:
        return self._of("undetermined")

    def adjusted(self) -> tuple[int, int, float]:
        """(killed, adjusted_total, rate) with only non-viable mutants removed.

        `invalid` and `undetermined` stay in the denominator. A mutant that
        does not compile is killable by any test that imports the module, and a
        mutant this script failed to reconstruct has been proven nothing at
        all. Subtracting either would let a parse failure loosen the gate.
        """
        denominator = self.total - len(self.non_viable)
        rate = self.killed / denominator if denominator else 0.0
        return self.killed, denominator, rate


def classify(session_path: Path, module_key: str, source_path: Path) -> Report:
    """Locate survivors for one module, then confirm each one's viability."""
    pristine = source_path.read_text()
    baseline = _normalized(pristine)
    if baseline is None:
        raise SystemExit(f"pristine source does not parse: {source_path}")

    report = Report(module=module_key, future_annotations=has_future_annotations(pristine))

    conn = sqlite3.connect(session_path)
    # Every count is scoped to one module. A session may cover many -- the
    # nightly config mutates the whole `maistro` package -- and mixing them
    # would apply one file's diffs to another's source and report a rate that
    # describes neither.
    initialized = conn.execute(
        "SELECT count(*) FROM mutation_specs WHERE module_path = ?", (module_key,)
    ).fetchone()[0]
    if initialized == 0:
        conn.close()
        raise SystemExit(
            f"no mutants recorded for module_path={module_key!r}. "
            "Pass the path exactly as cosmic-ray recorded it (repo-relative)."
        )

    rows = conn.execute(
        """SELECT s.job_id, s.start_pos_row, s.start_pos_col, s.operator_name,
                  r.test_outcome, r.diff
             FROM mutation_specs s JOIN work_results r ON s.job_id = r.job_id
            WHERE s.module_path = ?
            ORDER BY s.start_pos_row, s.start_pos_col""",
        (module_key,),
    ).fetchall()
    conn.close()

    report.total = len(rows)
    report.killed = sum(1 for r in rows if r[4] == "KILLED")
    # An interrupted sweep leaves specs without results. Counting only what
    # finished would quietly shrink the denominator and inflate the rate.
    report.pending = initialized - len(rows)

    src_lines = pristine.splitlines()
    for job_id, row, col, operator, outcome, diff in rows:
        if outcome == "KILLED":
            continue
        line_text = src_lines[row - 1].strip() if 0 < row <= len(src_lines) else ""
        mutated = _apply_diff(pristine, diff or "")
        if mutated is None:
            report.verdicts.append(Verdict(job_id, row, col, operator, "undetermined", line_text))
            continue
        candidate = _normalized(mutated)
        if candidate is None:
            report.verdicts.append(Verdict(job_id, row, col, operator, "invalid", line_text))
            continue
        # Only a deferred-annotation module may have anything excluded.
        equivalent = candidate == baseline and report.future_annotations
        category = "non_viable" if equivalent else "viable"
        mutated_lines = mutated.splitlines()
        mutated_line = mutated_lines[row - 1].strip() if row <= len(mutated_lines) else "<deleted>"
        report.verdicts.append(
            Verdict(job_id, row, col, operator, category, line_text, mutated_line)
        )

    return report


def _emit(report: Report, json_out: Path | None) -> int:
    killed, denominator, rate = report.adjusted()
    raw_rate = report.killed / report.total if report.total else 0.0

    print(f"module: {report.module}")
    if report.pending:
        print(f"  INCOMPLETE: {report.pending} initialized mutants have no result.")
        print("  Refusing to score a partial session -- rerun `cosmic-ray exec` to completion.")
        return 1
    print(f"  deferred annotations (PEP 563) : {report.future_annotations}")
    if not report.future_annotations:
        print("  -> annotations are live expressions here, so NOTHING is excluded.")
    print(f"  raw       : {report.killed}/{report.total} = {raw_rate:.1%}")
    print(f"  survivors : {report.total - report.killed}")
    print(f"    non-viable (annotation-only, provably unkillable) : {len(report.non_viable)}")
    print(f"    invalid    (does not compile; kept in denominator): {len(report.invalid)}")
    print(f"    undetermined (kept in denominator)                : {len(report.undetermined)}")
    print(f"    viable     (real coverage gaps)                   : {len(report.viable)}")
    print(f"  adjusted  : {killed}/{denominator} = {rate:.1%}")
    print("  (only non-viable is subtracted; invalid and undetermined are not)")
    print()

    if report.non_viable:
        print("excluded as non-viable -- each one named individually:")
        for v in report.non_viable:
            print(f"  {v.ident}")
            print(f"          - {v.source_line[:76]}")
            print(f"          + {v.mutated_line[:76]}")
        print()
        print(
            "  assumption: under PEP 563 the mutated annotation text is still "
            "reachable via\n  __annotations__ / inspect.signature / "
            "typing.get_type_hints. Excluding these\n  assumes no test and no "
            "runtime consumer resolves hints for this module."
        )
        print()

    if report.viable:
        print("viable survivors -- real coverage gaps, write tests for them:")
        for v in report.viable:
            print(f"  {v.ident}")
            print(f"          - {v.source_line[:76]}")
            print(f"          + {v.mutated_line[:76]}")

    if json_out:
        payload: dict[str, Any] = {
            "module": report.module,
            "future_annotations": report.future_annotations,
            "pending": report.pending,
            "raw": {"killed": report.killed, "total": report.total},
            "adjusted": {"killed": killed, "total": denominator, "rate": rate},
            **{
                name: [
                    {
                        "job_id": v.job_id,
                        "line": v.row,
                        "col": v.col,
                        "operator": v.operator,
                        "source": v.source_line,
                        "mutated": v.mutated_line,
                    }
                    for v in getattr(report, name)
                ]
                for name in ("non_viable", "viable", "invalid", "undetermined")
            },
        }
        json_out.write_text(json.dumps(payload, indent=2))
        print(f"\nwrote {json_out}")
    return 0


def _group_by_line(verdicts: list[Verdict]) -> list[tuple[int, str, str, list[str]]]:
    """Collapse verdicts to (line, source, mutated, [operators]).

    A survivor list is read by a person deciding what test to write next, and
    thirteen consecutive entries for one line answer that question no better
    than one entry saying "this line, thirteen ways".
    """
    grouped: dict[int, tuple[str, str, list[str]]] = {}
    for v in sorted(verdicts, key=lambda x: (x.row, x.col)):
        src, mutated, ops = grouped.get(v.row, (v.source_line, v.mutated_line, []))
        ops.append(v.operator.removeprefix("core/"))
        grouped[v.row] = (src, mutated, ops)
    return [(row, s, m, ops) for row, (s, m, ops) in sorted(grouped.items())]


def _print_survivors(verdicts: list[Verdict], module: str) -> None:
    """Actionable failure output: where, what changed, and how many ways."""
    for row, source, mutated, ops in _group_by_line(verdicts):
        plural = "mutant" if len(ops) == 1 else "mutants"
        print(f"  {module}:{row}  ({len(ops)} surviving {plural})")
        print(f"      - {source[:96]}")
        print(f"      + {mutated[:96]}")
        print(f"      via: {', '.join(sorted(set(ops)))[:150]}")
        print()


def gate(pairs: list[tuple[Path, str]], threshold: float, json_out: Path | None) -> int:
    """Score every mutated module together and decide the build.

    Replaces the inline aggregation the workflow used to carry. Three
    properties from that version are preserved deliberately:

      - no mutants at all is a configuration error, not a pass
      - only `non_viable` leaves the denominator
      - every exclusion is named, mirroring this workflow's existing promise
        that a skipped file is "named explicitly in the log"

    and one is added: a session with unfinished work refuses to score rather
    than quietly reporting the rate of the jobs that happened to complete.
    """
    reports = [classify(session, module, Path(module)) for session, module in pairs]

    incomplete = [r for r in reports if r.pending]
    for r in incomplete:
        print(f"::error::{r.module}: {r.pending} initialized mutants have no result.")
    if incomplete:
        print("::error::Refusing to score a partial sweep. Rerun `cosmic-ray exec`.")
        return 1

    total = sum(r.total for r in reports)
    if total == 0:
        print("::error::No mutants produced — config error, not a pass.")
        return 1

    killed = sum(r.killed for r in reports)
    excluded = sum(len(r.non_viable) for r in reports)
    denominator = total - excluded
    if denominator == 0:
        print("::error::Every mutant was classified non-viable — that is not a pass.")
        return 1
    rate = killed / denominator
    raw_rate = killed / total

    print(f"Mutation kill rate: {killed}/{denominator} = {rate:.1%} (gate: {threshold:.0%})")
    print(f"  raw, before exclusions: {killed}/{total} = {raw_rate:.1%}")
    print(f"  excluded as non-viable: {excluded}")
    print()
    for r in reports:
        r_killed, r_denom, r_rate = r.adjusted()
        print(f"  {r.module}: {r_killed}/{r_denom} = {r_rate:.1%}")
    print()

    if excluded:
        _print_exclusions(reports)
    if json_out:
        _write_gate_json(json_out, reports, threshold, killed, denominator, total, rate)

    if rate < threshold:
        print(f"::error::Mutation kill rate {rate:.1%} is below the {threshold:.0%} gate.")
        _print_failure_detail(reports)
        return 1

    print(f"Mutation gate passed (>={threshold:.0%})")
    return 0


def _print_exclusions(reports: list[Report]) -> None:
    """Name every subtracted mutant.

    Aggregating by operator would be shorter and would also make the claim
    false: a reviewer cannot audit an exclusion they cannot locate.
    """
    print("::group::Excluded as non-viable (provably unkillable), named individually")
    for r in reports:
        for v in r.non_viable:
            print(f"  {r.module}:{v.row}:{v.col} {v.operator} [{v.job_id[:8]}]")
            print(f"      - {v.source_line[:96]}")
            print(f"      + {v.mutated_line[:96]}")
    print(
        "\n  These mutate type annotations in modules carrying "
        "`from __future__ import annotations`,\n  where annotations are "
        "never evaluated. Assumption: nothing resolves hints at runtime\n"
        "  for these modules (__annotations__ / inspect.signature / "
        "typing.get_type_hints)."
    )
    print("::endgroup::")


def _print_failure_detail(reports: list[Report]) -> None:
    """Say where to look and what to write, not what the result rows contain."""
    print()
    print("Surviving mutants a test could kill — each is a behaviour nothing asserts:")
    print()
    for r in reports:
        _print_survivors(r.viable, r.module)
    for r in reports:
        if r.invalid:
            print(f"  {r.module}: {len(r.invalid)} mutants do not compile and still survived.")
            print("      The scoped tests never import this module — that is the gap.")
        if r.undetermined:
            print(f"  {r.module}: {len(r.undetermined)} mutants could not be reconstructed;")
            print("      they stay in the denominator rather than be assumed harmless.")
    print(
        "Tip: pick the line with the most survivors first. When the mutants are "
        "arithmetic,\nassert an exact value from a base that separates them — "
        "from 0, `x+1`, `x|1` and\n`x^1` all agree, so an assertion of 1 passes "
        "against most of the mutants too."
    )


def _write_gate_json(
    json_out: Path,
    reports: list[Report],
    threshold: float,
    killed: int,
    denominator: int,
    total: int,
    rate: float,
) -> None:
    json_out.write_text(
        json.dumps(
            {
                "threshold": threshold,
                "killed": killed,
                "adjusted_total": denominator,
                "raw_total": total,
                "rate": rate,
                "modules": [
                    {
                        "module": r.module,
                        "killed": r.killed,
                        "total": r.total,
                        "non_viable": len(r.non_viable),
                        "viable": len(r.viable),
                    }
                    for r in reports
                ],
            },
            indent=2,
        )
    )


def _read_pairs(path: Path) -> list[tuple[Path, str]]:
    """Read the workflow's `session<TAB>module` manifest."""
    pairs: list[tuple[Path, str]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        session, _, module = line.partition("\t")
        if not module:
            raise SystemExit(f"malformed manifest line (expected session<TAB>module): {line!r}")
        pairs.append((Path(session), module))
    if not pairs:
        raise SystemExit(f"no sessions listed in {path}")
    return pairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify surviving cosmic-ray mutants.")
    parser.add_argument("session", type=Path, nargs="?", help="cosmic-ray session sqlite")
    parser.add_argument("module", nargs="?", help="module_path as recorded in the session")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="read pristine text here instead of from MODULE (e.g. a git-show copy)",
    )
    parser.add_argument(
        "--sessions",
        type=Path,
        default=None,
        help="gate mode: a TSV manifest of `session<TAB>module` lines to score together",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="gate mode: minimum adjusted kill rate (default 0.90)",
    )
    parser.add_argument("--json", type=Path, default=None, help="write a JSON report here")
    args = parser.parse_args(argv)

    if args.sessions:
        if args.session or args.module:
            parser.error("--sessions is gate mode; do not also pass SESSION/MODULE")
        return gate(_read_pairs(args.sessions), args.threshold, args.json)

    if not (args.session and args.module):
        parser.error("pass SESSION and MODULE for a single-module report, or --sessions to gate")
    report = classify(args.session, args.module, args.source or Path(args.module))
    return _emit(report, args.json)


if __name__ == "__main__":
    sys.exit(main())
