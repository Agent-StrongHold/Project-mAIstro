"""Objective code-quality scoring from ruff + bandit + radon.

Benchmark scoring for *code* has leaned on keyword matching and an LLM judge —
subjective and expensive. This module adds an objective, graded signal by
running three static tools and normalising each to 0..1:

  - **ruff**   — lint/style/correctness violations (fewer is better)
  - **bandit** — security issues, weighted by severity (fewer/lower is better)
  - **radon**  — cyclomatic complexity (lower) + maintainability index (higher)

The tools run as subprocesses (``python -m ruff|bandit|radon``), so this module
has no import-time dependency on them; a tool that isn't installed or errors is
dropped from the composite and the remaining weights renormalise (with a flag in
``tools_missing``), rather than silently scoring 0 or crashing. Use it two ways:
score the *quality of code an agent generates* (step-1 benchmark fitness) or the
*delta* on a self-modification to the codebase (step-2 code-level RSI gate).
"""

from __future__ import annotations

import ast
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class QualityWeights:
    # Continuous, graded measures (pylint/mi/type-coverage/cognitive/duplication/
    # docstrings/halstead) carry most of the weight — they spread across the
    # clean-to-excellent range. The defect floors (ruff/bandit/mypy/dead-code)
    # saturate at 1.0 for clean code, so they matter more as gates than as
    # score, and are weighted lightly here.
    pylint: float = 0.16
    type_coverage: float = 0.12
    cognitive: float = 0.12
    radon_mi: float = 0.10
    duplication: float = 0.10
    docstrings: float = 0.08
    halstead: float = 0.08
    bandit: float = 0.08
    ruff: float = 0.06
    mypy: float = 0.05
    dead_code: float = 0.03
    radon_cc: float = 0.02
    # semgrep is optional (needs install + ruleset); 0 weight unless the caller
    # opts in, so a missing semgrep doesn't perturb the default composite.
    semgrep: float = 0.0


@dataclass
class CodeQualityScore:
    composite: float
    ruff: float | None = None
    bandit: float | None = None
    mypy: float | None = None
    pylint: float | None = None
    docstrings: float | None = None
    halstead: float | None = None
    type_coverage: float | None = None
    cognitive: float | None = None
    duplication: float | None = None
    dead_code: float | None = None
    semgrep: float | None = None
    radon_cc: float | None = None
    radon_mi: float | None = None
    ruff_violations: int = 0
    bandit_issues: int = 0
    mypy_errors: int = 0
    pylint_rating: float = 0.0
    docstring_pct: float = 0.0
    halstead_difficulty: float = 0.0
    type_coverage_pct: float = 0.0
    duplication_pct: float = 0.0
    dead_code_count: int = 0
    cognitive_avg: float = 0.0
    semgrep_findings: int = 0
    avg_complexity: float = 0.0
    maintainability: float = 0.0
    tools_missing: list[str] = field(default_factory=list)


