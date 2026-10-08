# M8-A research note — critical-zone mutation strategy for architectural invariants

Epic: #880. Leaf: #894. Initiative: #879.

## Research question

Does mutation testing provide more value when concentrated on high-consequence
invariant code than when uniformly maximizing mutation score across the
repository — and is a near-zero-survivor policy practical for *selected*
invariant code?

## Canonical seam

The prototype zone is real authorization invariant code:
`packages/maistro-core/src/maistro/security/trust_boundary.py` — the per-agent
permission-grant system at the trust boundary (grant expiry enforcement,
resource-scope globs for read/write, the execute capability gate with its
command allowlist, and the final deny-all fallback). It hits three of the
leaf's candidate zones at once (authorization enforcement, workspace/tenant
scoping via path globs, and fail-safe defaults), it is small (123 LOC), and its
mirror suite `packages/maistro-core/tests/security/test_trust_boundary.py`
(17 tests) is the narrowest scope `scripts/mutation_targets.py` maps — so the
zone satisfies the affordability constraint that produced the historical
30-minute PR mutation timeout when violated.

The other candidate zones from the leaf (canonical execution transitions,
Invocation retry protection, Event ordering/replay, Goal ownership/delegation,
scheduler admission/idempotency) are larger; `classify_zone` in the harness
prices them from the measured density below before any mutant is generated.

## Deliverable 1 — critical-zone selection criteria

Codified as an executable classifier in
`packages/maistro-rsi/tests/test_m8a14_critical_zone_mutation_research.py`
(`classify_zone`; every criterion has a hand-checked reject case):

- **C1 authority adjacency** — the module enforces at least one of the leaf's
  invariant families, asserted through an explicit role registry
  (`AuthorityRole`), not keyword guessing. Authority alone is not sufficient.
- **C2 narrow test scope** — a mirror test file resolves. A module whose tests
  resolve only to a whole-suite directory cannot run per-mutant affordably;
  that widening is exactly how the historical PR mutation job hit its
  30-minute wall (`scripts/mutation_targets.py` documents the incident).
- **C3 bounded budget** — estimated mutants (LOC × measured density) must fit
  the experiment budget. The measured density of the prototype zone is
  **103 mutants / 123 LOC ≈ 0.84 mutants per LOC**. A large authority module
  (e.g. `scheduling/admission.py`, 1465 LOC → ~1231 estimated mutants) fails
  this criterion and must be *split*, not silently admitted.
- **C4 affordable per-mutant cost** — measured unit cost below
  `max_per_mutant_seconds` (this zone: ~2.3 s/mutant serial).
- **C5 fail-safe shape** — the refusal path defaults to deny. Mutation bias
  then surfaces in the dangerous direction (granting), so every survivor is
  security-relevant by construction and earns its triage cost.

## Deliverable 2 — operator semantic-risk taxonomy

cosmic-ray 8.7 ships **213 operator variants over 16 families**
(`cosmic-ray operators`; asserted in the harness). The prototype run's central
taxonomy finding: **operator risk is context-dependent**. The same family is a
decision flip in a guard, a magnitude change with security consequence on a
runtime TTL, and a no-op on a type annotation. The harness classifies
(family × syntactic context) pairs (`classify_operator`):

- **decision_flip** at runtime-value positions: `ReplaceComparisonOperator`,
  `ReplaceAndWithOr`/`ReplaceOrWithAnd`, `ReplaceTrueWithFalse`/
  `ReplaceFalseWithTrue`, `AddNot`, `ReplaceUnaryOperator`,
  `ReplaceBreakWithContinue`/`ReplaceContinueWithBreak`, `VariableReplacer`,
  `VariableInserter` — these flip branch selection in guards.
- **magnitude_or_flow** at runtime positions: `ReplaceBinaryOperator`,
  `NumberReplacer`, `ZeroIterationForLoop`, `ExceptionReplacer` — they change
  computed values, not branch selection directly. **Not "low"**: on this zone's
  TTL arithmetic, `+` → `*` means *grants that never expire*.
- **equivalent_by_construction** at PEP 563 annotation or message contexts:
  any value-operator. With `from __future__ import annotations`, parameter
  annotations are strings and are never evaluated — `str | None` →
  `str * None` cannot change behavior.
- **structural**: `RemoveDecorator`.

## Deliverable 3 — prototype run (real, reproducible)

