"""M8-A research harness — CrossHair symbolic execution over pure Python invariants.

Issue #890 (leaf of epic #880, initiative #879). Hypothesis under study: CrossHair
can find counterexamples in deterministic, side-effect-light Python logic without
translation to another language, making it valuable for small MAIstro policy and
transformation functions.

This module is a RESEARCH ARTIFACT, not product code. Unlike the sibling TLA+
leaf (#918), whose toolchain did not exist in deterministic CI, the tool under
study here is real and reproducible: ``crosshair-tool`` is declared in the dev
extra, and the prototype below runs the actual ``crosshair check`` engine as a
subprocess against REAL maistro seams — scope/permission expansion
(``maistro.auth._types.expand_scopes``), the single daily-budget formula
(``maistro.types.model.normalized_daily_budget``, #1205), and the sequence-aware
policy rules (``maistro.policy.rules``). Nothing here reads or writes a Goal,
Run, NodeRun, routing decision, or Warden/HITL control; CrossHair runs with its
default side-effect audit (wall-clock reads in ``cycle_key`` are observed, not
unblocked), and every result is advisory evidence for the research record.

Headline experimental results this module pins (full record and the INCUBATE
disposition live in ``docs/research/890-crosshair-symbolic-execution-pure-invariants.md``):

- Two boundary mutants that the entire existing suite misses (the hand-written
  policy suite AND the Hypothesis formal models) are caught by CrossHair with
  exact minimal counterexamples: ``BudgetRule`` ``>`` → ``>=`` (denies at the
  boundary) and ``normalized_daily_budget`` ``/30.0`` → ``/31.0`` (rewrites the
  documented 30-day flattening).
- One documented deterministic false positive (untyped-int input at the
  float-range boundary): CrossHair reports a counterexample whose printed input
  satisfies the contract when replayed concretely. The replay-triage step below
  pins that class so it cannot silently become trust.
- One honest miss (``ForbiddenPairRule`` self-pair mutant): the discriminating
  input region needs a single-entry ``counts_by_kind`` dict, which CrossHair
  cannot construct within budget — the applicability boundary, recorded.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTE_PATH = REPO_ROOT / "docs" / "research" / "890-crosshair-symbolic-execution-pure-invariants.md"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: CI-profile contract set (6 of the 17 documented contracts). Chosen to keep
#: the subprocess under ~25s wall while pinning one contract per real seam.
#: Float-heavy scarcity contracts stay in the research note's out-of-CI set.
CONTRACT_PROTOTYPE_SOURCE = '''\
"""M8-A10 (#890) CrossHair prototype: contracts over real maistro pure seams."""
from maistro.auth._types import CATEGORY_SCOPES, Scope, ScopeCategory, expand_scopes
from maistro.policy.rules import BudgetRule
from maistro.policy.types import Action, SequenceState
from maistro.types.model import (
    SUPPORTED_BILLING_CYCLES,
    UnknownBillingCycleError,
    normalized_daily_budget,
)

_SCOPE_VALUES = [s.value for s in Scope]
_CATEGORY_VALUES = [c.value for c in ScopeCategory]


def expand_category_wildcard_is_complete(cat: str) -> frozenset:
    """pre: cat in _CATEGORY_VALUES
    post: __return__ == CATEGORY_SCOPES[ScopeCategory(cat)]
    """
    return expand_scopes([cat + ":*"])


def expand_superuser_includes_every_category(cat: str) -> frozenset:
    """pre: cat in _CATEGORY_VALUES
    post: CATEGORY_SCOPES[ScopeCategory(cat)] <= __return__
    """
    return expand_scopes(["*:*"])


def daily_budget_is_identity(free_tokens: int) -> float:
    """pre: free_tokens >= 0
    post: __return__ == float(free_tokens)
    """
    return normalized_daily_budget(free_tokens, "daily")


def monthly_budget_is_thirtieth(free_tokens: int) -> float:
    """pre: free_tokens >= 0
    post: __return__ == float(free_tokens) / 30.0
    """
    return normalized_daily_budget(free_tokens, "monthly")


def unknown_cycle_raises(cycle: str) -> float:
    """pre: cycle not in SUPPORTED_BILLING_CYCLES
    raises: UnknownBillingCycleError
    """
    return normalized_daily_budget(1, cycle)


def budget_rule_iff(rule: BudgetRule, action: Action, prospective: SequenceState):
    """pre: rule.dimension == "tokens"
    post: (__return__ is None) == (not (float(prospective.tokens) > rule.limit))
    """
    return rule.evaluate(action, prospective)
'''

#: Deliberately broken postcondition. CrossHair must report the exact minimal
#: counterexample on stderr-style stdout, or the tool is not really analyzing.
NEGATIVE_CONTROL_SOURCE = '''\
def inc(x: int) -> int:
    """pre: x > 0
    post: __return__ > x + 1
    """
    return x + 1
'''

#: The documented deterministic false positive: CrossHair 0.0.111 reports this
#: exact function with a counterexample at the int→float conversion boundary
#: whose printed input satisfies the postcondition when replayed concretely.
FALSE_POSITIVE_SOURCE = '''\
from maistro.types.model import SUPPORTED_BILLING_CYCLES, normalized_daily_budget


def known_cycle_never_raises(cycle: str, free_tokens: int) -> float:
    """pre: cycle in SUPPORTED_BILLING_CYCLES and free_tokens >= 0
    post: __return__ >= 0.0
    """
    return normalized_daily_budget(free_tokens, cycle)
'''

#: The counterexample input CrossHair prints (int at the float-range boundary).
FALSE_POSITIVE_INPUT = 179769313486231570814527423731704356798070567525844996598917476803157260780028538760589558632766878171540458953514382464234321326889464182768467546703537516986049910576551282076245490090389328944075868508455133942304583236903222948165808559332123348274797826204144723168738177180919299881250404026184124858369

#: Modules scanned for the applicability map (E1). Each imports cleanly under
#: CrossHair but contains no checkable functions: imports are not the barrier,
#: contract authoring is. Includes one stateful/DB-coupled module and one with a
#: heavy import web to show the boundary does not move for those reasons either.
APPLICABILITY_MODULES = [
    "packages/maistro-core/src/maistro/policy/rules.py",
    "packages/maistro-core/src/maistro/types/model.py",
    "packages/maistro-core/src/maistro/auth/_types.py",
    "packages/maistro-core/src/maistro/quota/billing.py",
    "packages/maistro-core/src/maistro/router/scarcity.py",
    "packages/maistro-core/src/maistro/capabilities/invocation.py",
    "packages/maistro-core/src/maistro/orchestrator/master.py",
]


def _run_crosshair(
    source: str, tmp_path: Path, name: str, *extra: str
) -> subprocess.CompletedProcess[str]:
    module = tmp_path / name
    module.write_text(source)
    return subprocess.run(
        [sys.executable, "-m", "crosshair", "check", str(module), *extra],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=600,
        check=False,
    )


def test_research_note_records_incubate_disposition() -> None:
    """The leaf's terminal disposition and evidence record exist and are honest."""
    text = NOTE_PATH.read_text()
    assert NOTE_PATH.exists()
    assert "## Disposition" in text
    assert "INCUBATE" in text
    # The three evidence classes the module pins must be in the record.
    assert "false positive" in text.lower()
    assert "symbolic" in text.lower()
    assert "/30.0" in text


def test_crosshair_tool_is_declared_and_present() -> None:
    """The research dependency is declared in the dev group and importable.

    Also pins the dependency hygiene fix: the unrelated legacy PyPI
    ``crosshair`` package (0.1.0.dev11, paramiko-era) must stay out — its
    distribution ships a same-named ``crosshair`` package that shadows
    crosshair-tool's own.
    """
    config = tomllib.loads(PYPROJECT.read_text())
    dev_group = config["dependency-groups"]["dev"]
    assert any(dep.startswith("crosshair-tool") for dep in dev_group)
    assert not any(dep.startswith("crosshair>=") for dep in dev_group)
    assert importlib.util.find_spec("crosshair") is not None


def test_contract_prototype_passes_against_production(tmp_path: Path) -> None:
    """The 6-contract CI-profile prototype holds against real maistro code.

    Exit 0 with empty output = no counterexample found on the documented
    domains. This is NOT proof of correctness (the issue's own warning); it
    pins that the contracts are satisfiable and the seams stay analyzable.
    """
    result = _run_crosshair(
        CONTRACT_PROTOTYPE_SOURCE,
        tmp_path,
        "m8a_ci_contracts.py",
        "--per_path_timeout",
        "60",
    )
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"
    assert result.stdout.strip() == ""


def test_crosshair_reports_exact_counterexample(tmp_path: Path) -> None:
    """Anti-vacuity: the engine genuinely analyzes and reports deterministically."""
    result = _run_crosshair(NEGATIVE_CONTROL_SOURCE, tmp_path, "bad.py")
    assert result.returncode == 1
    assert (
        f"{tmp_path / 'bad.py'}:3: error: false when calling inc(1) "
        "(which returns 2)" in result.stdout
    )


def test_documented_false_positive_replays_clean(tmp_path: Path) -> None:
    """The known false positive: reported, and disproven by concrete replay.

    CrossHair reports a counterexample for an input at the float-range
    boundary; replaying that exact input against the real function shows the
    contract holds. The false positive is budget-dependent: it appears only
    when ``--per_path_timeout`` gives the solver room at the int→float
    conversion boundary (with the default budget the same probe exits 0).
    This pins the replay-triage protocol any CI adoption would need: never
    trust an un-replayed counterexample.
    """
    result = _run_crosshair(
        FALSE_POSITIVE_SOURCE,
        tmp_path,
        "fp_budget.py",
        "--per_path_timeout",
        "20",
    )
    assert result.returncode == 1
    assert "known_cycle_never_raises" in result.stdout
    assert str(FALSE_POSITIVE_INPUT) in result.stdout

    from maistro.types.model import normalized_daily_budget

    replayed = normalized_daily_budget(FALSE_POSITIVE_INPUT, "monthly")
    assert replayed >= 0.0


def test_applicability_scan_imports_but_finds_no_checkable_functions(
    tmp_path: Path,
) -> None:
    """E1 datum: every scanned module imports cleanly, none is checkable.

    A missing module, an import-time crash, or an audit-hook trip would be a
    different (and notable) result; the pinned outcome is that imports are
    never the barrier in this codebase — contract authoring is.
    """
    for rel in APPLICABILITY_MODULES:
        target = REPO_ROOT / rel
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "crosshair",
                "check",
                str(target),
                "--per_path_timeout",
                "30",
            ],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            timeout=300,
            check=False,
        )
        assert result.returncode == 0, f"{rel}: {result.stdout} {result.stderr}"
        assert "no checkable functions" in (result.stdout + result.stderr)