def _run_tool(args: list[str], *, timeout: int = 120) -> tuple[str, bool]:
    """Run ``python -m <args>``; return (stdout, available). available=False when
    the tool isn't installed, so callers can drop it instead of scoring it 0."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", False
    if "No module named" in proc.stderr:
        return "", False
    return proc.stdout, True


def _ruff(path: Path) -> tuple[float | None, int]:
    out, ok = _run_tool(["ruff", "check", "--output-format", "json", str(path)])
    if not ok:
        return None, 0
    try:
        violations = len(json.loads(out or "[]"))
    except json.JSONDecodeError:
        violations = 0
    return 1.0 / (1.0 + violations), violations


def _bandit(path: Path) -> tuple[float | None, int]:
    out, ok = _run_tool(["bandit", "-f", "json", "-q", str(path)])
    if not ok:
        return None, 0
    try:
        results = json.loads(out or "{}").get("results", [])
    except json.JSONDecodeError:
        results = []
    severity_weight = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    weighted = sum(severity_weight.get(r.get("issue_severity", "LOW"), 1) for r in results)
    return 1.0 / (1.0 + weighted), len(results)


def _mypy(path: Path) -> tuple[float | None, int]:
    # --ignore-missing-imports: don't penalise a snippet for deps it can't
    #   resolve; we're scoring the code's own type-consistency.
    # --config-file os.devnull: ignore the repo's pyproject mypy config (its
    #   pydantic plugin etc.), which would otherwise fail to import in a bare
    #   scoring env and looks like "tool missing".
    out, ok = _run_tool(
        [
            "mypy",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--no-color-output",
            "--config-file",
            os.devnull,
            str(path),
        ]
    )
    if not ok:
        return None, 0
    errors = sum(1 for line in out.splitlines() if ": error:" in line)
    return 1.0 / (1.0 + errors), errors


def _radon(path: Path) -> tuple[float | None, float | None, float, float]:
    cc_out, cc_ok = _run_tool(["radon", "cc", "-j", str(path)])
    mi_out, mi_ok = _run_tool(["radon", "mi", "-j", str(path)])
    avg_cc = 0.0
    cc_score: float | None = None
    if cc_ok:
        try:
            cc_data = json.loads(cc_out or "{}")
            ccs = [b["complexity"] for blocks in cc_data.values() for b in blocks]
            avg_cc = statistics.mean(ccs) if ccs else 1.0
            # A-grade (avg CC <= 5) is perfect; decays toward 0 by CC ~25.
            cc_score = 1.0 if avg_cc <= 5 else max(0.0, 1.0 - (avg_cc - 5) / 20)
        except (json.JSONDecodeError, KeyError):
            cc_score = None
    mi_raw = 0.0
    mi_score: float | None = None
    if mi_ok:
        try:
            mi_data = json.loads(mi_out or "{}")
            mis = [v["mi"] for v in mi_data.values() if isinstance(v, dict) and "mi" in v]
            mi_raw = statistics.mean(mis) if mis else 100.0
            mi_score = max(0.0, min(1.0, mi_raw / 100.0))
        except (json.JSONDecodeError, KeyError):
            mi_score = None
    return cc_score, mi_score, round(avg_cc, 2), round(mi_raw, 2)


def _pylint(path: Path) -> tuple[float | None, float]:
    # pylint's global rating is continuous (0..10) and folds in dozens of checks,
    # so it spreads clean code that ruff/bandit call "perfect". Disable import
    # resolution noise so a snippet isn't scored on unresolved deps.
    out, ok = _run_tool(
        ["pylint", str(path), "--score=y", "--disable=import-error,no-name-in-module"]
    )
    if not ok:
        return None, 0.0
    m = re.search(r"rated at (-?[\d.]+)/10", out)
    if not m:
        return None, 0.0
    rating = float(m.group(1))
    return max(0.0, rating / 10.0), rating


def _docstring_coverage(path: Path) -> tuple[float | None, float]:
    out, ok = _run_tool(["interrogate", str(path)])
    if not ok:
        return None, 0.0
    m = re.search(r"actual: ([\d.]+)%", out)
    if not m:
        return None, 0.0
    pct = float(m.group(1))
    return pct / 100.0, pct


def _halstead(path: Path) -> tuple[float | None, float]:
    # Halstead Difficulty (D = h1/2 * N2/h2): how hard the code is to understand
    # from its operator/operand structure. Lower is better; continuous.
    out, ok = _run_tool(["radon", "hal", str(path), "-j"])
    if not ok:
        return None, 0.0
    try:
        data = json.loads(out or "{}")
        diffs = [
            v["total"]["difficulty"]
            for v in data.values()
            if isinstance(v, dict) and isinstance(v.get("total"), dict)
        ]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None, 0.0
    difficulty = statistics.mean(diffs) if diffs else 0.0
    return 1.0 / (1.0 + difficulty / 15.0), round(difficulty, 1)


def _type_coverage(path: Path) -> tuple[float | None, float]:
    # Pure AST: fraction of function params (excluding self/cls) + returns that
    # carry a type annotation. Graded, unlike mypy's pass/fail.
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    except (SyntaxError, OSError, ValueError):
        return None, 0.0
    total = 0
    annotated = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            total += 1
            annotated += node.returns is not None
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs]:
                if arg.arg in ("self", "cls"):
                    continue
                total += 1
                annotated += arg.annotation is not None
    if total == 0:
        return 1.0, 100.0
    pct = annotated / total
    return pct, round(pct * 100, 1)


def _duplication(path: Path) -> tuple[float | None, float]:
    # Fraction of non-trivial logical lines that recur in a duplicated N-line
    # block within the file. Pure Python, deterministic.
    window = 4
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None, 0.0
    sig = [ln.strip() for ln in raw if len(ln.strip()) > 3 and not ln.strip().startswith("#")]
    if len(sig) < window * 2:
        return 1.0, 0.0
    seen: dict[tuple[str, ...], int] = {}
    dup: set[int] = set()
    for i in range(len(sig) - window + 1):
        block = tuple(sig[i : i + window])
        if block in seen:
            dup.update(range(i, i + window))
        else:
            seen[block] = i
    frac = len(dup) / len(sig)
    return 1.0 - frac, round(frac * 100, 1)


def _dead_code(path: Path) -> tuple[float | None, int]:
    # vulture finds unused code. It over-reports protocol-mandated unused params
    # (self-documenting sandbox/exc_info), so this is a soft signal, not a gate.
    out, ok = _run_tool(["vulture", str(path), "--min-confidence", "80"])
    if not ok:
        return None, 0
    n = sum(1 for line in out.splitlines() if "unused" in line)
    return 1.0 / (1.0 + n), n


def _cognitive(path: Path) -> tuple[float | None, float]:
    # complexipy's cognitive complexity weights nesting (unlike CC), so it tracks
    # "hard to understand" better. Imported (no `-m` entry point); missing → None.
    try:
        import complexipy  # type: ignore[import-not-found]

        result = complexipy.file_complexity(str(path))
        fns = getattr(result, "functions", [])
        avg = (sum(f.complexity for f in fns) / len(fns)) if fns else 0.0
    except Exception:
        return None, 0.0
    return 1.0 / (1.0 + avg / 15.0), round(avg, 1)


def _semgrep(path: Path) -> tuple[float | None, int]:
    # Deeper security/bug rules than bandit. Optional: needs semgrep installed
    # (+ a ruleset); any failure degrades to "missing" rather than blocking.
    out, ok = _run_tool(
        ["semgrep", "--config", "auto", "--json", "--quiet", "--timeout", "30", str(path)],
        timeout=90,
    )
    if not ok:
        return None, 0
    try:
        findings = json.loads(out or "{}").get("results", [])
    except json.JSONDecodeError:
        return None, 0
    return 1.0 / (1.0 + len(findings)), len(findings)


def score_path(path: str | Path, weights: QualityWeights | None = None) -> CodeQualityScore:
    """Score one file (or a directory tree) for code quality in 0..1."""
    weights = weights or QualityWeights()
    p = Path(path)
    ruff_s, ruff_v = _ruff(p)
    bandit_s, bandit_n = _bandit(p)
    mypy_s, mypy_e = _mypy(p)
    pylint_s, pylint_r = _pylint(p)
    doc_s, doc_pct = _docstring_coverage(p)
    hal_s, hal_d = _halstead(p)
    tc_s, tc_pct = _type_coverage(p)
    dup_s, dup_pct = _duplication(p)
    dead_s, dead_n = _dead_code(p)
    cog_s, cog_avg = _cognitive(p)
    sem_s, sem_n = _semgrep(p)
    cc_s, mi_s, avg_cc, mi_raw = _radon(p)

    parts: list[tuple[float, float]] = []  # (score, weight)
    missing: list[str] = []
    for name, score, weight in (
        ("ruff", ruff_s, weights.ruff),
        ("bandit", bandit_s, weights.bandit),
        ("mypy", mypy_s, weights.mypy),
        ("pylint", pylint_s, weights.pylint),
        ("docstrings", doc_s, weights.docstrings),
        ("halstead", hal_s, weights.halstead),
        ("type_coverage", tc_s, weights.type_coverage),
        ("duplication", dup_s, weights.duplication),
        ("dead_code", dead_s, weights.dead_code),
        ("cognitive", cog_s, weights.cognitive),
        ("semgrep", sem_s, weights.semgrep),
        ("radon_cc", cc_s, weights.radon_cc),
        ("radon_mi", mi_s, weights.radon_mi),
    ):
        if score is None:
            if weight > 0:
                missing.append(name)
        else:
            parts.append((score, weight))

    if parts:
        total_w = sum(w for _, w in parts)
        composite = sum(s * w for s, w in parts) / total_w if total_w else 0.0
    else:
        composite = 0.0

    return CodeQualityScore(
        composite=round(composite, 4),
        ruff=ruff_s,
        bandit=bandit_s,
        mypy=mypy_s,
        pylint=pylint_s,
        docstrings=doc_s,
        halstead=hal_s,
        type_coverage=tc_s,
        cognitive=cog_s,
        duplication=dup_s,
        dead_code=dead_s,
        semgrep=sem_s,
        radon_cc=cc_s,
        radon_mi=mi_s,
        ruff_violations=ruff_v,
        bandit_issues=bandit_n,
        mypy_errors=mypy_e,
        pylint_rating=pylint_r,
        docstring_pct=doc_pct,
        halstead_difficulty=hal_d,
        type_coverage_pct=tc_pct,
        duplication_pct=dup_pct,
        dead_code_count=dead_n,
        cognitive_avg=cog_avg,
        semgrep_findings=sem_n,
        avg_complexity=avg_cc,
        maintainability=mi_raw,
        tools_missing=missing,
    )


def score_source(code: str, weights: QualityWeights | None = None) -> CodeQualityScore:
    """Score a code *string* (e.g. an agent's generated fix) by writing it to a
    temp file first — this is the step-1 benchmark-fitness entry point."""
    with tempfile.TemporaryDirectory(prefix="maistro-qscore-") as tmp:
        f = Path(tmp) / "candidate.py"
        f.write_text(code, encoding="utf-8")
        return score_path(f, weights)