Executed 2026-10-08 against the canonical seam, cosmic-ray 8.7.0, local
distributor, serial. Config (paths were absolute at run time):

```toml
[cosmic-ray]
module-path = ".../packages/maistro-core/src/maistro/security/trust_boundary.py"
timeout = 60.0
excluded-modules = []
test-command = "uv run pytest packages/maistro-core/tests/security/test_trust_boundary.py -x -q"

[cosmic-ray.distributor]
name = "local"
```

Procedure: `cosmic-ray baseline` (17 passed, 2.48 s) → `cosmic-ray init`
(**103 mutants**: 63 `check_permission`, 14 `PermissionGrant`,
14 `validate_spec`, 12 `create_grant_for_task`) → `cosmic-ray exec`
(**3 m 59 s wall, ~2.3 s/mutant serial**) → session SQLite analysis. Every
worker outcome was `NORMAL` — no timeout or infrastructure artifacts; the
result is clean evidence.

| Outcome | Count | Rate |
|---|---|---|
| KILLED | 53 | 51.5% raw |
| SURVIVED | 50 | — |
| KILLED among meaningful mutants (excl. equivalents) | 53 / 78 | **67.9%** |

## Deliverable 4 — survivor taxonomy (all 50 classified)

| Class | Count | Meaning | Action |
|---|---|---|---|
| `equivalent_by_construction` | 25 | 22 PEP 563 annotation `str \| None` binary-operator mutants (L76–77) + 3 `==`→`is` enum-identity mutants (L91/94/97) | exclude at generation time |
| `lexicographic_coincidence` | 2 | StrEnum members compare lexicographically, so `action >= Action.WRITE` (L94) and `action <= Action.EXECUTE` (L97) coincide with `==` over the closed member set | seal the member set or ignore |
| `boundary_measure_zero` | 2 | `>` → `>=` at expiry (L88) and prompt-stuffing limit (L52) | optional exact-boundary assertions |
| `untested_invariant` | **19** | real authorization/scoping semantics no test observes | **triage to the zone owner** |
| `non_invariant_metadata` | 2 | grant-ID entropy width (L28 `secure_id(6)`) | out of policy scope |

The 19 actionable survivors, by invariant:

- **Deny-all fallback unpinned (L106)** — `return False` → `return True`.
  **Hand-verified**: the mutated module was run against the mirror suite
  directly and all 17 tests passed. The single most security-critical line of
  the module — the default-deny — has no test.
- **Fail-safe default unpinned (L32)** — `can_execute: bool = False` → `True`.
  **Hand-verified** the same way. Default-constructed grants silently gain the
  execute capability.
- **Deny-by-default bypass via action guard (L97)** — `== Action.EXECUTE` →
  `>=`: StrEnum lexicographic order routes READ *and* WRITE into the execute
  branch, where a capability grant authorizes without any scope. The
  deny-all fallback becomes unreachable for every action. Modeled and killed
  deterministically in the harness (`test_action_guard_ge_reproduces_the_
bypass_shape`).
- **Calling-convention invariants unpinned (L91, L94 `<=`)** — EXECUTE calls
  carrying a path would enter the read/write branches; safe only under the
  implicit convention that execute checks never pass a path.
- **Asymmetric scoping unpinned (L94 `and`→`or`)** — factory grants use
  identical read/write path lists, so a READ consulting write scopes is
  unobservable to the suite.
- **Execute command-gate semantics unpinned (L100 `and`→`or`)** — both the
  allow-all meaning of an empty allowlist and the deny-then-fail path for a
  restricted grant with `command=None`.
- **Grant liveness/expiry unpinned (L34 ×11, L122)** — every replacement of
  `time.time() + TTL` survives: `−` means every default grant is instantly
  expired (deny everything), `*`/`/`/`**` means grants never expire
  (over-extension). Neither direction is observed.

### Mechanism, not correlation

The harness includes a miniature deterministic mutation engine over a
hand-checked deny-by-default guard with the zone's control shape. It
demonstrates for each representative survivor family: the mutant violates
exactly one oracle when the full battery runs (killed), and survives when that
oracle is absent — reproducing each recorded survivor mechanism in CI without
running cosmic-ray. A mutant survives exactly when no oracle distinguishes it;
that is the whole diagnosis, and it is testable.

## Answers to the leaf's questions

