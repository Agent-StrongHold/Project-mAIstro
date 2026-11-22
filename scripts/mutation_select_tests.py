#!/usr/bin/env python3
"""Select, per changed line, the tests that actually execute it (#330).

A mutant can only be killed by a test that runs the mutated line. Running the
whole file-mirror suite per mutant is how the original PR job hit its
30-minute wall; #330 instead records, from a coverage run with per-test
contexts, exactly which tests execute each changed line and hands the mutation
runner one *test group* per distinct selected-test set. The runner then uses
each group's own tests — and each group's measured duration — as the per-mutant
timeout baseline.

Mechanics
---------
1. Run the scoped tests under coverage with `dynamic_context = test_function`
   so every executed line records which test executed it.
2. `pytest --collect-only` resolves context names (`test_mod.TestX.test_y`)
   to runnable node ids (`tests/test_mod.py::TestX::test_y`).
3. Only executable changed lines are selection candidates: comments, blank
   lines, and docstrings are never mutation targets, and a line executed only
   at import time is covered (it runs) even though no single test owns it —
   neither may fail the gate. An executable line nothing executes is reported
   explicitly as `no_coverage` and fails gate mode — that silence is a
   coverage gap, not a pass.
4. Changed lines sharing the same selected-test set collapse into one group;
   the runner scores one mutant set per distinct test set.

The per-line data is the contract: grouping is an optimization. Two changed
lines with different selected tests never share a mutant run, so no mutant is
ever scored against tests that cannot see it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class Selection:
    """Per-line selected tests, grouped, with uncovered lines named."""

    groups: list[dict] = field(default_factory=list)  # {"lines": [...], "tests": [...]}
    no_coverage: list[int] = field(default_factory=list)
    # Changed lines excluded before per-test coverage is required, with the
    # reason: not executable at all (comments/blank lines) vs. executed only
    # at import time (covered, but no single test is attributable).
    non_executable: list[int] = field(default_factory=list)
    import_time_only: list[int] = field(default_factory=list)


def coverage_contexts(coverage_json: dict, source: str) -> dict[int, list[str]]:
    """Line -> context names for one file of a `coverage json --show-contexts` payload."""
    contexts = _coverage_file_entry(coverage_json, source).get("contexts", {})
    # A line executed at import time (module body) reports an empty-string
    # context — it names no test, so it selects nothing.
    return {
        int(line): [name for name in names if name]
        for line, names in contexts.items()
        if any(names)
    }


def _coverage_file_entry(coverage_json: dict, source: str) -> dict:
    path = str(Path(source))
    files = coverage_json.get("files", {})
    entry = files.get(path) or files.get(path.replace("\\", "/"))
    if entry is None:
        raise ValueError(f"coverage report has no entry for {source}; was --cov scoped to it?")
    return entry


def coverage_executable_lines(coverage_json: dict, source: str) -> tuple[set[int], set[int]]:
    """(executed, missing) line numbers for one file of a coverage JSON report.

    Coverage lists an executable line exactly once: in `executed_lines` when a
    run reached it, in `missing_lines` when it did not. A line in neither is
    not executable — a comment, blank line, or docstring — and can never be a
    mutation target, so it must not be demanded of the coverage gate.
    """
    entry = _coverage_file_entry(coverage_json, source)
    executed = {int(line) for line in entry.get("executed_lines", [])}
    missing = {int(line) for line in entry.get("missing_lines", [])}
    return executed, missing


def partition_changed(
    changed: list[int],
    executed: set[int],
    missing: set[int],
    by_line: dict[int, list[str]],
) -> tuple[list[int], list[int], list[int]]:
    """Split changed lines into (testable, non_executable, import_time_only).

    `testable` holds the executable mutation targets per-test coverage is
    required for — including executable-but-unexecuted lines, which `group_lines`
    surfaces as `no_coverage`. Non-executable lines and lines coverage executed
    without a test context (import-time module body) are excluded: requiring
    tests for them fails the gate on lines no test can ever be credited with.
    """
    executable = executed | missing
    testable: list[int] = []
    non_executable: list[int] = []
    import_time_only: list[int] = []
    for line in changed:
        if line not in executable:
            non_executable.append(line)
        elif line in executed and not by_line.get(line):
            import_time_only.append(line)
        else:
            testable.append(line)
    return testable, non_executable, import_time_only


def context_to_node_id(context: str, collected: dict[str, str]) -> list[str]:
    """Resolve a coverage context name to runnable pytest node ids.

    Contexts look like `test_mod.TestX.test_y[param]`; collected node ids look
    like `tests/test_mod.py::TestX::test_y[param]`. The mapping key is the file
    stem joined to the `::`-parts by dots. Ambiguous stems resolve to EVERY
    candidate: over-selection costs runner seconds, but under-selection could
    drop the one test that kills a mutant.

    Coverage roots context names at the test module's import path, which for a
    packaged suite carries a package prefix the stem mapping lacks
    (`security.test_mod.TestX.test_y` vs key `test_mod.TestX.test_y`). When the
    exact forms do not line up, a collected key still matches when it is a
    dotted-path suffix of the context — the same over-selection bias.
    """
    _stem, _sep, qualname = context.partition(".")
    if not qualname:
        return []
    matches = [node for key, node in collected.items() if key == context]
    if not matches:
        # Parameterized contexts keep the param suffix; try stripping it.
        base = context.split("[", 1)[0]
        matches = [node for key, node in collected.items() if key.split("[", 1)[0] == base]
    if not matches:
        base = context.split("[", 1)[0]
        matches = [
            node for key, node in collected.items() if base.endswith("." + key.split("[", 1)[0])
        ]
    return sorted(set(matches))


def parse_collected(lines: list[str]) -> dict[str, str]:
    """`pytest --collect-only -q` output -> {context-name: node-id}."""
    out: dict[str, str] = {}
    for line in lines:
        line = line.strip()
        if not line or "::" not in line or line.startswith("="):
            continue
        parts = line.split("::")
        stem = Path(parts[0]).stem
        qualname = ".".join(parts[1:])
        out[f"{stem}.{qualname}"] = line
    return out


def group_lines(changed: list[int], line_tests: dict[int, list[str]]) -> Selection:
    """Collapse changed lines into one group per distinct selected-test set."""
    selection = Selection()
    grouped: dict[tuple[str, ...], list[int]] = {}
    for line in sorted(changed):
        tests = sorted(set(line_tests.get(line, [])))
        if not tests:
            selection.no_coverage.append(line)
            continue
        grouped.setdefault(tuple(tests), []).append(line)
    selection.groups = [
        {"lines": lines, "tests": list(tests)} for tests, lines in sorted(grouped.items())
    ]
    return selection


def _package_pythonpath() -> str:
    return ":".join(str(p) for p in sorted((ROOT / "packages").glob("*/src"))) or str(ROOT)


def select(
    source: str,
    tests: str,
    changed: list[int],
    *,
    env_extra: dict[str, str] | None = None,
    pytest_args: list[str] | None = None,
) -> Selection:
    """Run the coverage + collection pass and return per-line selection."""
    with tempfile.TemporaryDirectory(prefix="mutation-select-") as tmp:
        tmp_path = Path(tmp)
        rc = tmp_path / "coveragerc"
        rc.write_text(
            f"[run]\ndynamic_context = test_function\ndata_file = {tmp_path / '.coverage'}\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = _package_pythonpath()
        if env_extra:
            env.update(env_extra)

        # coverage's source selector accepts only directories or importable
        # names, so scope to the file's directory and let coverage_contexts
        # pick out the target file's lines from the JSON report.
        src_path = Path(source)
        cov_target = str(src_path.parent) if src_path.suffix == ".py" else source
        cov_run = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                tests,
                *(pytest_args or ["-q", "--timeout=120", "-p", "no:cacheprovider"]),
                "--cov",
                f"--cov-config={rc}",
                "--cov-report=",
                f"--cov={cov_target}",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if cov_run.returncode != 0:
            print(cov_run.stdout[-4000:], file=sys.stderr)
            print(
                f"::error::selected-test baseline run failed (exit {cov_run.returncode}); "
                "mutation selection cannot proceed on a red baseline.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        report = tmp_path / "coverage.json"
        coverage_env = dict(env)
        coverage_env["COVERAGE_FILE"] = str(tmp_path / ".coverage")
        coverage_env["COVERAGE_RCFILE"] = str(rc)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "json",
                "--show-contexts",
                "-o",
                str(report),
            ],
            cwd=ROOT,
            env=coverage_env,
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(report.read_text(encoding="utf-8"))
        by_line = coverage_contexts(payload, source)
        executed, missing = coverage_executable_lines(payload, source)
        testable, non_executable, import_time_only = partition_changed(
            changed, executed, missing, by_line
        )
        if non_executable:
            print(
                f"::notice::{source}: non-executable changed line(s) {non_executable} "
                "excluded from coverage requirements (no mutation target).",
                file=sys.stderr,
            )
        if import_time_only:
            print(
                f"::warning::{source}: changed line(s) {import_time_only} execute only "
                "at import time; covered, but no single test selects them.",
                file=sys.stderr,
            )

        collect = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                tests,
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        collected = parse_collected(collect.stdout.splitlines())

    resolved: dict[int, list[str]] = {}
    for line in testable:
        node_ids: set[str] = set()
        for context in by_line.get(line, []):
            node_ids.update(context_to_node_id(context, collected))
        if not node_ids and by_line.get(line):
            print(
                f"::warning::line {line} of {source} was executed but its context "
                "could not be resolved to a node id; treating as uncovered.",
                file=sys.stderr,
            )
        resolved[line] = sorted(node_ids)
    selection = group_lines(testable, resolved)
    selection.non_executable = sorted(non_executable)
    selection.import_time_only = sorted(import_time_only)
    return selection


def _read_lines(path: str) -> list[int]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    lines = (
        [int(line) for line in payload]
        if isinstance(payload, list)
        else sorted(int(k) for k in payload)
    )
    if not lines:
        raise SystemExit("changed-line set is empty; nothing to select tests for")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tests", required=True)
    parser.add_argument("--lines", required=True, help="JSON array (or object) of changed lines")
    parser.add_argument("--output", required=True, help="selection JSON output path")
    parser.add_argument(
        "--allow-uncovered",
        action="store_true",
        help="report no-coverage lines without failing (measurement runs)",
    )
    args = parser.parse_args(argv)

    changed = _read_lines(args.lines)
    selection = select(args.source, args.tests, changed)

    args_output = Path(args.output)
    args_output.write_text(
        json.dumps(
            {
                "source": args.source,
                "tests": args.tests,
                "changed_lines": sorted(changed),
                "groups": selection.groups,
                "no_coverage": selection.no_coverage,
                "non_executable": selection.non_executable,
                "import_time_only": selection.import_time_only,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    total_selected = len({t for g in selection.groups for t in g["tests"]})
    print(
        f"test selection for {args.source}: {len(selection.groups)} group(s), "
        f"{total_selected} selected test(s), {len(selection.no_coverage)} no-coverage "
        f"line(s), {len(selection.non_executable)} non-executable, "
        f"{len(selection.import_time_only)} import-time-only"
    )
    for line in selection.no_coverage:
        # A changed line nothing executes is exactly the "zero selected tests"
        # condition #330 refuses to let pass silently.
        print(f"  no selected test executes line {line}", file=sys.stderr)
    if selection.no_coverage and not args.allow_uncovered:
        print(
            f"::error::{args.source}: changed line(s) {selection.no_coverage} have no "
            "selected test. Zero selected tests is explicit, never a pass.",
            file=sys.stderr,
        )
        return 1
    if not selection.groups:
        print(
            f"::error::{args.source}: zero selected tests across all changed lines; "
            "refusing to produce an empty mutation run.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
