#!/usr/bin/env python3
"""Judge one completed Pyright JSON scan without running the analyzer again.

The caller supplies the analyzer's real exit code and the existing error-count
baseline. Exit 1 from Pyright is a measured type-error result, not an execution
failure; other nonzero statuses are not eligible for the debt allowance. The
complete JSON diagnostics are printed from the same measurement used to judge
that allowance. No source analysis, cache, dependency installation, or network
access occurs here.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject ambiguous reports instead of accepting the last duplicate key."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _count(value: object, label: str) -> int:
    """Read a nonnegative integer without accepting bool, float, or text."""
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _diagnostic_counts(diagnostics: list[object]) -> Counter[str]:
    """Validate diagnostic entries and retain every severity in the count."""
    observed: Counter[str] = Counter()
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            raise ValueError("every diagnostic must be an object")
        severity = diagnostic.get("severity")
        if not isinstance(severity, str) or severity not in ("error", "warning", "information"):
            raise ValueError("diagnostic has an unsupported severity")
        if not isinstance(diagnostic.get("message"), str):
            raise ValueError("diagnostic requires a message")
        observed[severity] += 1
    return observed


def validate_report(report: object, exit_code: int) -> int:
    """Return the measured error count, or refuse invalid/incomplete execution.

    This contract is for the workflow's ordinary --outputjson invocation,
    without --warnings or diagnostic-level filtering. Unknown JSON fields are
    retained for display, but missing/count-inconsistent evidence cannot pass.
    """
    if exit_code not in (0, 1):
        raise ValueError(f"Pyright did not complete normally (exit {exit_code})")
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object")
    summary = report.get("summary")
    diagnostics = report.get("generalDiagnostics")
    if not isinstance(summary, dict) or not isinstance(diagnostics, list):
        raise ValueError("report requires summary and generalDiagnostics")
    if _count(summary.get("filesAnalyzed"), "filesAnalyzed") == 0:
        raise ValueError("Pyright analyzed no files")
    counts = {
        severity: _count(summary.get(f"{severity}Count"), f"{severity}Count")
        for severity in ("error", "warning", "information")
    }
    observed = _diagnostic_counts(diagnostics)
    if any(observed[severity] != count for severity, count in counts.items()):
        raise ValueError("diagnostic counts disagree with summary")
    errors = counts["error"]
    if exit_code != int(errors > 0):
        raise ValueError("Pyright exit code disagrees with its error count")
    return errors


def main(argv: list[str] | None = None) -> int:
    """Render and judge one report; 1 is regression, 2 is invalid evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--baseline", type=int, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        baseline = _count(args.baseline, "baseline")
        report = json.loads(
            args.report.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
        errors = validate_report(report, args.exit_code)
    except (OSError, ValueError) as exc:
        print(f"::error::invalid Pyright evidence: {exc}")
        return 2
    # JSON escaping keeps diagnostic text from becoming workflow commands.
    # Preserve all diagnostics, locations, rules and metadata, not just errors.
    print(json.dumps(report, indent=2, ensure_ascii=True))
    print(f"pyright error count: {errors} (baseline: {baseline})")
    if errors > baseline:
        print(f"::error::pyright regression: {errors} errors exceeds baseline of {baseline}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
