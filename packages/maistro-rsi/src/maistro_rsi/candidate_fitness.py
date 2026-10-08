"""Compose the fitness signals into one promotion decision for the RSI loop.

Gathers the *local* signals for a baseline→candidate pair (tests, coverage,
code-quality, assertion-strength, lint/type/security gates) and builds the
transparent `Scorecard`: gates first (any veto ⇒ reject), then priority-weighted
scores (`FitnessWeights`). Capability (benchmarks) and architecture-fit (LLM
judge) are *injected* when a gateway is available, so this module stays
runnable offline. `compose_scorecard()` is pure and takes already-gathered
`FitnessInputs`; `evaluate_candidate()` runs the tools to produce them.

Since #392 the gates include `fail_first_evidence` (see `maistro_rsi.fail_first`):
a source-touching candidate must prove a changed test fails on the exact base
revision for the intended reason — or, under a declared refactor/doc contract,
show the explicit alternative evidence instead.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import os
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from maistro_evolve._candidate_env import candidate_env
from maistro_evolve.assertion_strength import score_assertions
from maistro_evolve.code_quality import ToolRunner, score_path
from maistro_evolve.coverage_gate import (
    coverage_gate,
    coverage_signal,
    measure_coverage_detailed,
    new_source_lines,
    uncovered_new_lines,
)
from maistro_evolve.doc_regression import doc_regressions
from maistro_evolve.improvement import ImprovementKind
from maistro_evolve.mutation_probe import MutationProbe, MutationRunner, probe_diff_mutations
from maistro_evolve.scenario_objective import (
    CorrectnessResult,
    ScenarioEvaluation,
    ScenarioObjective,
    evaluate_proven_scenarios,
)
from maistro_evolve.scorecard import (
    FitnessWeights,
    GateResult,
    GateState,
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
)
from maistro_rsi.contained_validation import (
    CONTAINED_PYTHON,
    ContainedEvaluation,
    ContainmentUnavailable,
)
from maistro_rsi.fail_first import (
    EvidenceContract,
    FailFirstEvidence,
    ProbeExecutor,
    collect_fail_first_evidence,
    fail_first_gate,
    resolve_contract,
)
from maistro_rsi.regression_judge import REJECT_BELOW, JudgeVerdict
from maistro_rsi.test_inventory import (
    InventoryResult,
    changed_config_files,
    collect_inventory,
    diff_inventory,
)

logger = structlog.get_logger()

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

# How many deleted node IDs the inventory gate's reason/detail/trace carry —
# enough to name every deletion in any realistic diff while keeping a hostile
# mass-deletion from bloating the promotion record. The full count always
# rides along as ``deleted_count``.
_DELETED_TRACE_CAP = 20

# How many mutated-oracle paths the evaluator-integrity gate's reason names —
# the full list always rides in the gate detail (and the promotion record),
# but the one-line reason should survive a hostile mass-edit of the oracle
# surface without bloating the scorecard explain().
_EVIDENCE_PATH_CAP = 5


def _is_test(path: str) -> bool:
    return any(h in path.replace("\\", "/") for h in _TEST_HINTS)


def _signal_routing(contained: ContainedEvaluation | None) -> _SignalRouting:
    """Where each executing signal runs (#614): the host process tree, or the
    one sandbox the evaluation opened. The routing decision is made ONCE, here,
    so `evaluate_candidate` reads as measurement intake and no signal can grow
    a host-side fallback of its own — the code-quality tool runner included:
    `score_path` shells out to ruff/bandit/mypy/pylint/radon, so those
    launches are bound to the sandbox too, never the host."""
    if contained is None:
        return _HOST_ROUTING
    return _SignalRouting(
        test_run=contained.run_argv,
        interpreter=CONTAINED_PYTHON,
        coverage_execute=contained.run_argv_streams,
        lint_execute=contained.run_argv_streams,
        quality_run_tool=_contained_quality_tool(contained),
        probe_executor=_ContainedProbeExecutor(contained),
        mutation_runner=contained,
        collect_execute=contained.run_argv_streams,
    )


@dataclass(frozen=True)
class _SignalRouting:
    """The per-signal execution channels (see `_signal_routing`). `None` means
    the host default for that signal; a contained evaluation fills every
    channel — nothing stays on the host."""

    test_run: Callable[[list[str]], tuple[int, str]] | None = None
    interpreter: str | None = None
    coverage_execute: Callable[[list[str]], tuple[int, str, str]] | None = None
    lint_execute: Callable[[list[str]], tuple[int, str, str]] | None = None
    probe_executor: ProbeExecutor | None = None
    mutation_runner: MutationRunner | None = None
    collect_execute: Callable[[list[str]], tuple[int, str, str]] | None = None
    # The runner code_quality's score_path uses to launch ruff/bandit/mypy/
    # pylint/radon. None = the host default (credential-boundary env); a
    # contained evaluation binds it to the sandbox (#614).
    quality_run_tool: ToolRunner | None = None


_HOST_ROUTING = _SignalRouting()


def _contained_quality_tool(contained: ContainedEvaluation) -> ToolRunner:
    """``maistro_evolve.code_quality``'s tool runner bound to the evaluation
    sandbox (#614). Same contract as the host default — ``(stdout,
    available)`` with available=False when the image lacks the tool — but the
    ruff/bandit/mypy/pylint/radon processes run inside the sandbox, under the
    image's own environment, and only their report streams cross back as
    data. Without this channel `score_path` would launch those tools on the
    host against candidate-authored files — exactly the leak containment
    exists to close."""

    def run(args: list[str], *, timeout: int = 120) -> tuple[str, bool]:
        # A non-zero exit is an ordinary result (bandit exits 1 on findings);
        # only a tool the image lacks is "missing", so its weight renormalises.
        _code, out, err = contained.run_argv_streams(
            [CONTAINED_PYTHON, "-m", *args], timeout=timeout
        )
        if "No module named" in err:
            return "", False
        return out, True

    return run


class _ContainedProbeExecutor:
    """The fail-first probe's steps, executed inside the evaluation sandbox (#614).

    The probe REPLAYS the candidate's changed tests against the baseline —
    candidate-authored code, so every probe run happens where the candidate's
    edits live, through the one sandbox the evaluation opened. Git plumbing
    (rev-parse, cat-file, checkout) and reads move recorded contents around;
    they execute nothing the candidate wrote, but they must run against the
    same tree the probes see, so they go through the sandbox too.
    """

    def __init__(self, contained: ContainedEvaluation) -> None:
        self._c = contained

    def rev_parse(self, ref: str) -> str:
        code, out = self._c.run_argv(["git", "rev-parse", ref], timeout=30)
        return out.strip() if code == 0 else ""

    def base_has(self, ref: str, rel: str) -> bool:
        code, _out = self._c.run_argv(["git", "cat-file", "-e", f"{ref}:{rel}"], timeout=30)
        return code == 0

    def checkout(self, ref: str, rel: str) -> None:
        self._c.run_argv(["git", "checkout", ref, "--", rel], timeout=60)

    def remove(self, rel: str) -> None:
        self._c.run_argv(["rm", "-f", rel], timeout=30)

    def probe(self, tests: list[str], timeout: int) -> tuple[int, str]:
        # The SAME selection argv run_test_selection composes on the host —
        # one shape, so a contained replay cannot drift from the host one.
        return self._c.run_argv(
            [
                CONTAINED_PYTHON,
                "-m",
                "pytest",
                "-q",
                "-p",
                "no:cacheprovider",
                "-rfE",
                *tests,
            ],
            timeout=timeout,
        )

    def read_text(self, rel: str) -> str:
        return self._c.read_file(rel)


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
    cwd: Path,
    test_files: list[str],
    valid_roots: list[str],
    src_files: list[str] | None = None,
    execute: Callable[[list[str]], tuple[int, str, str]] | None = None,
    interpreter: str | None = None,
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
            returncode = _collect_one(cwd, rel, execute=execute, interpreter=interpreter)
        except (OSError, subprocess.TimeoutExpired):
            reasons.append(f"{rel}: collection timed out or errored")
            continue
        if returncode != 0:
            # 0 = collected >=1 item; 5 = "no tests collected"; anything else =
            # a collection error (e.g. import failure) — all three mean this
            # file contributes nothing the harness will ever run.
            reasons.append(f"{rel}: pytest could not collect it (exit {returncode})")
    return reasons


def _collect_one(
    cwd: Path,
    rel: str,
    *,
    execute: Callable[[list[str]], tuple[int, str, str]] | None = None,
    interpreter: str | None = None,
) -> int:
    """One per-file ``pytest --collect-only`` exit code, for
    `_uncollectable_tests`. ``execute`` routes the import through the
    evaluation sandbox (#614); the host default is this process tree. Raises
    OSError/TimeoutExpired — the caller formats the refusal-shaped reason."""
    if execute is not None:
        rc, _out, _err = execute(
            [interpreter or sys.executable, "-m", "pytest", "--collect-only", "-q", rel]
        )
        return rc
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", rel],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode


@dataclass
class InventoryEvidence:
    """What the ``protected_test_inventory`` gate rules on (#306): the
    candidate's own collection result, the baseline's (when the caller has one
    — the loop computes it once per cycle), which changed files touch test
    configuration, and the governance override flag.

    The diff is derived (servable sets), not stored, so the evidence can never
    disagree with the results it was computed from."""

    candidate: InventoryResult = field(default_factory=InventoryResult)
    base: InventoryResult | None = None
    config_files_changed: list[str] = field(default_factory=list)
    allow_shrink: bool = False


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
    # Second-opinion LLM regression judge verdict — only ever populated after
    # every other gate already passed (see evaluate_candidate), so a doomed
    # candidate never burns the extra LLM call. Availability is kept separate
    # from score (#307): an UNAVAILABLE verdict (gateway error, timeout,
    # unparsable reply, oversized diff) carries score=None and FAILS the
    # regression-judge gate — fail closed, never a numeric fallback.
    regression_judge: JudgeVerdict | None = None
    # Diff-scoped mutation probe: do the candidate's own tests catch mutations of
    # the lines it added? Only populated after the cheap gates pass (mutation
    # runs the tests once per mutant). An unavailable probe (no changed tests, no
    # mutable new lines) adds no gate — never a false rejection.
    mutation_probe: MutationProbe | None = None
    # Protected test-inventory evidence (#306): ALWAYS gathered by
    # ``evaluate_candidate`` (collection failure on the candidate fails the gate
    # even without a baseline), diffed against ``base`` when one is given. None
    # only on compose-only calls that measured nothing — there is no measurement
    # to fail on, so the gate passes without verifying rather than inventing a
    # failure the caller never asked about.
    test_inventory: InventoryEvidence | None = None
    # Fail-first evidence contract (#392). ``changed_src``/``changed_tests``
    # are the diff's non-test/test .py files (the contract's shape input);
    # ``declared_kind`` is the slot's ImprovementKind value (the declaration
    # input; None/generic → BEHAVIOR for source-touching diffs).
    # ``fail_first`` is the collected probe record (None = never probed —
    # missing evidence under the behavior contract, fail closed).
    # ``baseline_quality_composite`` is the changed source's mean quality at
    # the base revision, the left side of the refactor contract's delta.
    changed_src: list[str] = field(default_factory=list)
    changed_tests: list[str] = field(default_factory=list)
    declared_kind: str | None = None
    fail_first: FailFirstEvidence | None = None
    baseline_quality_composite: float | None = None
    # Evaluator-oracle integrity (#109). ``evaluator_digest`` pins the SHA-256
    # of the score-defining artifacts (scorer, pinning tests, scenario corpora,
    # ratchet baselines, AC trees) at the TRUSTED base revision into the
    # scorecard provenance — every acceptance decision records exactly which
    # evaluator version judged it. ``evaluator_mutations`` lists the oracle
    # paths this candidate's own diff touched; non-empty vetoes (see
    # ``evaluator_integrity_gate``) because a candidate may not be judged by
    # the oracle it just changed. ``evaluator_mutation_authorized`` is the
    # explicit human governance override (LocalRsiConfig.
    # allow_evaluator_mutation, the #306 precedent): the gate then passes WITH
    # the mutation recorded, never silently.
    evaluator_digest: str | None = None
    evaluator_mutations: list[str] = field(default_factory=list)
    evaluator_mutation_authorized: bool = False
    # The weighted proven-scenario objective (M5-B, #108): the immutable,
    # versioned scenario ruler the loop evaluates candidates with, plus the
    # prior proven scores (best-ever per scenario, archive.proven_scenario_scores
    # semantics), the candidate's own scenario scores, and — optionally — an
    # explicit correctness verdict. When ``scenario_correctness`` is None the
    # ``tests_pass`` gate IS the correctness oracle (contract/acceptance tests
    # are the non-negotiable oracle); a caller with a broader oracle (security
    # suites, contract tests beyond the loop's own pytest run) injects it.
    # All four stay None when the loop has no scenario objective configured;
    # the scenario gate and signal are then simply absent.
    scenario_objective: ScenarioObjective | None = None
    scenario_proven_scores: dict[str, float] = field(default_factory=dict)
    scenario_candidate_scores: dict[str, float] = field(default_factory=dict)
    scenario_correctness: CorrectnessResult | None = None


def evaluator_integrity_gate(inp: FitnessInputs) -> GateResult:
    """The oracle-immunity veto (#109): a candidate may not edit the evaluator
    it is scored by.

    RSI may satisfy the oracle — the scorer, its pinning tests, the scenario
    corpus, the ratchet baselines, the AC trees — but may never change it in
    the diff that is judged against it: acceptance evidence produced by a
    mutated oracle is manufactured, not measured. Non-empty
    ``evaluator_mutations`` therefore vetoes. Under the explicit human
    governance override (``evaluator_mutation_authorized``) the gate passes
    WITH the mutation recorded in detail — the authorized path is visible,
    never silent — and the ``evaluator_digest`` provenance still names the
    trusted base definition every other candidate was scored against.
    """
    detail: dict[str, object] = {
        "evaluator_digest": inp.evaluator_digest,
        "mutations": list(inp.evaluator_mutations),
        "authorized": inp.evaluator_mutation_authorized,
    }
    if not inp.evaluator_mutations:
        reason = (
            f"oracle pinned at {inp.evaluator_digest[:12]}"
            if inp.evaluator_digest
            else "no baseline to diff against — unchecked"
        )
        return GateResult("evaluator_integrity", True, reason, detail=detail)
    if inp.evaluator_mutation_authorized:
        return GateResult(
            "evaluator_integrity",
            True,
            "AUTHORIZED oracle mutation — recorded for governance review: "
            + ", ".join(inp.evaluator_mutations[:_EVIDENCE_PATH_CAP]),
            detail=detail,
        )
    return GateResult(
        "evaluator_integrity",
        False,
        "candidate mutated the scoring oracle — evidence withheld (#109): "
        + ", ".join(inp.evaluator_mutations[:_EVIDENCE_PATH_CAP]),
        detail=detail,
    )


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


def protected_inventory_gate(ev: InventoryEvidence | None) -> GateResult:
    """The protected-inventory veto (#306): a candidate may not shrink the
    oracle that judges it. ALWAYS present in the Scorecard — unlike the
    conditional gates, this one is not optional evidence, it is the ratchet's
    own foundation (a loop whose candidates can delete the tests that catch
    them improves nothing, it just forgets).

    - FAIL when the candidate's collection failed (unverifiable inventory).
    - FAIL when the baseline's collection failed (no trustworthy base to
      diff against — fail closed, #307 doctrine).
    - FAIL when a test-config file changed AND anything shrank (deletions or
      a reduced unchanged core) — config change + shrink is presumed hiding,
      and the ``allow_shrink`` override does NOT cover it.
    - FAIL when protected IDs were deleted/renamed/disabled, unless
      ``allow_shrink`` (the explicit governance override) is set — in which
      case the gate passes with a WARNING and the deleted list recorded on
      the gate detail, so a shrink is never silent.
    - PASS otherwise, with the base/candidate counts and the (capped) deleted
      and added lists as evidence.
    """
    if ev is None:
        return GateResult("protected_test_inventory", True, "not measured (no inventory inputs)")
    if not ev.candidate.collection_ok:
        return GateResult(
            "protected_test_inventory",
            False,
            "inventory unverifiable: collection failed "
            f"({ev.candidate.collection_error or 'unknown cause'})",
            detail={"collection_ok": False},
        )
    if ev.base is None:
        return GateResult(
            "protected_test_inventory",
            True,
            "base inventory unavailable — candidate collected "
            f"{len(ev.candidate.servable)} servable test(s), nothing to diff",
            detail={"candidate": len(ev.candidate.servable)},
        )
    if not ev.base.collection_ok:
        return GateResult(
            "protected_test_inventory",
            False,
            "inventory unverifiable: base collection failed "
            f"({ev.base.collection_error or 'unknown cause'})",
            detail={"collection_ok": False},
        )
    diff = diff_inventory(ev.base, ev.candidate)
    detail: dict[str, object] = {
        "base": len(ev.base.servable),
        "candidate": len(ev.candidate.servable),
        "deleted": diff.deleted[:_DELETED_TRACE_CAP],
        "deleted_count": len(diff.deleted),
        "added": diff.added[:_DELETED_TRACE_CAP],
    }
    capped = ", ".join(diff.deleted[:_DELETED_TRACE_CAP]) or "(none)"
    if ev.config_files_changed and (diff.shrinks or diff.unchanged_count < len(ev.base.servable)):
        return GateResult(
            "protected_test_inventory",
            False,
            "test configuration changed while the inventory shrank (presumed "
            f"hiding): {', '.join(ev.config_files_changed)}; deleted: {capped}",
            detail={**detail, "config_files_changed": list(ev.config_files_changed)},
        )
    if diff.deleted and not ev.allow_shrink:
        return GateResult(
            "protected_test_inventory",
            False,
            f"{len(diff.deleted)} protected test(s) deleted/renamed/disabled: {capped}",
            detail=detail,
        )
    if diff.deleted and ev.allow_shrink:
        logger.warning(
            "rsi_test_inventory_shrink_allowed",
            deleted_count=len(diff.deleted),
            deleted=diff.deleted[:_DELETED_TRACE_CAP],
        )
        return GateResult(
            "protected_test_inventory",
            True,
            "GOVERNANCE OVERRIDE (allow_test_inventory_shrink): "
            f"{len(diff.deleted)} protected test(s) removed: {capped}",
            detail={**detail, "override": True},
        )
    return GateResult(
        "protected_test_inventory",
        True,
        f"{len(ev.base.servable)} -> {len(ev.candidate.servable)} protected tests "
        f"(+{len(diff.added)}, -{len(diff.deleted)})",
        detail=detail,
    )


def _conditional_gates(inp: FitnessInputs) -> list[GateResult]:
    """Gates that only exist when their (optional) evidence was gathered: the
    second-opinion LLM regression judge, and the diff-scoped mutation probe.
    Kept out of ``compose_scorecard`` so the assembly there stays flat."""
    gates: list[GateResult] = []
    if inp.regression_judge is not None:
        verdict = inp.regression_judge
        if verdict.status == "unavailable":
            # Fail closed (#307): an unavailable judge is a FAILED gate, and
            # its score stays None — never substituted with a passing number.
            gates.append(
                GateResult(
                    "no_flagged_regression",
                    False,
                    f"judge unavailable: {verdict.cause or 'unknown cause'} — fail closed",
                    detail={"score": verdict.score, "status": verdict.status},
                )
            )
        else:
            # A ruling: pass/reject behave exactly as before the verdict
            # refactor — a score below REJECT_BELOW ("reject") vetoes.
            score = verdict.score
            gates.append(
                GateResult(
                    "no_flagged_regression",
                    score is not None and score >= REJECT_BELOW,
                    verdict.rationale,
                    detail={"score": score, "status": verdict.status},
                )
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


def _scenario_objective_eval(inp: FitnessInputs) -> ScenarioEvaluation | None:
    """Evaluate the proven-scenario objective when the caller configured one.

    Pure: no measurement happens here, the caller gathered the scores. The
    default correctness oracle is the ``tests_pass`` gate itself (the
    contract/acceptance tests), so a loop that configured a scenario objective
    but has no broader oracle still gets the M5-B semantics — a red test suite
    scores zero on the scenario objective, no matter the aggregate.
    """
    if inp.scenario_objective is None:
        return None
    oracle = inp.scenario_correctness or CorrectnessResult(
        passed=inp.tests_passed,
        failures=() if inp.tests_passed else (inp.test_reason or "tests failed",),
    )
    return evaluate_proven_scenarios(
        inp.scenario_objective,
        inp.scenario_proven_scores,
        inp.scenario_candidate_scores,
        oracle,
    )


def _scenario_gate_items(scenario_eval: ScenarioEvaluation | None) -> list[GateResult]:
    """The proven-scenario veto (M5-B, #108) as a gate list: empty when no
    scenario objective was configured (absent evidence adds no gate), a
    single non-tradeable gate otherwise.

    The gate reads ``promotable`` — zeroed when the correctness oracle failed
    or any proven scenario regressed / was never evaluated — so no unrelated
    scalar gain (coverage, quality, even other scenarios' gains) can rescue
    the candidate. The full evaluation rides in ``detail`` and on
    ``Scorecard.scenario_objective``, so the correctness verdict and the
    scalar score are recorded separately for audit.
    """
    if scenario_eval is None:
        return []
    return [
        GateResult(
            "no_proven_scenario_regression",
            scenario_eval.promotable,
            scenario_eval.summary(),
            detail={
                "objective_version": scenario_eval.objective_version,
                "objective_digest": scenario_eval.objective_digest,
                "correctness_passed": scenario_eval.correctness_gate.passed,
                "correctness_failures": list(scenario_eval.correctness_gate.failures),
                "regressed": scenario_eval.regressed,
                "not_evaluated": scenario_eval.not_evaluated,
                "raw_weighted_score": scenario_eval.raw_weighted_score,
                "objective_score": scenario_eval.objective_score,
            },
        )
    ]


def _scenario_signal(scenario_eval: ScenarioEvaluation, w: FitnessWeights) -> SignalScore:
    """The scalar ranking contribution of the proven-scenario objective: the
    dominant term of the composite when present (M5-B #108 — keeping the
    proven scenarios green IS the objective the work signals serve). Only
    ranks candidates that already cleared the scenario gate."""
    return SignalScore(
        "proven_scenarios",
        MeasureKind.DERIVED,
        scenario_eval.objective_score,
        w.proven_scenarios,
        (
            "criticality-weighted proven scenarios under "
            f"{scenario_eval.objective_version} ({scenario_eval.objective_digest}): "
            f"score={scenario_eval.objective_score:.4f}; correctness="
            f"{'pass' if scenario_eval.correctness_gate.passed else 'FAIL'}"
        ),
        detail={
            "objective_version": scenario_eval.objective_version,
            "objective_digest": scenario_eval.objective_digest,
            "raw_weighted_score": scenario_eval.raw_weighted_score,
            "regressed": scenario_eval.regressed,
            "not_evaluated": scenario_eval.not_evaluated,
        },
    )


def _scenario_signal_items(
    scenario_eval: ScenarioEvaluation | None, w: FitnessWeights
) -> list[SignalScore]:
    """``_scenario_signal`` as a list: empty when no scenario objective was
    configured, so absent evidence adds no signal (and no branch lands in
    ``compose_scorecard``)."""
    if scenario_eval is None:
        return []
    return [_scenario_signal(scenario_eval, w)]


def compose_scorecard(inp: FitnessInputs, weights: FitnessWeights | None = None) -> Scorecard:
    """Pure: assemble gates + priority-weighted scores into a Scorecard."""
    w = weights or FitnessWeights()
    # The proven-scenario objective (M5-B, #108) is evaluated first: its gate
    # is a veto like any other, and its evaluation record rides on the
    # Scorecard so the correctness verdict and the scalar objective are
    # recorded separately from the work-signal composite.
    scenario_eval = _scenario_objective_eval(inp)
    gates = [
        # The oracle-immunity veto leads (#109): a candidate that mutated the
        # evaluator it is scored by is rejected on this gate before any other
        # signal is consulted, and its ``accepted`` can never come from the
        # evidence its own mutation manufactured.
        evaluator_integrity_gate(inp),
        GateResult(
            "tests_pass",
            inp.tests_passed,
            inp.test_reason or ("ok" if inp.tests_passed else "failed"),
        ),
        coverage_gate(inp.baseline_coverage, inp.candidate_coverage),
        protected_inventory_gate(inp.test_inventory),
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
        fail_first_gate(
            resolve_contract(inp.declared_kind, inp.changed_src, inp.changed_tests),
            inp.fail_first,
            quality_delta=(
                inp.code_quality_composite - inp.baseline_quality_composite
                if inp.code_quality_composite is not None
                and inp.baseline_quality_composite is not None
                else None
            ),
            net_new_tests=inp.net_new_tests,
            assertion_score=inp.assertion_score,
        ),
        *inp.lint_gates,
        *_scenario_gate_items(scenario_eval),
        *_conditional_gates(inp),
    ]
    scores: list[SignalScore] = [
        red_green_signal(inp.tdd, w.red_green),
        *_scenario_signal_items(scenario_eval, w),
    ]
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
    scorecard = Scorecard(
        gates=gates,
        scores=scores,
        scenario_objective=scenario_eval,
    )
    # Provenance (#109): the scorecard records the trusted evaluator digest it
    # was judged against, so an acceptance decision is replayable against the
    # exact oracle version that produced it.
    scorecard.evaluator_digest = inp.evaluator_digest
    return scorecard


def _run(
    cmd: str,
    cwd: Path,
    timeout: int = 900,
    argv: tuple[str, ...] = (),
    execute: Callable[[list[str]], tuple[int, str]] | None = None,
) -> tuple[bool, str]:
    """Run the candidate's test command, preferring an argument vector (#305).

    `argv` is what every non-terminal caller supplies: the Conductor resolves it
    from server-side policy, and running a vector means no shell parses it.
    `cmd` remains for the CLI, where an operator typed the command.

    Joining a vector into a string for the shell path would be the wrong
    fallback rather than a convenient one -- a token containing a space would
    re-split into two arguments, so the thing that ran would not be the thing
    the policy named.

    ``execute`` is the containment seam (#614): when given, the vector runs
    inside the evaluation sandbox and only its exit status and output come
    back. An empty vector with no host fallback is a refusal — see
    `ContainedEvaluation.run_argv`.

    Both host paths run behind the credential boundary (#78): the command
    imports and executes candidate code, so it gets the minimal base
    environment — never the harness's ambient credentials.
    """
    try:
        if execute is not None:
            if not argv:
                raise ContainmentUnavailable(
                    "container isolation requires an argument vector: there is no shell "
                    "inside the sandbox to hand a command string to, and running the "
                    "command on the host instead is the failure this exists to prevent"
                )
            code, output = execute(list(argv))
        elif argv:
            proc = subprocess.run(
                list(argv),
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=candidate_env(),
            )
            code, output = proc.returncode, proc.stdout + proc.stderr
        else:
            # shell=True: the CLI path, where `cmd` is what an operator typed.
            proc = subprocess.run(  # nosemgrep
                cmd,
                shell=True,  # nosemgrep
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=candidate_env(),
            )
            code, output = proc.returncode, proc.stdout + proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"test command errored: {exc}"
    tail = output.strip()[-200:]
    return (
        code == 0,
        f"exit {code}: {tail}" if tail else f"exit {code}",
    )


_LINT_TIMEOUT = 120


def _run_lint_tool(
    argv: list[str],
    cwd: Path,
    execute: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> tuple[subprocess.CompletedProcess[str] | None, str | None]:
    """Run a static tool, bounded by a timeout.

    Returns ``(proc, cause)``. ``proc`` is None when the tool did not produce
    a result; ``cause`` names why — ``"missing"`` (not installed / not
    importable in this runner), ``"timeout"`` (wedged past the bound) or
    ``"error"`` (could not even be spawned). Callers decide what a non-result
    means (#304): for a REQUIRED gate it is a blocking ``not_run``, never a
    silent omission.

    ``execute`` routes the same tool through the evaluation sandbox (#614):
    argv[0] is swapped for the interpreter the image provides (the host's
    `sys.executable` is a host path a container may not have), and the streams
    come back separated so report parsing cannot be corrupted by interleaved
    stderr. A sandbox that cannot establish or execute raises
    `ContainmentUnavailable` instead of returning a non-result — under
    containment a missing image is a refusal (#614 AC-3), not a ``not_run``
    verdict about the candidate; only the classifications above describe the
    tool's own failure to produce evidence, and they mean the same thing in
    both isolation modes (a missing analyzer blocks promotion rather than
    narrowing the evidence, #304)."""
    if execute is not None:
        rc, out, err = execute([CONTAINED_PYTHON, *argv[1:]])
        proc = subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)
    else:
        try:
            proc = subprocess.run(
                argv, cwd=str(cwd), capture_output=True, text=True, timeout=_LINT_TIMEOUT
            )
        except subprocess.TimeoutExpired:
            return None, "timeout"
        except OSError:
            return None, "error"
    if "No module named" in proc.stderr:
        return None, "missing"
    return proc, None


# The required analyzer gates (#304): (gate name, distribution name, argv
# prefix). Every one of these gates is named in the scorecard and in generated
# RSI PR bodies, so each must have an EXECUTED result tied to provenance — a
# runner missing any of them fails closed with a blocking ``not_run`` gate
# instead of silently narrowing the evidence. The runner image declares the
# same set (Dockerfile.rsi-runner); their parity is pinned by test.
REQUIRED_LINT_TOOL_SPEC: tuple[tuple[str, str, list[str]], ...] = (
    (
        "ruff_clean",
        "ruff",
        [sys.executable, "-m", "ruff", "check", "--output-format", "json"],
    ),
    (
        "mypy_clean",
        "mypy",
        [
            sys.executable,
            "-m",
            "mypy",
            "--ignore-missing-imports",
            "--no-error-summary",
            "--no-color-output",
            "--config-file",
            os.devnull,
        ],
    ),
    ("no_bandit_high", "bandit", [sys.executable, "-m", "bandit", "-f", "json", "-q"]),
)


def _tool_version(dist: str) -> str | None:
    """The installed distribution version of a gate's tool, or None when the
    dist is absent (which for a required tool surfaces as a not_run gate
    anyway). Read in-process: the gate argv runs under ``sys.executable``, so
    this interpreter's metadata IS the version that produced the result."""
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return None


def _candidate_sha(cwd: Path) -> str | None:
    """The candidate commit the gates are scoring — None outside a git
    worktree (compose-only contexts), where provenance honestly cannot pin a
    SHA rather than inventing one."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def _gate_provenance(
    cwd: Path,
    argv: list[str],
    dist: str,
    proc: subprocess.CompletedProcess[str] | None,
    *,
    contained: bool = False,
) -> dict[str, object]:
    """What actually executed behind a gate result (#304 AC-1): command,
    tool version, candidate SHA, exit status, and an output digest over both
    output streams — the minimum a reviewer needs to distinguish a measured
    pass from a guess.

    ``contained`` (#614): the tool ran inside the evaluation sandbox, so two
    host-side facts would describe executions that did NOT produce this
    result and are recorded as honest Nones — the interpreter's installed
    dist version is the host's, not the image's, and a host ``git
    rev-parse`` would pin the seed worktree, not the tree inside the sandbox
    the gates actually scored (no host process may run during a contained
    evaluation, #614 AC-5). The command, exit status and output digest still
    tie the result to the execution that produced it."""
    return {
        "command": list(argv),
        "tool_version": None if contained else _tool_version(dist),
        "candidate_sha": None if contained else _candidate_sha(cwd),
        "exit_status": proc.returncode if proc is not None else None,
        "output_digest": _output_digest(proc) if proc is not None else None,
    }


def _output_digest(proc: subprocess.CompletedProcess[str]) -> str:
    """SHA-256 over the analyzer's complete output — stdout and stderr — with
    each stream length-framed so no concatenation ambiguity can collide two
    different splits. Hashing stdout alone would leave stderr diagnostics and
    fatal errors unauthenticated: a run that crashed while printing nothing to
    stdout would carry the same digest as a genuinely silent clean one."""
    out = (proc.stdout or "").encode()
    err = (proc.stderr or "").encode()
    framed = b"stdout:%d:" % len(out) + out + b"stderr:%d:" % len(err) + err
    return "sha256:" + hashlib.sha256(framed).hexdigest()


def _not_run_gate(name: str, dist: str, cause: str, provenance: dict[str, object]) -> GateResult:
    return GateResult(
        name,
        False,
        f"{dist} did not run ({cause}) — required gate not_run; "
        "a missing analyzer blocks promotion rather than narrowing the evidence",
        detail={"cause": cause, **provenance},
        state=GateState.NOT_RUN,
    )


def _unreadable_output_gate(name: str, tool: str, provenance: dict[str, object]) -> GateResult:
    """An executed tool whose stdout cannot be parsed, recorded FAILED —
    unreadable evidence is not a green result."""
    return GateResult(
        name,
        False,
        f"unreadable {tool} output — recorded as failed, not clean",
        detail=provenance,
        state=GateState.FAILED,
    )


def _ruff_clean_gate(
    proc: subprocess.CompletedProcess[str], provenance: dict[str, object]
) -> GateResult:
    """Gate on the count of ruff findings in the JSON report."""
    try:
        n = len(json.loads(proc.stdout or "[]"))
    except json.JSONDecodeError:
        return _unreadable_output_gate("ruff_clean", "ruff", provenance)
    return GateResult(
        "ruff_clean",
        n == 0,
        f"{n} lint violation(s)",
        detail=provenance,
        state=GateState.PASSED if n == 0 else GateState.FAILED,
    )


def _mypy_clean_gate(
    proc: subprocess.CompletedProcess[str], provenance: dict[str, object]
) -> GateResult:
    """Gate on the count of ``: error:`` lines in mypy's output."""
    errs = sum(1 for ln in proc.stdout.splitlines() if ": error:" in ln)
    return GateResult(
        "mypy_clean",
        errs == 0,
        f"{errs} type error(s)",
        detail=provenance,
        state=GateState.PASSED if errs == 0 else GateState.FAILED,
    )


def _bandit_high_gate(
    proc: subprocess.CompletedProcess[str], provenance: dict[str, object]
) -> GateResult:
    """Gate on the count of HIGH-severity bandit findings."""
    try:
        results = json.loads(proc.stdout or "{}").get("results", [])
    except json.JSONDecodeError:
        return _unreadable_output_gate("no_bandit_high", "bandit", provenance)
    high = [r for r in results if r.get("issue_severity") == "HIGH"]
    return GateResult(
        "no_bandit_high",
        len(high) == 0,
        f"{len(high)} HIGH-severity finding(s)",
        detail=provenance,
        state=GateState.PASSED if len(high) == 0 else GateState.FAILED,
    )


# Per-tool result builders for the executed-and-well-formed path, keyed by
# gate name (the same names REQUIRED_LINT_TOOL_SPEC carries).
_LINT_GATE_PARSERS: dict[
    str, Callable[[subprocess.CompletedProcess[str], dict[str, object]], GateResult]
] = {
    "ruff_clean": _ruff_clean_gate,
    "mypy_clean": _mypy_clean_gate,
    "no_bandit_high": _bandit_high_gate,
}


def _lint_gate_result(
    name: str,
    dist: str,
    proc: subprocess.CompletedProcess[str] | None,
    cause: str | None,
    provenance: dict[str, object],
) -> GateResult:
    """Classify one analyzer run into its gate result: ``not_run`` when the
    tool never produced a result or died mid-execution, else the tool's
    parser decides ``passed`` vs ``failed``.

    All three are REQUIRED gates: a tool that is missing, wedged, or times
    out yields a blocking ``not_run`` gate (``passed=False`` vetoes the
    candidate) that names the cause — never a silent omission a downstream
    PR body could render as a pass. Output that cannot be parsed is a FAILED
    gate, not a clean one. Nor is an execution failure: exits 0 (clean) and
    1 (findings) are the only analyzer-evidence codes — a tool that starts
    and then dies with a usage/configuration/internal exit (2) yields a
    blocking ``not_run`` gate, because empty stdout from a broken analyzer
    is not evidence of clean code."""
    if proc is None:
        return _not_run_gate(name, dist, cause or "error", provenance)
    if proc.returncode not in (0, 1):
        # A findings exit is 0 or 1; anything else means the analyzer
        # never evaluated the files. Reject before parsing so empty
        # stdout (ruff "[]", mypy zero errors, bandit "{}") from a
        # broken run cannot masquerade as a clean result.
        return _not_run_gate(name, dist, f"execution error (exit {proc.returncode})", provenance)
    return _LINT_GATE_PARSERS[name](proc, provenance)


def _lint_gates(
    cwd: Path,
    src_files: list[str],
    execute: Callable[[list[str]], tuple[int, str, str]] | None = None,
) -> list[GateResult]:
    """ruff / mypy / bandit-HIGH on the changed source files (#304).

    An executed gate carries its provenance (command, tool version,
    candidate SHA, exit status, output digest) and one of exactly two
    states: ``passed`` or ``failed``; see ``_lint_gate_result`` for how a
    non-execution is classified.

    ``execute`` (the contained evaluation, #614) runs each tool inside the
    sandbox instead of on the host — the same REQUIRED gate set in both
    isolation modes, so containment cannot silently narrow the evidence.
    The recorded provenance still names the execution that produced the
    result: the sandbox receives its own interpreter name rather than a host
    path, and the tool version is an honest None — this interpreter's
    metadata is the host's, not the image's that actually ran (#614 AC-5)."""
    if not src_files:
        return []
    gates: list[GateResult] = []
    for name, dist, argv in REQUIRED_LINT_TOOL_SPEC:
        full_argv = [*argv, *src_files]
        if execute is not None:
            proc, cause = _run_lint_tool(full_argv, cwd, execute)
            provenance = _gate_provenance(
                cwd, [CONTAINED_PYTHON, *full_argv[1:]], dist, proc, contained=True
            )
        else:
            proc, cause = _run_lint_tool(full_argv, cwd)
            provenance = _gate_provenance(cwd, full_argv, dist, proc)
        gates.append(_lint_gate_result(name, dist, proc, cause, provenance))
    return gates


def _mean_quality(
    cwd: Path, src_files: list[str], run_tool: ToolRunner | None = None
) -> tuple[float | None, str]:
    composites = []
    for f in src_files:
        if (cwd / f).is_file():
            composites.append(score_path(cwd / f, run_tool=run_tool).composite)
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


def _baseline_quality_at_base(
    cwd: Path, baseline_ref: str | None, src_files: list[str], contract: EvidenceContract
) -> float | None:
    """The refactor contract's left side (#392): the changed source's mean
    quality at the base revision. Only a declared REFACTOR contract measures
    it — the behavior contract's delta is fail-first evidence, not quality —
    and with no baseline there is nothing to diff against (fail closed:
    ``None``). Named so ``evaluate_candidate`` reads as measurement intake
    rather than contract arithmetic."""
    if contract is not EvidenceContract.REFACTOR or not baseline_ref:
        return None
    return _mean_quality_at_base(cwd, baseline_ref, src_files)


def _mean_quality_at_base(cwd: Path, baseline_ref: str, src_files: list[str]) -> float | None:
    """Mean code-quality composite of the changed source files AS THEY WERE on
    ``baseline_ref`` — the left side of the refactor contract's quality delta.
    Files absent on baseline contribute nothing (a new file has no baseline
    quality to improve upon). Returns None when no baseline version of any
    changed file could be read: the refactor contract then fails closed.

    Deliberately host-side even under containment (#614): the analyzed bytes
    are the pinned BASE revision's, written by the harness into a bare temp
    directory. Nothing candidate-authored is parsed there and no candidate
    config file can ride along, so the tools only ever read harness-written
    data — and they run behind the credential-boundary env, never ambient
    inheritance."""
    composites: list[float] = []
    for i, rel in enumerate(src_files):
        base = subprocess.run(
            ["git", "show", f"{baseline_ref}:{rel}"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if base.returncode != 0 or not base.stdout.strip():
            continue
        with tempfile.TemporaryDirectory() as td:
            snap = Path(td) / f"base_{i}_{Path(rel).name}"
            snap.write_text(base.stdout, encoding="utf-8")
            composites.append(score_path(snap).composite)
    if not composites:
        return None
    return round(sum(composites) / len(composites), 4)


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


def _resolve_evaluator_evidence(
    cwd: Path,
    changed_files: list[str],
    *,
    baseline_ref: str | None,
    declared: str | None,
    evaluator_digest: str | None,
    evaluator_mutations: list[str] | None,
    evaluator_mutation_authorized: bool,
    weights: FitnessWeights | None,
) -> tuple[str | None, list[str], Scorecard | None]:
    """The #109 preamble: resolve oracle-integrity evidence and, when a
    non-authorized mutation is found, the scorecard that withholds ALL other
    evidence (returned third). A helper so the ordering contract — integrity
    resolved BEFORE the oracle runs — reads as one named step."""
    if evaluator_mutations is None and baseline_ref:
        from maistro_rsi.evaluator_oracle import oracle_digest, oracle_mutations

        evaluator_mutations = oracle_mutations(cwd, baseline_ref, changed_files)
        evaluator_digest = evaluator_digest or oracle_digest(cwd, baseline_ref)
    mutations = list(evaluator_mutations or [])
    withheld: Scorecard | None = None
    if mutations and not evaluator_mutation_authorized:
        withheld = compose_scorecard(
            FitnessInputs(
                tests_passed=False,
                test_reason="withheld: candidate mutated the scoring oracle (#109)",
                changed_src=[f for f in changed_files if f.endswith(".py") and not _is_test(f)],
                changed_tests=changed_test_paths(changed_files),
                declared_kind=declared,
                evaluator_digest=evaluator_digest,
                evaluator_mutations=mutations,
                evaluator_mutation_authorized=False,
            ),
            weights,
        )
    return evaluator_digest, mutations, withheld


def _resolve_tdd_evidence(
    cwd: Path,
    *,
    baseline_ref: str | None,
    src: list[str],
    tests: list[str],
    timeout: int,
    config_changed: list[str],
    tdd: TddEvidence | None,
    executor: ProbeExecutor | None = None,
) -> tuple[TddEvidence, FailFirstEvidence | None]:
    """The #392 evidence contract's collection step: when the caller supplies
    no ``tdd`` view, probe the base revision for fail-first evidence (a source
    change owes a changed test that is red on the exact base for the intended
    reason). Returns ``(tdd, fail_first)`` — the probe record is None when no
    probe ran, which the fail-first gate treats as missing evidence (fail
    closed) under the behavior contract. ``executor`` routes the probe's test
    runs (#614): the replay imports candidate test code, so a contained
    evaluation runs it inside the sandbox."""
    if tdd is not None:
        return tdd, None
    if not (baseline_ref and tests):
        return TddEvidence(changed_tests=tests), None
    fail_first = collect_fail_first_evidence(
        cwd,
        baseline_ref,
        src,
        tests,
        timeout,
        config_files_changed=config_changed,
        executor=executor,
    )
    if fail_first is None:
        return TddEvidence(changed_tests=tests), None
    return fail_first.tdd_view(tests), fail_first


def _stage_mutation_probe(
    inputs: FitnessInputs,
    cwd: Path,
    baseline_ref: str | None,
    new_src_lines: dict[str, set[int]],
    tests: list[str],
    timeout: int,
    weights: FitnessWeights | None,
    runner: MutationRunner | None = None,
) -> Scorecard | None:
    """Run the diff-mutation probe once the cheap gates cleared.

    Cost-layered after the cheap gates: mutation runs the changed tests once
    per mutant, so a candidate already doomed on tests/coverage/syntax never
    pays for it. Only meaningful when the diff added source lines AND changed
    tests exist to catch mutations of them. ``runner`` (#614) writes each
    mutant into — and reruns the tests inside — the evaluation sandbox.

    Returns the staged, gate-failing Scorecard when the probe vetoes the
    candidate, else ``None`` (probe absent or passed).
    """
    if not (baseline_ref and new_src_lines and tests):
        return None
    inputs.mutation_probe = probe_diff_mutations(
        cwd, new_src_lines, tests, timeout=timeout, max_mutants=_MUTATION_MAX_MUTANTS, runner=runner
    )
    staged = compose_scorecard(inputs, weights)
    if staged.gates_passed:
        return None
    return staged


def _attach_regression_judge(
    inputs: FitnessInputs,
    regression_judge_fn: Callable[[str, str], JudgeVerdict] | None,
    cwd: Path,
    baseline_ref: str | None,
    target: str,
) -> None:
    """Attach the second-opinion LLM judge, last and only if it can rule.

    Only for candidates that cleared every deterministic gate, including the
    mutation probe. An unavailable ``git diff`` is treated as no diff (the
    judge simply stays absent); a produced diff is judged verbatim.
    """
    if regression_judge_fn is None or not baseline_ref:
        return
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
    regression_judge_fn: Callable[[str, str], JudgeVerdict] | None = None,
    target: str = "",
    test_argv: tuple[str, ...] = (),
    baseline_inventory: InventoryResult | None = None,
    allow_test_inventory_shrink: bool = False,
    declared_kind: ImprovementKind | str | None = None,
    evaluator_digest: str | None = None,
    evaluator_mutations: list[str] | None = None,
    evaluator_mutation_authorized: bool = False,
    scenario_objective: ScenarioObjective | None = None,
    scenario_proven_scores: dict[str, float] | None = None,
    scenario_candidate_scores: dict[str, float] | None = None,
    scenario_correctness: CorrectnessResult | None = None,
    contained: ContainedEvaluation | None = None,
) -> Scorecard:
    """Run the local signals for a candidate and compose the Scorecard.

    ``feature_judge`` (score, rationale) and ``perf`` (baseline_s, candidate_s) are
    injected by callers that have a judge gateway / timing harness; without them
    those signals are simply absent (composite renormalises over present signals).

    ``baseline_inventory`` (see test_inventory.collect_inventory) is the base
    revision's collected test inventory — the loop computes it once per cycle
    against the baseline worktree. Without it the candidate is still collection-
    checked (a broken collection fails the gate on its own), just not diffed.
    ``allow_test_inventory_shrink`` is the explicit governance override (#306):
    when True, deletions pass the gate with a WARNING and are recorded, never
    silently absorbed.

    The four ``scenario_*`` arguments are the M5-B proven-scenario evidence
    (#108), gathered by the caller (the loop runs the scenario suite and reads
    the archive's proven scores — no measurement happens here). Passing an
    objective enables the ``no_proven_scenario_regression`` veto and the
    dominant ``proven_scenarios`` signal; omitting it leaves both absent
    (identical semantics to the ``FitnessInputs`` fields, never a false
    rejection or a silent zero).

    ``regression_judge_fn`` (diff_text, target) -> JudgeVerdict is called
    lazily, and ONLY if every other gate already passes: a candidate that's
    going to be rejected on tests/coverage/syntax/etc. never burns the extra
    LLM call, so this second-opinion safety net stays cheap in aggregate.
    When it does run, an unavailable verdict fails the candidate (fail
    closed, #307) — the score of a judge that never ruled is None, not a
    number.

    ``contained`` is the evaluation sandbox (#614): when given, every signal
    that executes candidate code — the test run, the coverage run, the
    red/green replay, the mutation probe's reruns, per-file collection and
    the static tools — runs inside it, and results come back as data (exit
    codes, parsed reports, file contents read on demand). No signal falls
    back to the host, and a sandbox that cannot establish or execute raises
    `ContainmentUnavailable` instead of producing a Scorecard: "the tests
    failed" and "the tests could not be run safely" are different facts.
    One sandbox serves the whole evaluation — a per-signal container would
    multiply a multi-cycle run's cost by the number of gates.

    Evaluator-oracle integrity (#109): with a ``baseline_ref`` and no explicit
    ``evaluator_mutations``, the candidate's diff is checked against the
    score-defining artifact surface BEFORE any oracle run — a candidate that
    mutated ``candidate_fitness.py``, its pinning tests, a ratchet baseline or
    the AC tree is rejected (or, under ``evaluator_mutation_authorized``,
    scored WITH the mutation recorded) without its modified oracle ever
    producing acceptance evidence. ``evaluator_digest`` pins the trusted base
    oracle's SHA-256 into the scorecard provenance; when not supplied it is
    computed from the same baseline revision, so every scorecard names the
    evaluator version that judged it.
    """
    cwd = Path(candidate_dir)
    # The containment routing decision (#614), made once: when a sandbox was
    # handed in, every executing signal below routes through it and none may
    # fall back to the host. The analysis that only PARSES candidate bytes
    # (syntax check, assertion scores, doc regression, inventory diffing)
    # stays a host-side computation over data either way; the code-quality
    # tools shell out, so their runner crosses the boundary too
    # (``routing.quality_run_tool``).
    routing = _signal_routing(contained)
    run_tests = routing.test_run
    src = [f for f in changed_files if f.endswith(".py") and not _is_test(f)]
    tests = changed_test_paths(changed_files)
    all_py = [f for f in changed_files if f.endswith(".py")]
    # The declared contract (#392): the slot's ImprovementKind decides whether
    # source-touching work owes fail-first evidence (default) or the refactor
    # alternative (declared refactor/doc polish).
    declared = declared_kind.value if isinstance(declared_kind, ImprovementKind) else declared_kind
    contract = resolve_contract(declared, src, tests)
    baseline_quality = _baseline_quality_at_base(cwd, baseline_ref, src, contract)
    # Test-config surfaces touched by this diff — the shared taint signal for
    # the protected-inventory gate (#306) and the fail-first contract (#392):
    # a config edit can both hide inventory shrinkage and manufacture a red.
    config_changed = changed_config_files(changed_files)

    # Oracle immunity (#109) — enforced BEFORE any oracle run. Unless the
    # caller already resolved the integrity evidence, derive it from the
    # trusted baseline revision. A candidate that mutated the evaluator oracle
    # is rejected WITHOUT executing the mutated tree: its modified oracle must
    # not contribute acceptance evidence. The digest still pins the trusted
    # base definition into the scorecard provenance either way.
    evaluator_digest, evaluator_mutations, withheld = _resolve_evaluator_evidence(
        cwd,
        changed_files,
        baseline_ref=baseline_ref,
        declared=declared,
        evaluator_digest=evaluator_digest,
        evaluator_mutations=evaluator_mutations,
        evaluator_mutation_authorized=evaluator_mutation_authorized,
        weights=weights,
    )
    if withheld is not None:
        return withheld

    tests_passed, test_reason = _run(test_command, cwd, timeout, argv=test_argv, execute=run_tests)
    cand_cov, missing = measure_coverage_detailed(
        cwd,
        source=coverage_source,
        pytest_args=coverage_pytest_args,
        interpreter=routing.interpreter,
        execute=routing.coverage_execute,
    )
    cq, cq_detail = _mean_quality(cwd, src, run_tool=routing.quality_run_tool)
    astr, astr_detail = _mean_assertion(cwd, tests)
    tdd, fail_first = _resolve_tdd_evidence(
        cwd,
        baseline_ref=baseline_ref,
        src=src,
        tests=tests,
        timeout=timeout,
        config_changed=config_changed,
        tdd=tdd,
        executor=routing.probe_executor,
    )
    net_new = count_net_new_tests(cwd, baseline_ref, tests) if (baseline_ref and tests) else 0
    doc_reasons = _doc_regressions(cwd, baseline_ref, src) if baseline_ref else []
    from maistro_rsi.spec_tracker import new_ac_coverage, proposed_specs

    new_acs = new_ac_coverage(cwd, baseline_ref, tests) if (baseline_ref and tests) else []
    new_specs = proposed_specs(cwd, changed_files)

    syntax_reasons = _syntax_check(cwd, all_py)
    valid_roots = _parse_test_roots(coverage_pytest_args)
    uncollectable = _uncollectable_tests(
        cwd,
        tests,
        valid_roots,
        src_files=src,
        execute=routing.collect_execute,
        interpreter=routing.interpreter,
    )
    new_src_lines = new_source_lines(cwd, baseline_ref, src) if (baseline_ref and src) else {}
    uncovered_new = uncovered_new_lines(new_src_lines, missing) if new_src_lines else {}
    vacuous_reasons = _vacuous_test_reasons(src, tests, tdd)
    # Protected test inventory (#306): always collected for the candidate —
    # a broken collection is itself disqualifying — and diffed against the
    # caller-supplied baseline inventory when one exists. Collection is cheap
    # (no test execution) and runs before the scorecard is first composed, so
    # a shrinking candidate is vetoed in ``prelim`` and never pays for the
    # mutation probe or the LLM judge.
    inventory_evidence = InventoryEvidence(
        candidate=collect_inventory(
            cwd,
            shlex.split(coverage_pytest_args),
            execute=routing.collect_execute,
            interpreter=routing.interpreter,
        ),
        base=baseline_inventory,
        config_files_changed=config_changed,
        allow_shrink=allow_test_inventory_shrink,
    )

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
        lint_gates=_lint_gates(cwd, src, routing.lint_execute),
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
        test_inventory=inventory_evidence,
        changed_src=src,
        changed_tests=tests,
        declared_kind=declared,
        fail_first=fail_first,
        baseline_quality_composite=baseline_quality,
        evaluator_digest=evaluator_digest,
        evaluator_mutations=evaluator_mutations,
        evaluator_mutation_authorized=evaluator_mutation_authorized,
        scenario_objective=scenario_objective,
        scenario_proven_scores=scenario_proven_scores or {},
        scenario_candidate_scores=scenario_candidate_scores or {},
        scenario_correctness=scenario_correctness,
    )
    prelim = compose_scorecard(inputs, weights)
    if not prelim.gates_passed:
        return prelim

    staged = _stage_mutation_probe(
        inputs,
        cwd,
        baseline_ref,
        new_src_lines,
        tests,
        timeout,
        weights,
        routing.mutation_runner,
    )
    if staged is not None:
        return staged

    # Second-opinion LLM judge last (most expensive): only for candidates that
    # cleared every deterministic gate, including the mutation probe.
    _attach_regression_judge(inputs, regression_judge_fn, cwd, baseline_ref, target)

    return compose_scorecard(inputs, weights)
