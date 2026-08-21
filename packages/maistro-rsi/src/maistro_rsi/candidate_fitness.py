"""Compose the fitness signals into one promotion decision for the RSI loop.

Gathers the *local* signals for a baseline→candidate pair (tests, coverage,
code-quality, assertion-strength, lint/type/security gates) and builds the
transparent `Scorecard`: gates first (any veto ⇒ reject), then priority-weighted
scores (`FitnessWeights`). Capability (benchmarks) and architecture-fit (LLM
judge) are *injected* when a gateway is available, so this module stays
runnable offline. `compose_scorecard()` is pure and takes already-gathered
`FitnessInputs`; `evaluate_candidate()` runs the tools to produce them.
"""

from __future__ import annotations

import ast
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from maistro_evolve.assertion_strength import score_assertions
from maistro_evolve.code_quality import score_path
from maistro_evolve.coverage_gate import (
    coverage_gate,
    coverage_signal,
    measure_coverage_detailed,
    new_source_lines,
    uncovered_new_lines,
)
from maistro_evolve.doc_regression import doc_regressions
from maistro_evolve.mutation_probe import MutationProbe, probe_diff_mutations
from maistro_evolve.scorecard import (
    FitnessWeights,
    GateResult,
    MeasureKind,
    Scorecard,
    SignalScore,
    architecture_fit_signal,
    capability_signal,
    judge_signal,
    perf_signal,
)
from maistro_evolve.tdd_gate import (
    TddEvidence,
    changed_test_paths,
    count_net_new_tests,
    new_test_signal,
    red_green_signal,
    run_test_selection,
)

_TEST_HINTS = ("test_", "_test.py", "/tests/", "conftest.py")

# Minimum fraction of diff-scoped mutants the candidate's own tests must kill for
# the ``tests_pin_behavior`` gate to pass. Half is deliberately lenient: it
# rejects only changes whose tests miss the majority of introduced-behavior
# mutations — the clear over-solving / reward-hacking signature — while tolerating
# the odd equivalent-ish mutant that no reasonable test would catch.
_MUTATION_KILL_THRESHOLD = 0.5

# Cap on mutants run per candidate. Each mutant reruns the changed tests once, so
# this bounds the probe's cost; the site list is truncated deterministically.
_MUTATION_MAX_MUTANTS = 6


def _is_test(path: str) -> bool:
    return any(h in path.replace("\\", "/") for h in _TEST_HINTS)


def _syntax_check(cwd: Path, py_files: list[str]) -> list[str]:
    """Every changed ``.py`` file must at least parse — test or source, in or
    out of the configured test roots. A file that can't be collected by the
    scoped test command (see ``_uncollectable_tests``) is otherwise invisible
    to every other gate, so a broken file can sit silently in the repo forever
    unless something checks it unconditionally. This is that check."""
    reasons: list[str] = []
    for rel in py_files:
        path = cwd / rel
        if not path.is_file():
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError as exc:
            reasons.append(f"{rel}: {exc.msg} (line {exc.lineno})")
        except OSError:
            continue
    return reasons


def _parse_test_roots(pytest_args: str) -> list[str]:
    """Extract the configured test-root paths from a pytest args string.

    ``coverage_pytest_args`` (and ``test_command``) already encode exactly the
    paths pytest will collect from — e.g. ``"packages/x/tests packages/y/tests
    --ignore=..."``. Parsing them here means a new test file's location can be
    checked against the SAME roots the harness actually uses, with no separate
    config to keep in sync.
    """
    roots = []
    for tok in shlex.split(pytest_args):
        if tok.startswith("-"):
            continue
        roots.append(tok.replace("\\", "/").rstrip("/"))
    return roots


