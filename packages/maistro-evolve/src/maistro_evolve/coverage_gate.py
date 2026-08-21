"""Test coverage as a fitness signal — a *substantial* gate plus a graded score.

Unlike the static code-quality metrics (which score a file in isolation),
coverage is a project-level, run-based measure: it needs the test suite executed
under instrumentation, and the meaningful quantity is the *delta* vs. the
baseline. A self-modification that quietly deletes tests or adds untested code
should be **rejected outright** — so coverage-not-dropping is a hard gate (the
most substantial form a signal can take), and the absolute coverage is also
offered as a graded score for ranking among candidates that pass.

Coverage measures real correctness *assurance*, not a proxy — which is why it
earns a veto where the shallow metrics (docstrings, style) only earn weight.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from maistro_evolve.scorecard import GateResult, MeasureKind, SignalScore


def measure_coverage(
    repo_dir: str | Path,
    *,
    source: str = ".",
    pytest_args: str = "",
    timeout: int = 900,
) -> float | None:
    """Run the suite under coverage in ``repo_dir``; return total % covered (0..100).

    Returns None if coverage can't be produced (tool missing, no data) so the
    caller can treat coverage as unavailable rather than as 0% — which would
    falsely fail the gate.
    """
    total, _ = measure_coverage_detailed(
        repo_dir, source=source, pytest_args=pytest_args, timeout=timeout
    )
    return total


def measure_coverage_detailed(
    repo_dir: str | Path,
    *,
    source: str = ".",
    pytest_args: str = "",
    timeout: int = 900,
) -> tuple[float | None, dict[str, list[int]]]:
    """Like :func:`measure_coverage`, but also returns each file's uncovered
    (missing) line numbers — the scout uses these to target real gaps instead
    of guessing, and to earn the ambition to propose a ``feature`` once a
    module's uncovered lines run out. Paths are normalized to forward slashes
    so they compare consistently across OS. One ``coverage run`` + ``coverage
    json`` invocation, same as ``measure_coverage`` — no extra cost.

    Returns ``(total_pct, {file: [missing_line, ...]})``; the dict is empty
    whenever coverage data can't be produced.
    """
    cwd = str(repo_dir)
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "coverage",
                "run",
                f"--source={source}",
                "-m",
                "pytest",
                *shlex.split(pytest_args),
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # Even if some tests fail, coverage data may still exist — read it anyway.
        report = subprocess.run(
            [sys.executable, "-m", "coverage", "json", "-o", "-"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, {}
    if report.returncode != 0 or not report.stdout.strip():
        return None, {}
    try:
        payload = json.loads(report.stdout)
        total = float(payload["totals"]["percent_covered"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None, {}
    missing: dict[str, list[int]] = {}
    for file_path, file_data in payload.get("files", {}).items():
        lines = file_data.get("missing_lines")
        if lines:
            missing[file_path.replace("\\", "/")] = list(lines)
    return total, missing


def new_source_lines(
    repo_dir: str | Path, baseline_ref: str, src_files: list[str]
) -> dict[str, set[int]]:
    """Line numbers ADDED (not context) to each source file vs ``baseline_ref``.

    An aggregate coverage percentage can rise for reasons unrelated to the new
    lines in THIS diff (another test in the same candidate covering unrelated
    code) — this pins down exactly which lines the diff actually introduced, so
    ``uncovered_new_lines`` can check whether those specific lines execute,
    rather than trusting a project-wide number as a proxy.
    """
    cwd = Path(repo_dir)
    added: dict[str, set[int]] = {}
    for rel in src_files:
        proc = subprocess.run(
            ["git", "diff", "--unified=0", baseline_ref, "--", rel],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0 or not proc.stdout:
            continue
        lines: set[int] = set()
        cur: int | None = None
        for ln in proc.stdout.splitlines():
            if ln.startswith("@@"):
                m = re.search(r"\+(\d+)", ln)
                cur = int(m.group(1)) if m else None
                continue
            if cur is None:
                continue
            if ln.startswith("+") and not ln.startswith("+++"):
                lines.add(cur)
                cur += 1
            elif ln.startswith("-") and not ln.startswith("---"):
                continue  # removed line — absent from the new file, cur unmoved
        if lines:
            added[rel.replace("\\", "/")] = lines
    return added


def uncovered_new_lines(
    new_lines: dict[str, set[int]], missing: dict[str, list[int]]
) -> dict[str, list[int]]:
    """Of the lines a diff ADDED, which ones the coverage run never executed.

    Non-empty means the candidate's new code shipped with a gap no test in this
    candidate actually exercises — regardless of whether some OTHER change in
    the same diff raised the project's overall coverage percentage.
    """
    result: dict[str, list[int]] = {}
    for file, lines in new_lines.items():
        missed = sorted(lines & set(missing.get(file, [])))
        if missed:
            result[file] = missed
    return result


def coverage_gate(
    baseline_pct: float | None, candidate_pct: float | None, *, tolerance: float = 0.5
) -> GateResult:
    """Hard veto: the candidate must not drop coverage below baseline (minus a
    small tolerance for run-to-run noise). Unavailable coverage is not enforced."""
    if baseline_pct is None or candidate_pct is None:
        return GateResult("coverage_not_dropped", True, "coverage unavailable — gate not enforced")
    dropped = candidate_pct < baseline_pct - tolerance
    delta = candidate_pct - baseline_pct
    sign = "+" if delta >= 0 else ""
    return GateResult(
        "coverage_not_dropped",
        passed=not dropped,
        reason=f"{candidate_pct:.1f}% vs baseline {baseline_pct:.1f}% ({sign}{delta:.1f}, tol {tolerance})",
    )


# Coverage swing (percentage points) that maps a change to a full 0→1 score.
# A +2pp gain scores 1.0, flat scores the 0.5 neutral, -2pp scores 0.0. Chosen so
# even a modest single-test gain registers above neutral; the big reward for
# *adding* a test is the presence-gated ``new_test`` signal, this just grades the
# direction of the coverage move.
_COVERAGE_SWING_PP = 2.0


def coverage_signal(
    baseline_pct: float | None, candidate_pct: float | None, weight: float
) -> SignalScore:
    """Coverage **delta** as a graded score (0..1): reward the direction of the
    move, not the absolute level. Flat coverage is neutral (0.5), a gain trends to
    1.0, a drop toward 0.0 — so a candidate that adds a covering test scores well
    and one that merely restyles (flat) does not, where the old absolute score
    made every candidate look identical at the suite's standing coverage."""
    cand = candidate_pct or 0.0
    base = baseline_pct if baseline_pct is not None else cand
    delta = cand - base
    sign = "+" if delta >= 0 else ""
    score = max(0.0, min(1.0, 0.5 + delta / (2 * _COVERAGE_SWING_PP)))
    return SignalScore(
        name="coverage",
        kind=MeasureKind.DERIVED,
        score=score,
        weight=weight,
        rationale=f"coverage {sign}{delta:.1f}pp ({base:.1f}% → {cand:.1f}%)",
        detail={"baseline": base, "candidate": cand, "delta": delta},
    )
