#!/usr/bin/env python3
"""Skip mutants that land inside a type annotation (#419).

Why
---
Under ``from __future__ import annotations`` every annotation is a *string*.
Python never evaluates it, so a mutation inside one changes nothing a test
could observe. Cosmic-ray does not know that, and mutates them anyway:

    -def _module_file(root: Path, parts: list[str]) -> Path | None:
    +def _module_file(root: Path, parts: list[str]) -> Path + None:

One `X | None` yields six of these — Add, Mul, Mod, RShift, LShift, BitAnd —
and all six survive by construction. They cost a full test-command run each and
then land in the survivor list for a human to triage as "equivalent", every
time, forever.

Measured on this repository: 1,861 union nodes sit in annotation position
across the 682 files under ``packages/*/src`` that carry the future import.
At six operators apiece that is ~11,166 unkillable mutants, and at the
5.9s/mutant this repository actually achieves, ~18 hours of runner time
producing no signal at all. It was 6 of the 17 survivors on the first gate
measured.

What it does NOT skip
---------------------
A runtime union. ``isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)``
is evaluated, its mutants are killable, and a test kills them. That is why this
filter is positional rather than a regex over operator names: the two are the
same operator in the same file, told apart only by where they sit.

Nor does it skip anything in a file without the future import, where an
annotation *is* evaluated at definition time.

Usage
-----
    python3 scripts/mutation_filter_annotations.py <session.sqlite> [--report]

Runs between ``cosmic-ray init`` and ``cosmic-ray exec``, like the filters
cosmic-ray ships (``cr-filter-operators``, ``cr-filter-pragma``).
"""

from __future__ import annotations

import ast
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path

from cosmic_ray.tools.filters.filter_app import FilterApp
from cosmic_ray.work_item import WorkerOutcome, WorkResult

FUTURE_ANNOTATIONS = "from __future__ import annotations"


def annotation_spans(source: str) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    """Every ``(start, end)`` position that is inside an annotation.

    Empty when the module does not carry the future import: there an
    annotation is evaluated at definition time, so mutating it is fair game.

    Positions are ``(line, col)`` to match cosmic-ray's ``MutationSpec``.
    """
    if FUTURE_ANNOTATIONS not in source:
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for node in ast.walk(tree):
        for annotation in _annotations_of(node):
            if annotation is None or annotation.end_lineno is None:
                continue
            spans.append(
                (
                    (annotation.lineno, annotation.col_offset),
                    (annotation.end_lineno, annotation.end_col_offset or 0),
                )
            )
    return spans


def _annotations_of(node: ast.AST) -> list[ast.expr | None]:
    """The annotation expressions one node introduces.

    Every argument kind is listed rather than just `args`: `*args`, `**kwargs`,
    keyword-only and positional-only parameters are all annotated in this
    codebase, and one missed kind is a silent hole in the filter.
    """
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        spec = node.args
        arguments = [
            *spec.posonlyargs,
            *spec.args,
            *spec.kwonlyargs,
            spec.vararg,
            spec.kwarg,
        ]
        return [node.returns, *(a.annotation for a in arguments if a is not None)]
    if isinstance(node, ast.AnnAssign):
        return [node.annotation]
    return []


def _within(
    position: tuple[int, int],
    span: tuple[tuple[int, int], tuple[int, int]],
) -> bool:
    start, end = span
    return start <= position <= end


def is_annotation_mutant(
    spans: list[tuple[tuple[int, int], tuple[int, int]]],
    start_pos: tuple[int, int],
    end_pos: tuple[int, int],
) -> bool:
    """Whether a mutation lies wholly inside one annotation.

    Wholly, not partly: a mutation straddling an annotation's edge is not one
    this filter understands, and skipping it would be a guess. None have been
    observed; the strictness is so that an unobserved shape fails toward
    *running* the mutant rather than silently dropping it.
    """
    return any(_within(start_pos, s) and _within(end_pos, s) for s in spans)


class AnnotationsFilter(FilterApp):
    """Mark annotation-position mutants SKIPPED before they are ever run."""

    def description(self) -> str:
        return __doc__ or ""

    def add_args(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--report",
            action="store_true",
            help="print how many mutants were skipped, and from how many files",
        )

    def filter(self, work_db, args: Namespace) -> None:
        cache: dict[Path, list[tuple[tuple[int, int], tuple[int, int]]]] = {}
        skipped = 0
        files: set[Path] = set()

        for item in work_db.pending_work_items:
            for mutation in item.mutations:
                path = Path(mutation.module_path)
                if path not in cache:
                    try:
                        cache[path] = annotation_spans(path.read_text(encoding="utf-8"))
                    except OSError:
                        cache[path] = []
                if not is_annotation_mutant(cache[path], mutation.start_pos, mutation.end_pos):
                    continue
                work_db.set_result(
                    item.job_id,
                    WorkResult(
                        output="Filtered: mutation inside a type annotation (#419)",
                        worker_outcome=WorkerOutcome.SKIPPED,
                    ),
                )
                skipped += 1
                files.add(path)
                break

        if getattr(args, "report", False):
            print(f"skipped {skipped} annotation mutant(s) across {len(files)} file(s)")


def main(argv: list[str] | None = None) -> int:
    return AnnotationsFilter().main(argv)


if __name__ == "__main__":
    sys.exit(main())