def _uncollectable_tests(
    cwd: Path, test_files: list[str], valid_roots: list[str], src_files: list[str] | None = None
) -> list[str]:
    """New/changed test files that the harness's own scoped pytest invocation
    would never run: either the path falls outside every configured test root,
    or pytest can't collect any item from it (e.g. a syntax error, or a name
    that doesn't match pytest's discovery pattern). A test the harness never
    executes contributes nothing — its presence must not be rewarded, and it
    should not silently accumulate as repo clutter.

    If the test file falls outside the configured roots BUT is in a valid test
    directory for a package that has source in the diff (auto-discovery), the
    gate PASSES — the agent put the test in the right place for the source it
    changed, the operator just didn't include that package's tests in the scope.
    """
    # auto-discover valid test roots from the changed SOURCE files: if the
    # agent changed a file in packages/X/src, then packages/X/tests is a
    # legitimate test root even if the operator didn't list it.
    auto_roots: list[str] = []
    if src_files:
        for sf in src_files:
            norm = sf.replace("\\", "/")
            # packages/maistro-core/src/... → packages/maistro-core/tests
            parts = norm.split("/")
            for i, part in enumerate(parts):
                if part == "src" and i > 0:
                    pkg_root = "/".join(parts[:i])
                    auto_roots.append(f"{pkg_root}/tests")
                    break
    all_roots = list(set(valid_roots + auto_roots))

    reasons: list[str] = []
    for rel in test_files:
        norm = rel.replace("\\", "/")
        if all_roots and not any(norm == root or norm.startswith(root + "/") for root in all_roots):
            reasons.append(f"{rel}: outside configured test roots ({', '.join(valid_roots)})")
            continue
        if not (cwd / rel).is_file():
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "pytest", "--collect-only", "-q", rel],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            reasons.append(f"{rel}: collection timed out or errored")
            continue
        if proc.returncode != 0:
            # 0 = collected >=1 item; 5 = "no tests collected"; anything else =
            # a collection error (e.g. import failure) — all three mean this
            # file contributes nothing the harness will ever run.
            reasons.append(f"{rel}: pytest could not collect it (exit {proc.returncode})")
    return reasons


@dataclass
class FitnessInputs:
    tests_passed: bool
    test_reason: str = ""
    baseline_coverage: float | None = None
    candidate_coverage: float | None = None
    code_quality_composite: float | None = None
    code_quality_detail: str = ""
    assertion_score: float | None = None
    assertion_detail: str = ""
    tdd: TddEvidence = field(default_factory=TddEvidence)
    lint_gates: list[GateResult] = field(default_factory=list)
    capability: tuple[float, float] | None = None
    architecture_fit: object | None = None
    # Net-new ``test_*`` functions added by the candidate (drives the presence-
    # gated ``new_test`` signal together with the coverage delta).
    net_new_tests: int = 0
    # Lines this diff ADDED to source files that the coverage run never
    # executed (coverage_gate.uncovered_new_lines) — non-empty withholds the
    # new_test signal even if some unrelated coverage gain in the same diff
    # pushed the aggregate percentage up.
    uncovered_new_source_lines: dict[str, list[int]] = field(default_factory=dict)
    # Symbols whose docstring lost material specificity — any entry vetoes.
    doc_regression_reasons: list[str] = field(default_factory=list)
    # LLM impact judge for a FEATURE/v2.0 change: (score 0..1, rationale). Injected
    # only when a judge gateway is available; absent otherwise.
    feature_judge: tuple[float, str] | None = None
    # Wall-clock timing for a PERF change: (baseline_seconds, candidate_seconds).
    perf: tuple[float, float] | None = None
    # AC ids newly claimed by @pytest.mark.ac in this candidate's tests (net-new
    # vs baseline — see spec_tracker.new_ac_coverage). Non-empty + green tests ⇒
    # the spec_completion signal fires: the biggest single reward in the system.
    new_ac_ids: list[str] = field(default_factory=list)
    # Spec ids of NEW well-formed docs/specs/ contracts this candidate authored
    # (spec_tracker.proposed_specs) — the BACKLOG path: formalise the idea first.
    proposed_spec_ids: list[str] = field(default_factory=list)
    # Any changed .py file that fails ast.parse — vetoes unconditionally, test
    # or source, in or out of the configured test roots.
    syntax_error_reasons: list[str] = field(default_factory=list)
    # New/changed test files pytest's own scoped invocation would never
    # collect (wrong location, or a collection error) — vetoes; an uncollected
    # test contributes nothing and must not be counted as verification.
    uncollectable_test_reasons: list[str] = field(default_factory=list)
    # A changed test that still passes with its accompanying source change
    # reverted to baseline — it doesn't exercise what it claims to. Distinct
    # from a genuine characterization test (no source change at all in the
    # diff), which never triggers this.
    vacuous_test_reasons: list[str] = field(default_factory=list)
    # Second-opinion LLM regression check (score 0..1, rationale) — only ever
    # populated after every other gate already passed (see evaluate_candidate),
    # so a doomed candidate never burns the extra LLM call.
    regression_judge: tuple[float, str] | None = None
    # Diff-scoped mutation probe: do the candidate's own tests catch mutations of
    # the lines it added? Only populated after the cheap gates pass (mutation
    # runs the tests once per mutant). An unavailable probe (no changed tests, no
    # mutable new lines) adds no gate — never a false rejection.
    mutation_probe: MutationProbe | None = None


