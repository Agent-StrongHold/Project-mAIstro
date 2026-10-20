# M8-A research note — CrossHair symbolic execution for pure Python invariants

Epic: #880. Leaf: #890 (M8-A10). Initiative: #879.

## Hypothesis (from the issue)

CrossHair can find counterexamples in deterministic, side-effect-light Python
logic without requiring translation to another language, making it potentially
valuable for small MAIstro policy and transformation functions.

## Canonical targets (real seams, all importable without I/O)

| Seam | Module | Issue candidate class |
|---|---|---|
| `expand_scopes` | `maistro.auth._types` | scope/permission expansion |
| `normalized_daily_budget`, `validate_billing_cycle` | `maistro.types.model` | normalization and validation helpers (#1205: the single formula) |
| `BudgetRule.evaluate`, `ForbiddenPairRule.evaluate` | `maistro.policy.rules` | priority/routing calculations (ADR-085/086 policy decisions) |
| `compute_effective_cost` | `maistro.router.scarcity` | routing calculations (production authority for effective cost) |
| `cycle_key` | `maistro.quota.billing` | wall-clock-keyed bucketing (side-effect probe) |

Out of scope after triage: `capabilities/invocation.py` effect identity (its
identity logic is coupled to store rows and admission state — not isolatable
without refactoring; recorded in the applicability map below rather than
force-wrapped), and async/I/O-bound modules generally.

## Baseline

- The Hypothesis formal suite (`formal/`, #410 evidence rules) and the
  hand-written suites. Directly relevant: formal I7 (`test_auth_scopes.py`,
  scope expansion with an independent oracle), formal I21
  (`test_billing_cycle.py`), and `packages/maistro-core/tests/policy`
  (12 hand-written tests, no property-based coverage).
- No symbolic execution anywhere in the repo before this leaf.

## Method

Three experiments, all against the real worktree (CrossHair 0.0.111,
`crosshair-tool`, declared in `[dependency-groups].dev`):

1. **E1 — applicability scan.** `crosshair check <module>` over seven
   production modules (five pure seams, plus `capabilities/invocation.py` and
   `orchestrator/master.py` as heavy/stateful probes).
2. **E2 — contract prototype.** 17 docstring contracts (`pre:`/`post:`/
   `raises:`) restating each module's documented behavior, checked against the
   unmodified production code. Six of them — one per real seam — are committed
   as the `CONTRACT_PROTOTYPE_SOURCE` CI profile in
   `packages/maistro-rsi/tests/test_m8a_crosshair_research.py`; the other 11
   (scarcity-dominance, `ForbiddenPairRule`, and `cycle_key` probes) were
   session artifacts **not preserved**, so results attributed to the full set
   below are observed-once evidence, not tree-reproducible (see the
   reproducibility note on the mutant table).
3. **E3 — mutant comparison.** Four mutants applied to an out-of-tree copy of
   `maistro-core/src` (`tar` copy; the worktree itself is never mutated). Each
   mutant is run against the relevant existing suites AND the contract
   prototype. **Isolation correction (review):** the first submission ran the
   suites with a bare `PYTHONPATH=<muttree>` prepend and reported 12/224
   survivor passes. That precedence check was done in a plain interpreter, not
   inside pytest: pytest's `pythonpath` ini (`pyproject.toml`,
   `[tool.pytest.ini_options]`) prepends the workspace `src` dirs at
   `sys.path[0]` in every pytest process, so the suites actually executed the
   unmutated worktree. All suite numbers below are from reruns with
   `-o pythonpath=<muttree>`, with in-process precedence proven by an
   ImportError canary appended to the mutated module.

## Results

### E1 — imports are never the barrier; contracts are

All seven modules import and traverse cleanly under `crosshair check`
(0.4–1.5 s each) and every one reports `WARNING: Targets found, but contain no
checkable functions.` — including the DB-coupled `capabilities/invocation.py`
and the heavy-import `orchestrator/master.py`. 7/7 analyzable without
refactoring at the import level; 0/7 checkable without authoring contracts
first. The cost center of this technique in MAIstro is annotation effort, not
tool compatibility.

### E2 — contracts: green against production, and instructive when red

The full 17-contract set passed (exit 0, no counterexamples) against
unmodified production code in the original session — ~53–57 s wall for the
full set, 19.4 s for the six-contract CI profile (per-path budget 20 s;
timings from the development machine, structural not contractual). After the
review, the committed CI profile is **re-bounded** to keep the whole
subprocess far under CI's 30 s per-test kill: per-path budget 5 s, measured
~7 s wall, still exit 0 with no counterexamples. A budget this tight makes the
committed profile a satisfiability/analyzability pin, not a completeness
claim — heavy analysis stays out of CI.

The `cycle_key` wall-clock probe (session set) also passed under CrossHair's
default side-effect audit: `datetime.now` consumption does not trip the
blocker for shape-level postconditions.

Four first-run counterexamples, classified by replay:

1. **Tool false positive (the key reliability datum).**
   `known_cycle_never_raises(cycle, free_tokens)` (post: `__return__ >= 0.0`)
   is reported violated at `'monthly', 17976931348…4858369` — an int at the
   float-range boundary. Replaying that exact input concretely returns
   `5.99e306 >= 0.0` = True: the contract holds; the reported counterexample
   is wrong. The false positive is **budget-dependent**: with the default
   per-path budget the probe exits 0; with `--per_path_timeout 20` it fired on
   the development machine — but whether the solver reaches the boundary
   region within a budget is a property of the machine, so the pin is
   **opt-in** (`MAISTRO_CROSSHAIR_BUDGET_REPRO=1`), never a merge gate. Any
   CI adoption needs a mandatory concrete-replay triage step; the module pins
   both halves (reported AND replayed-clean) behind that switch.
2. **Spec gap (mine):** the in-budget scarcity contract omitted
   `billing_cycle in SUPPORTED_BILLING_CYCLES` from its precondition;
   CrossHair found the exact `ProviderConfig(billing_cycle='')` that escapes
   as `UnknownBillingCycleError`. Contracts force implicit caller domains to
   become explicit — precisely their maintenance value.
3. **Spec gap (mine):** the paid-overage dominance contract allowed negative
   overage rates, where `OVER_QUOTA_FLOOR + avg_rate` drops below the floor.
   No production validation forbids negative rates; recorded below as a
   routing-owner follow-up, not fixed in M8 (guardrail 4).
4. **Expressiveness limit:** `implies` is not Python; implication must be
   written as `not A or B`. CrossHair reports this as
   `invalid syntax (<string>, line 1)` — legible, but easy to misread as a
   tool failure (an earlier attempt at this leaf did exactly that).

### E3 — mutant battery: suites and CrossHair agree (corrected after review)

| Mutant | Defect | Existing suites (corrected isolation) | CrossHair (committed 6-contract profile; M1–M3 re-verified post-review) |
|---|---|---|---|
| M1 | `BudgetRule`: `value > limit` → `>=` | **caught**: `tests/policy` 2 failed / 10 passed — `test_keys_are_isolated` (`BudgetRule("count", limit=1)`, first charge must be ALLOW) and `test_decision_sink_fires_on_non_allow_only` | **caught**: `BudgetRule('tokens', limit=0.0)`, `SequenceState(tokens=0)` — denies exactly at the boundary |
| M2 | `expand_scopes`: category wildcard drops one scope | formal I7 **3 failed — caught** (matches its recorded M13a history) | **caught**: exact input `expand_category_wildcard_is_complete('builders')` |
| M3 | `normalized_daily_budget`: `/30.0` → `/31.0` | **caught**: `formal I21 + tests/quota` 4 failed / 220 passed / 29 skipped — `test_daily_budget_monthly` and `test_daily_budget_equals_free_tokens_div_30_monthly` assert `30000/30`, plus `TestDailyBudget::test_monthly_divides_by_thirty` and the quota race-boundary test (passes on the clean tree) | **caught**: minimal input `monthly_budget_is_thirtieth(1)` returning `1/31` |
| M4 | `ForbiddenPairRule`: self-pair decrement dropped | `tests/policy` **missed** | **missed** (see below) |

Reproducibility note (added in review): the CrossHair column's M1–M3 catches
rest on contracts that ARE committed (`budget_rule_iff`,
`expand_category_wildcard_is_complete`, `monthly_budget_is_thirtieth`) and
were re-verified after the isolation correction by running the committed
profile against out-of-tree mutant copies (`PYTHONPATH=<muttree>` in a plain
`crosshair check` subprocess, precedence canary-proven; the exact
counterexamples above are re-derived, not remembered). The M4 row's contract
was part of the uncommitted session set, so its "missed" is observed-once
evidence — re-derivable only by re-authoring the contract per the procedure
below.

Corrected reading: on M1–M3 the existing suites and CrossHair catch the same
defects; CrossHair's advantage is counterexample quality — minimal concrete
inputs (`SequenceState(tokens=0)`, `monthly_budget_is_thirtieth(1)`) in
seconds, where Hypothesis shrinks to a strategy-level example. On M2
CrossHair's counterexample names the failing category directly. The original
claim that symbolic execution found exact-boundary and exact-rate defects
"the entire existing suite misses" was an isolation artifact and is withdrawn.

### The honest miss (M4) — the applicability boundary

M4's discriminating region needs `counts_by_kind == {kind: 1}` — a single-entry
dict, for a ForbiddenPair contract that belonged to the uncommitted session
set (so the row above is observed-once evidence, not a tree-reproducible
result). Two `post: False` canary probes (with and without a `len(kind) == 1`
hint) both exited 0: CrossHair could not construct that dict region within
budget, so the contract passed **vacuously** even though its precondition is
reachable (the canaries fire on the empty-dict region). Simple frozen dataclasses
(`BudgetRule`, `ProviderConfig`) symbolize fine; dataclasses holding
dict/deque fields do not, in practice. This is the same harness-vacuity lesson
recorded on leaf #882: a green contract proves nothing until reachability of
its discriminating region is demonstrated.

### Cost summary

- Dependency: one dev-group package (`crosshair-tool`), no runtime impact.
  (The initially added bare `crosshair>=0.1.0.dev11` pin is an unrelated
  legacy PyPI package whose distribution shadows crosshair-tool's import name;
  removed — hygiene finding recorded.)
- Annotation: 17 contracts ≈ 90 lines for five seams; each contract restates
  an existing documented behavior (docstrings, #1205), so drift risk tracks
  the docs it mirrors.
- Runtime: ~7 s CI-profile prototype (per-path budget 5 s, re-bounded in
  review to sit far under CI's 30 s per-test kill); full session set ~1 min;
  per-module scans ~1 s.
- Reliability: 1 deterministic false positive in 4 reported counterexamples —
  100% replay-triage required before any counterexample is believed.
- Coverage shape: exact boundaries/rates (strong) vs state-shaped inputs with
  populated dict fields (unreachable) vs anything touching I/O, async, or
  wall-clock values beyond shape (out of scope).

## Evidence questions (from the issue), answered

- **Does CrossHair find cases Hypothesis misses or find them faster?** No on
  misses at these seams (corrected after the isolation fix): every mutant the
  suites catch (M1–M3), CrossHair catches too, and vice versa except M4.
  Yes on speed/precision: counterexamples arrive as minimal concrete inputs.
  Complement, not replacement: on the one seam with a strong Hypothesis oracle
  (I7), both catch M2; and M4 shows CrossHair missing what a Hypothesis
  strategy over dict fields would hit trivially.
- **What percentage of candidate code is analyzable without refactoring?**
  7/7 scanned modules (100%) import cleanly under CrossHair; 0% carry
  checkable contracts today. Effect-identity logic in
  `capabilities/invocation.py` is not isolatable from store state without
  refactoring — recorded, not forced.
- **How costly are annotations/contracts to maintain?** ~5 contracts per seam,
  each mirroring an existing docstring/ADR statement; the two red-flag runs
  during the experiment were both underspecified preconditions (mine), which
  is the technique working: contracts surface implicit caller domains.
- **How often do external calls, dynamic typing, async, or unsupported
  features make analysis unhelpful?** In this target set: imports never
  (7/7); wall-clock reads do not block shape-level checks; the practical wall
  is symbolic construction of populated dict/deque state (M4) and float-range
  reasoning (the false positive); the other three mutants are caught by both
  the existing suites and CrossHair.
- **Is the result reliable enough for CI, advisory use, or only targeted
  audits?** Advisory/targeted now. Counterexamples require mandatory concrete
  replay (deterministic false positive demonstrated); vacuity requires
  canary-proving discriminating regions. Not proposed as a merge gate.

## Reproduction procedure

1. Contracts: extract `CONTRACT_PROTOTYPE_SOURCE` from
   `packages/maistro-rsi/tests/test_m8a_crosshair_research.py` to a file;
   `uv run crosshair check <file> --per_path_timeout 5` → exit 0 (the bound
   the committed CI profile runs under). The budget-dependent false positive
   is exercised by the opt-in test:
   `MAISTRO_CROSSHAIR_BUDGET_REPRO=1 uv run pytest packages/maistro-rsi/tests/test_m8a_crosshair_research.py`.
2. Mutants: `tar --exclude='__pycache__' -cf - maistro | tar -C <muttree> -xf -`
   from `packages/maistro-core/src`; apply the one-line mutation from the
   table above; run the existing suites and CrossHair with
   `-o pythonpath=<muttree>` on every pytest invocation. A bare
   `PYTHONPATH=<muttree>` is NOT sufficient: pytest's `pythonpath` ini
   prepends the workspace `src` dirs at `sys.path[0]` inside the pytest
   process (this is the isolation defect behind the originally reported
   12/224 survivor passes). Verify precedence in-process — appending
   `raise ImportError('mutant loaded')` to the mutated module must fail the
   run. The worktree itself is never mutated.
3. False positive: `uv run crosshair check <fp.py> --per_path_timeout 20`;
   replay the printed input with `normalized_daily_budget(<input>, 'monthly')`.
   Whether the counterexample appears within a given budget is
   machine-dependent; on the development machine 20 s/path was sufficient.

## Disposition

**INCUBATE.** The tool works on real MAIstro seams today: at ~7 s CI cost and
one dev dependency it catches the same three of four battery mutants the
existing suites catch, returning minimal concrete counterexamples instead of
shrunken strategy examples. The differentiator is counterexample quality, not
unique defect discovery (the originally claimed detection gap was an
isolation artifact). It is not ready to gate anything: one deterministic false
positive per four reported counterexamples, and one of four mutants missed
vacuously, means both findings and passes require triage machinery that does
not exist yet. M8 does not adopt it into CI (guardrail 6: no replacement of
working controls without evidence; `formal/` remains the canonical in-repo
model authority).

Next required evidence before a GRADUATE decision:

1. A replay-triage wrapper (counterexample → concrete replay → verdict) plus a
   bounded contract set for one real seam, run in CI for a release cycle, with
   false-positive rate measured on real PRs.
2. A reachability canary convention (every contract carries a demonstrated
   `post: False`-style probe for its discriminating region, per the M4 lesson)
   so vacuous greens are structurally impossible.
3. Owner routing for the two domain findings this experiment surfaced:
   `compute_effective_cost`'s paid-overage dominance invariant is unenforced
   for negative overage rates (router/scarcity owner), and no test pins the
   documented `/30.0` daily-budget rate (quota owner, #1205). Per epic rules
   these route to M0–M7 owners rather than being fixed in M8.

## Trust boundary

Prototype contracts live in a test module and this note; nothing here is
imported by product code, nothing touches a Goal/Run/NodeRun authority, and
CrossHair runs with its default side-effect audit. The prototype module
(`packages/maistro-rsi/tests/test_m8a_crosshair_research.py`) is evidence, not
a control; its green runs assert satisfiability of documented contracts, never
correctness of the implementation (the issue's own warning).