1. **Which survivors represent genuinely untested architectural semantics?**
   The 19 `untested_invariant` rows above — 37% of survivors, and every one is
   a deny-by-default, scoping, capability, or grant-liveness invariant. Two
   were hand-verified by running the mutated module against the mirror suite.
2. **Which are equivalent/uninteresting?** 29 of 50 (58%): 25
   equivalent-by-construction (annotation/identity), 2 lexicographic
   coincidences, 2 non-invariant metadata. A further 2 are measure-zero
   boundaries.
3. **PR CI or nightly?** Measured: one zone ≈ 4 min serial → fits a PR slot.
   The leaf's seven candidate zones at this zone size ≈ 27 min serial →
   nightly (or a designated self-hosted job), not PR CI. Repository-wide at
   this density is infeasible — which is the hypothesis confirmed: uniform
   maximization buys mostly equivalents, while a curated zone set buys
   actionable invariants per minute. Note the current state: the nightly
   mutation workflow is parked (`.github/workflows/mutation.yml` runs
   `workflow_dispatch` only and prints a deferral notice), so today mutation
   runs in neither; a critical-zone job is the cheapest possible restart.
4. **Does a stricter local policy outperform broad score chasing?** Yes on
   this evidence: 31 of 50 survivors in one small module are non-actionable
   classes a broad score gate would force triage on, while the curated zone
   yields 19 concrete untested invariants for 4 minutes of compute. The
   policy that works is: exclude equivalents at generation time, count only
   `untested_invariant` survivors, require zero trend.
5. **What ownership/process for survivor triage?** Zone-owner rotation. On
   each run: `untested_invariant` → issue against the zone owner with the
   mutant diff (cosmic-ray session rows carry operator + position); `boundary`
   → optional exact-boundary assertion; `metadata` → closed as out of scope;
   `equivalent` classes → fed back into operator configuration, never into
   test debt.

## Relationship to existing evidence infrastructure

No existing gate was weakened or touched: `scripts/check_mutation_baseline.py`,
`quality/mutation-baseline.json`, the `scripts/mutation_*.py` family, and both
workflows are unmodified. The ratchet floor (0.90) and its provenance rules
apply unchanged. This experiment is complementary: it measures what the
*baseline gate's* raw score hides (equivalent-class noise) and prices the
*target resolution* that `scripts/mutation_targets.py` already enforces. The
harness lives under `packages/maistro-rsi/tests/`, imports nothing from
`maistro` (M8 guardrails 1–2), and asserts its evidence-only contract.

## Defect finding routed to the owning milestone (guardrail 4)

The prototype exposed a test-suite gap, not a product defect: production
`check_permission` behaves correctly, but nothing pins the deny-all fallback,
the fail-safe capability default, or grant liveness — the two hand-verified
survivors are one-line killer tests away from being killed. Per M8 guardrail 4
this is recorded for the earliest owning milestone (test hardening on
`packages/maistro-core`), not smuggled into this research change.

## Benchmark procedure (what the next experiment must do)

1. Select the next zone with `classify_zone` (recommended: scheduler admission
   idempotency or Invocation retry protection, split to fit C3);
2. Exclude annotation/identity equivalents at generation time (operator
   configuration or a post-`init` session filter) so triage sees only
   meaningful mutants;
3. Run the same cosmic-ray procedure; classify survivors with the taxonomy;
4. Move actionable survivors to zero with zone-owner issues; hold the zone at
   zero for one milestone;
5. Graduate when a standing critical-zone job (nightly-lite) catches or kills
   a real regression at ≤ 30 min/night; reject if the second zone's actionable
   yield does not justify triage ownership.

## Disposition

**INCUBATE** — the prototype ran for real against a canonical authorization
seam, the selection criteria, operator taxonomy, and survivor taxonomy are
codified and tested, and the hypothesis has first-zone support (19 actionable
findings for 4 minutes of compute vs. 58% equivalent noise under a broad
policy). INCUBATE rather than GRADUATE because: the evidence is one zone;
cosmic-ray's stock operator set still spends half its budget (and all of the
raw-score optics) on equivalent-by-construction mutants, so a near-zero
survivor policy is not yet practical without generation-time exclusion; the
nightly mutation workflow is parked with no runner capacity committed; and a
triage owner has not stood up. Next required evidence is the five-step
procedure above. WATCH trigger: a second zone whose actionable yield is
dominated by equivalents after exclusion — that would say the approach does
not generalize beyond authorization-shaped code.