def _ladder_signals(inp: FitnessInputs, w: FitnessWeights) -> list[SignalScore]:
    """Presence-gated maturity-ladder rewards: each fires only on the real event
    (net-new AC claims with green tests / a new well-formed spec contract), so
    it can never dilute candidates doing other work, and can't be farmed by
    re-tagging existing ACs (only net-new ids count — spec_tracker)."""
    signals: list[SignalScore] = []
    if inp.new_ac_ids and inp.tests_passed:
        signals.append(
            SignalScore(
                "spec_completion",
                MeasureKind.CALCULATED,
                1.0,
                w.spec_completion,
                f"newly proven acceptance criteria: {', '.join(inp.new_ac_ids)}",
            )
        )
    if inp.proposed_spec_ids:
        signals.append(
            SignalScore(
                "spec_proposed",
                MeasureKind.CALCULATED,
                1.0,
                w.spec_proposed,
                f"new spec contract(s) drafted: {', '.join(inp.proposed_spec_ids)}",
            )
        )
    return signals


def _mutation_gate(inp: FitnessInputs) -> GateResult | None:
    """The anti-reward-hacking veto: the candidate's own tests must catch the
    majority of mutations of the lines it added, or the change is under-verified
    (overfit to the observed tests rather than pinning behavior). None when the
    probe measured nothing — an unavailable probe adds no gate."""
    mp = inp.mutation_probe
    if mp is None or not mp.available:
        return None
    return GateResult(
        "tests_pin_behavior",
        mp.score >= _MUTATION_KILL_THRESHOLD,
        mp.summary(),
        detail={"score": mp.score, "killed": mp.killed, "survived": mp.survived},
    )


def _conditional_gates(inp: FitnessInputs) -> list[GateResult]:
    """Gates that only exist when their (optional) evidence was gathered: the
    second-opinion LLM regression judge, and the diff-scoped mutation probe.
    Kept out of ``compose_scorecard`` so the assembly there stays flat."""
    gates: list[GateResult] = []
    if inp.regression_judge is not None:
        score, rationale = inp.regression_judge
        gates.append(
            GateResult("no_flagged_regression", score >= 0.4, rationale, detail={"score": score})
        )
    mut_gate = _mutation_gate(inp)
    if mut_gate is not None:
        gates.append(mut_gate)
    return gates


def _mutation_signal(inp: FitnessInputs, w: FitnessWeights) -> SignalScore | None:
    """Ranking contribution for a passing candidate: how strongly its tests pin
    the introduced behavior. Present only when the probe measured something."""
    mp = inp.mutation_probe
    if mp is None or not mp.available:
        return None
    return SignalScore(
        "mutation_strength",
        MeasureKind.CALCULATED,
        mp.score,
        w.mutation_strength,
        mp.summary(),
    )


def compose_scorecard(inp: FitnessInputs, weights: FitnessWeights | None = None) -> Scorecard:
    """Pure: assemble gates + priority-weighted scores into a Scorecard."""
    w = weights or FitnessWeights()
    gates = [
        GateResult(
            "tests_pass",
            inp.tests_passed,
            inp.test_reason or ("ok" if inp.tests_passed else "failed"),
        ),
        coverage_gate(inp.baseline_coverage, inp.candidate_coverage),
        GateResult(
            "no_doc_regression",
            not inp.doc_regression_reasons,
            "; ".join(inp.doc_regression_reasons) or "no docstring made vaguer",
        ),
        GateResult(
            "valid_syntax",
            not inp.syntax_error_reasons,
            "; ".join(inp.syntax_error_reasons) or "all changed .py files parse",
        ),
        GateResult(
            "tests_collectable",
            not inp.uncollectable_test_reasons,
            "; ".join(inp.uncollectable_test_reasons) or "all changed test files are collectable",
        ),
        GateResult(
            "test_exercises_change",
            not inp.vacuous_test_reasons,
            "; ".join(inp.vacuous_test_reasons)
            or "changed tests depend on the accompanying change",
        ),
        *inp.lint_gates,
        *_conditional_gates(inp),
    ]
    scores: list[SignalScore] = [red_green_signal(inp.tdd, w.red_green)]
    cov_delta = (
        inp.candidate_coverage - inp.baseline_coverage
        if inp.candidate_coverage is not None and inp.baseline_coverage is not None
        else None
    )
    nt = new_test_signal(
        inp.net_new_tests,
        cov_delta,
        w.new_test,
        uncovered_new_lines=inp.uncovered_new_source_lines,
    )
    if nt is not None:
        scores.append(nt)
    scores.extend(_ladder_signals(inp, w))
    if inp.feature_judge is not None:
        scores.append(
            judge_signal(
                "feature_judge", inp.feature_judge[0], w.feature_judge, inp.feature_judge[1]
            )
        )
    if inp.perf is not None:
        scores.append(perf_signal(inp.perf[0], inp.perf[1], w.perf))
    if inp.capability is not None:
        scores.append(capability_signal(inp.capability[0], inp.capability[1], w.capability))
    if inp.assertion_score is not None:
        scores.append(
            SignalScore(
                "assertion_strength",
                MeasureKind.CALCULATED,
                inp.assertion_score,
                w.assertion_strength,
                inp.assertion_detail or "changed-test assertion strength",
            )
        )
    mut_signal = _mutation_signal(inp, w)
    if mut_signal is not None:
        scores.append(mut_signal)
    if inp.candidate_coverage is not None:
        scores.append(coverage_signal(inp.baseline_coverage, inp.candidate_coverage, w.coverage))
    if inp.architecture_fit is not None:
        scores.append(architecture_fit_signal(inp.architecture_fit, w.architecture_fit))
    if inp.code_quality_composite is not None:
        scores.append(
            SignalScore(
                "code_quality",
                MeasureKind.DERIVED,
                inp.code_quality_composite,
                w.code_quality,
                inp.code_quality_detail or "changed-source quality composite",
            )
        )
    return Scorecard(gates=gates, scores=scores)


def _run(cmd: str, cwd: Path, timeout: int = 900) -> tuple[bool, str]:
    try:
        # shell=True: `cmd` is operator-supplied test config, not agent/attacker input.
        proc = subprocess.run(  # nosemgrep
            cmd,
            shell=True,  # nosemgrep
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"test command errored: {exc}"
    tail = (proc.stdout + proc.stderr).strip()[-200:]
    return (
        proc.returncode == 0,
        f"exit {proc.returncode}: {tail}" if tail else f"exit {proc.returncode}",
    )


_LINT_TIMEOUT = 120


def _run_lint_tool(argv: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    """Run a static tool, bounded by a timeout. Returns None if the tool is
    missing or wedges — so the gate is treated as unavailable (not a false
    rejection, and never an indefinite hang of LocalRsiLoop.run())."""
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd), capture_output=True, text=True, timeout=_LINT_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if "No module named" in proc.stderr:
        return None
    return proc


def _lint_gates(cwd: Path, src_files: list[str]) -> list[GateResult]:
    """ruff / mypy / bandit-HIGH on the changed source files. A missing, errored,
    or timed-out tool yields no gate (unenforced) rather than a false rejection."""
    if not src_files:
        return []
    gates: list[GateResult] = []

    ruff = _run_lint_tool(
        [sys.executable, "-m", "ruff", "check", "--output-format", "json", *src_files], cwd
    )
    if ruff is not None:
        try:
            n = len(json.loads(ruff.stdout or "[]"))
        except json.JSONDecodeError:
            n = 0
        gates.append(GateResult("ruff_clean", n == 0, f"{n} lint violation(s)"))

    mypy = _run_lint_tool(
        [
            sys.executable,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--no-color-output",
            "--config-file",
            os.devnull,
            *src_files,
        ],
        cwd,
    )
    if mypy is not None:
        errs = sum(1 for ln in mypy.stdout.splitlines() if ": error:" in ln)
        gates.append(GateResult("mypy_clean", errs == 0, f"{errs} type error(s)"))

    bandit = _run_lint_tool([sys.executable, "-m", "bandit", "-f", "json", "-q", *src_files], cwd)
    if bandit is not None:
        try:
            results = json.loads(bandit.stdout or "{}").get("results", [])
        except json.JSONDecodeError:
            results = []
        high = [r for r in results if r.get("issue_severity") == "HIGH"]
        gates.append(
            GateResult("no_bandit_high", len(high) == 0, f"{len(high)} HIGH-severity finding(s)")
        )
    return gates


def _mean_quality(cwd: Path, src_files: list[str]) -> tuple[float | None, str]:
    composites = []
    for f in src_files:
        if (cwd / f).is_file():
            composites.append(score_path(cwd / f).composite)
    if not composites:
        return None, ""
    mean = sum(composites) / len(composites)
    return round(mean, 4), f"mean code-quality over {len(composites)} changed source file(s)"


def _doc_regressions(cwd: Path, baseline_ref: str, src_files: list[str]) -> list[str]:
    """Per changed source file, compare its docstrings against ``baseline_ref`` and
    collect any that lost material specificity (see ``doc_regression``). A file
    absent on baseline (all-new) has no baseline docstrings, so never regresses."""
    reasons: list[str] = []
    for rel in src_files:
        try:
            candidate = (cwd / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        base = subprocess.run(
            ["git", "show", f"{baseline_ref}:{rel}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        if base.returncode != 0:
            continue
        reasons += [f"{rel}::{r}" for r in doc_regressions(base.stdout, candidate)]
    return reasons


def _mean_assertion(cwd: Path, test_files: list[str]) -> tuple[float | None, str]:
    scores = []
    for f in test_files:
        if (cwd / f).is_file():
            s = score_assertions(cwd / f).score
            if s is not None:
                scores.append(s)
    if not scores:
        return None, ""
    mean = sum(scores) / len(scores)
    return round(mean, 4), f"mean assertion strength over {len(scores)} changed test file(s)"


def _red_green_evidence(
    cwd: Path, baseline_ref: str, src: list[str], tests: list[str], timeout: int
) -> TddEvidence:
    """Fill TddEvidence by running the candidate's changed tests against the
    baseline source: revert the changed source files to ``baseline_ref`` in the
    worktree (keeping the candidate's tests), run those tests (expect RED), then
    restore the candidate source. Green-on-candidate is the plain run.
    """
    if not tests:
        return TddEvidence()
    cand_rc, _ = run_test_selection(cwd, tests, timeout=timeout)
    base_rc: int | None = None
    if src:
        try:
            subprocess.run(
                ["git", "checkout", baseline_ref, "--", *src],
                cwd=str(cwd),
                check=True,
                capture_output=True,
                text=True,
            )
            base_rc, _ = run_test_selection(cwd, tests, timeout=timeout)
        except (OSError, subprocess.CalledProcessError):
            base_rc = None
        finally:
            subprocess.run(
                ["git", "checkout", "HEAD", "--", *src],
                cwd=str(cwd),
                capture_output=True,
                text=True,
            )
    return TddEvidence(
        changed_tests=tests, baseline_changed_rc=base_rc, candidate_changed_rc=cand_rc
    )


def _vacuous_test_reasons(src: list[str], tests: list[str], tdd: TddEvidence) -> list[str]:
    """A changed test that still passes with its accompanying source change
    reverted doesn't exercise that change — it's green for an unrelated reason
    (e.g. an earlier exception in the same call path masking that a new guard
    clause is never reached). Only fires when ``src`` is non-empty: a genuine
    characterization test (test-only diff, no source change at all) never
    reaches this — ``_red_green_evidence`` only computes ``baseline_changed_rc``
    when ``src`` is given, so it stays ``None`` for that valid case."""
    if src and tests and tdd.baseline_changed_rc == 0:
        return [
            f"{', '.join(tests)}: still pass(es) with {', '.join(src)} reverted to "
            "baseline — doesn't exercise this diff's source change"
        ]
    return []


def evaluate_candidate(
    candidate_dir: str | Path,
    changed_files: list[str],
    *,
    test_command: str,
    coverage_source: str = ".",
    coverage_pytest_args: str = "",
    baseline_coverage: float | None = None,
    baseline_ref: str | None = None,
    weights: FitnessWeights | None = None,
    tdd: TddEvidence | None = None,
    capability: tuple[float, float] | None = None,
    architecture_fit: object | None = None,
    feature_judge: tuple[float, str] | None = None,
    perf: tuple[float, float] | None = None,
    timeout: int = 900,
    regression_judge_fn: Callable[[str, str], tuple[float, str]] | None = None,
    target: str = "",
) -> Scorecard:
    """Run the local signals for a candidate and compose the Scorecard.

    ``feature_judge`` (score, rationale) and ``perf`` (baseline_s, candidate_s) are
    injected by callers that have a judge gateway / timing harness; without them
    those signals are simply absent (composite renormalises over present signals).

    ``regression_judge_fn`` (diff_text, target) -> (score, rationale) is called
    lazily, and ONLY if every other gate already passes: a candidate that's
    going to be rejected on tests/coverage/syntax/etc. never burns the extra
    LLM call, so this second-opinion safety net stays cheap in aggregate.
    """
    cwd = Path(candidate_dir)
    src = [f for f in changed_files if f.endswith(".py") and not _is_test(f)]
    tests = changed_test_paths(changed_files)
    all_py = [f for f in changed_files if f.endswith(".py")]

    tests_passed, test_reason = _run(test_command, cwd, timeout)
    cand_cov, missing = measure_coverage_detailed(
        cwd, source=coverage_source, pytest_args=coverage_pytest_args
    )
    cq, cq_detail = _mean_quality(cwd, src)
    astr, astr_detail = _mean_assertion(cwd, tests)
    if tdd is None:
        tdd = (
            _red_green_evidence(cwd, baseline_ref, src, tests, timeout)
            if baseline_ref
            else TddEvidence(changed_tests=tests)
        )
    net_new = count_net_new_tests(cwd, baseline_ref, tests) if (baseline_ref and tests) else 0
    doc_reasons = _doc_regressions(cwd, baseline_ref, src) if baseline_ref else []
    from maistro_rsi.spec_tracker import new_ac_coverage, proposed_specs

    new_acs = new_ac_coverage(cwd, baseline_ref, tests) if (baseline_ref and tests) else []
    new_specs = proposed_specs(cwd, changed_files)

    syntax_reasons = _syntax_check(cwd, all_py)
    valid_roots = _parse_test_roots(coverage_pytest_args)
    uncollectable = _uncollectable_tests(cwd, tests, valid_roots, src_files=src)
    new_src_lines = new_source_lines(cwd, baseline_ref, src) if (baseline_ref and src) else {}
    uncovered_new = uncovered_new_lines(new_src_lines, missing) if new_src_lines else {}
    vacuous_reasons = _vacuous_test_reasons(src, tests, tdd)

    inputs = FitnessInputs(
        tests_passed=tests_passed,
        test_reason=test_reason,
        baseline_coverage=baseline_coverage,
        candidate_coverage=cand_cov,
        code_quality_composite=cq,
        code_quality_detail=cq_detail,
        assertion_score=astr,
        assertion_detail=astr_detail,
        tdd=tdd,
        lint_gates=_lint_gates(cwd, src),
        capability=capability,
        architecture_fit=architecture_fit,
        net_new_tests=net_new,
        uncovered_new_source_lines=uncovered_new,
        doc_regression_reasons=doc_reasons,
        feature_judge=feature_judge,
        perf=perf,
        new_ac_ids=new_acs,
        proposed_spec_ids=new_specs,
        syntax_error_reasons=syntax_reasons,
        uncollectable_test_reasons=uncollectable,
        vacuous_test_reasons=vacuous_reasons,
    )
    prelim = compose_scorecard(inputs, weights)
    if not prelim.gates_passed:
        return prelim

    # Cost-layered after the cheap gates: mutation runs the changed tests once per
    # mutant, so a candidate already doomed on tests/coverage/syntax never pays
    # for it. Only meaningful when the diff added source lines AND changed tests
    # exist to catch mutations of them.
    if baseline_ref and new_src_lines and tests:
        inputs.mutation_probe = probe_diff_mutations(
            cwd, new_src_lines, tests, timeout=timeout, max_mutants=_MUTATION_MAX_MUTANTS
        )
        staged = compose_scorecard(inputs, weights)
        if not staged.gates_passed:
            return staged

    # Second-opinion LLM judge last (most expensive): only for candidates that
    # cleared every deterministic gate, including the mutation probe.
    if regression_judge_fn is not None and baseline_ref:
        try:
            diff = subprocess.run(
                ["git", "diff", baseline_ref],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=60,
            ).stdout
        except (OSError, subprocess.TimeoutExpired):
            diff = ""
        if diff.strip():
            inputs.regression_judge = regression_judge_fn(diff, target)

    return compose_scorecard(inputs, weights)
