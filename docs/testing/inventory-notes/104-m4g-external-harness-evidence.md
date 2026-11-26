---
inventory-delta:
  packages/maistro-evolve/tests: +191
---

# 104-m4g-external-harness-evidence

Epic #104 (M4-G) — external harness benchmarks and published evidence. This
note records the test-inventory movement for the change: **+168 collected
nodes** in `packages/maistro-evolve/tests` (722 → 890), all additions; no
existing test was removed or renamed.

## What moved and why

Six new test modules, plus additions to two existing ones:

| File | Nodes | What it pins down |
|------|-------|-------------------|
| `test_verdict_probes.py` | 15 | The adversarial/mutation battery: every hostile response is rejected by every production verdict path, every permissive mutant is killed by the same corpus, an empty battery certifies nothing, and the manifest section carries the mutant column. |
| `test_evidence_manifest.py` | 49 | The published manifest: build-time refusals (no conformance, failing conformance, unquotable score, `gap_closure` without `baseline_version`), the metering-presence/absence rules, and per-section tamper detection with the checksums re-sealed so each rule is judged on its own. |
| `test_lift_matrix.py` | 26 | The matched 4-cell matrix: derived lift/gap/gap-closure/transfer/inversion, and every refusal (same model in a row, two versions, two benchmarks, two harnesses per column, wrong column, missing/duplicate cell). |
| `test_arc_agi_benchmark.py` | 38 | The second-domain ARC-AGI adapter: corpus loading, withheld-answer secrecy, exact-grid grading, spoofed-`PASS`/prose/boolean/ragged-grid rejection, and the `official_comparable=False` contract. |
| `test_eval_metering.py` | 18 | The metered run block: cost/security-tax/RHAE math, refused event kinds, and that the meter never rewrites an adapter's own `metadata`. |
| `test_fitness_transfer_gate.py` | 12 | The transfer-inversion fitness gate: a measured inversion disqualifies, a stale measurement still disqualifies, and a promotion candidate without transfer evidence is blocked. |
| `test_harness.py` (existing) | +5 | The harness runs the verdict battery before it hands results back, refuses to return results when the battery does not hold, and stamps the metered block on every result without rewriting the adapter's own metadata. |
| `test_cycle.py` (existing) | +5 | The run publishes its evidence manifest when a target is configured, publishes nothing when it is not, and never overwrites an earlier run's evidence. |

## Notes on the count

The delta is additive only: no existing test was deleted, skipped, or
renamed, so the movement is fully explained by the table above. The
`+168` figure is the collected-node count reported by
`scripts/check-suite-inventory.py --update --note 104-m4g-external-harness-evidence`
(722 recorded → 890 collected). It was cross-checked node-by-node against the
base tree (`git archive fa2deb0a4`): 722 collected at the base, 890 collected
here, 168 added, 0 removed.

One production behaviour changed underneath the tests, and it is called out
here because it is the kind of change a count alone would hide:
`EvalResult.run_metering` is a new first-class field, and the metered block
is no longer written into the adapter-owned `metadata` dict. The existing
`test_e2e_sandbox_loop.py` assertion on the exact `metadata` contract
(`{"stub": False, "exit_code": 0}`) is what pinned that decision — metering
needed its own field rather than a metadata key.

## Develop reconciliation (branch rebuild)

The branch was re-landed onto develop (`4de7e906d`) after the earlier
single-commit graft reverted unrelated develop work. This change now is
exactly the 22 files above on top of develop; the nine files develop had
also advanced were re-merged three-way (base `fa2deb0a4`, lane
`63ceaaf8a7`, develop), keeping both sides' semantics. Consequences for
this note:

- The ledger delta above (`packages/maistro-evolve/tests: +168`) is
  unchanged and still describes this change's own contribution. On the
  reconciled branch the suite collects 1172 nodes = 651 (folded baseline)
  + 521 (sum of unfolded deltas, of which this note's change is +168);
  `scripts/check-suite-inventory.py` passes on exactly that arithmetic.
  The "722 → 890" absolutes earlier in this note describe the change
  measured at its original lane base, not the current tree.
- Two develop-side test stubs were adapted, with no node-count movement:
  the inline `_Cfg` doubles in `test_champion_provenance.py` gained
  `evidence_dir: None`, mirroring the new `EvolutionConfig` field's default
  (no evidence target ⇒ nothing published), which the folded-evidence tests
  now also implicitly pin.
- The radon ratchet (see `check-radon-baseline.py`) is met without a grant:
  the four C-grade blocks this change first introduced were refactored
  under rank B (`_inversion_entry_failures`/`_missing_transfer_evidence`,
  `_require_verdict_conformance`/`_lift_section_rows`/
  `_resolve_metering_block`, `_result_row_errors`,
  `_validate_train_pair`/`_validate_test_entry`), messages byte-identical,
  with the same 1166-pass suite pinning the behaviour.

## Writer repair: transfer-gate policy and evidence identity

The historical +168 delta above is supplemented by **23 new regression nodes**
in `test_fitness_transfer_gate.py` (+191 total for this note). The added cases
exercise candidate-supplied tolerance relaxation/malformed values (7), non-finite
or impossible transfers (5), fitness digest changes for transfer/tolerance/
approval inputs (3), the real cycle recomputability guard after a transfer
refresh (1), and the promotion-path gate reach (7, see the next section). No
existing test is removed or renamed.

The repair is bounded to the existing transfer fitness implementation. A
candidate may request a stricter tolerance, but cannot weaken the host's
`TRANSFER_EPSILON` ceiling; malformed tolerances and non-finite/out-of-range
transfer values fail closed. Transfer gate inputs must participate in the
fitness evidence digest so refreshed evidence cannot trigger a false
`FitnessEvidenceDriftError`.

Validation and epic-wide acceptance limitations are recorded below; prior
verification claims are not treated as current acceptance evidence.

## Validation executed for this repair (2026-11-26, this lane, `uv run`)

Fail-then-pass, re-executed this round by swapping `fitness.py` against
HEAD `8220813611` (file copies, no git history operations): at HEAD the new
cases fail **14/28** (including a real `FitnessEvidenceDriftError` raised by
`cycle.py` — a legitimate transfer refresh zeroing fitness under an unchanged
evidence hash); with the repair the module passes **28/28**.

Full battery on the repaired tree:

- `pytest packages/maistro-evolve/tests -q` → **1182 passed, 6 skipped**;
- `ruff check .` → all checks passed; `ruff format --check .` → 3495 files
  formatted;
- `scripts/check-suite-inventory.py` → ok, 21 suites, this note's suite at
  **1188 collected nodes** (651 folded + note deltas), no duplicates;
- `scripts/check-radon-baseline.py` (RATCHET_BASE_REV=origin/develop, merge
  base `4de7e906d9`) → 127/127 blocks, 0 new, 0 regressed, 0 stale;
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1302/1302 identities;
- `scripts/check-execution-lifecycles.py` → 19/19 classified;
- `scripts/check-model-egress.py` → 20 callers, no candidate-approved
  expansion.

Production-path acceptance probes (no network/credentials) confirm the
verdict battery holds on all four graders (hostile responses rejected,
all four mutants killed) and that ARC availability is honestly reported
(`False`, corpus not vendored — see below). Three observed limitations are
recorded for review, not repaired here:

1. ~~`promotion`/`selection_eligibility` and `PopulationStore._promote`
   re-derive only `_check_hard_gate` (per-benchmark thresholds); the
   transfer-inversion rules reach `compute_fitness` but not the activation
   path, so a measured inversion with `fitness_score=0.0` and
   `approved_for_promotion=True` can still activate when no incumbent is
   active.~~ **Repaired in this change** (see the promotion-path section
   below); the probe scenario now refuses with `PermissionError` naming the
   inversion and leaves no active genome.
2. `publish_evidence_manifest` accepts and verifies a manifest whose run
   metering records `unresolved_security_violations=1` — publishing
   evidence of a violation vs refusing to publish is a design call for
   review, not silently decided here.
3. `_publish_evidence`'s run id is `<genome>-cycle-<n>`, so two fresh
   `EvolutionCycle` instances evaluating the same genome at the same cycle
   count overwrite one manifest (within-instance runs cannot); the normal
   producer also supplies no `lift` rows or `refused_diffs` — those
   sections are schema-verified but not yet populated by the cycle path.

Epic-wide acceptance items that remain unimplemented/unverified for #104:
ARC-AGI-3 proper (the adapter grades static ARC grids with
`official_comparable=False`; the ARC Prize corpus is not vendored, so no
ARC-AGI-3 evaluation has run), matched same-model comparisons against real
external harnesses (the lift matrix machinery exists and is tested, but no
external harness has been wrapped), and fresh-workspace controls on the
real evaluation path.

## Writer repair: the composed gate reaches the promotion path

The probe limitation above was repaired rather than reported: the
acceptance-probe scenario (fitness 0.0 from a measured inversion, human
approval, no incumbent) now refuses with `PermissionError` naming the
inversion, and no genome is activated.

`fitness._gate_failures(genome)` is now the one composed definition of the
correctness gates — per-benchmark thresholds plus the transfer-inversion
rules — and every consumer asks it: `compute_fitness` (fitness zeroing,
replacing its private two-call composition), `passes_hard_gate` (retrodiction
false-negative accounting, so a candidate that inverts is not counted as a
filter false negative), `promotion.selection_eligibility` (champion
selection and governed promotion), and `PopulationStore._promote` (the raw
activation transition `promote_audited` wraps). #104's acceptance asks that
benchmark pass/fail is host-owned "before results are published or fed into
M4 fitness/promotion" — a gate that only reached fitness could not stop a
cold-start activation, which is exactly what the probe demonstrated.

Rule 2 (an approved promotion candidate carries transfer evidence for every
scored benchmark — SPEC-281 §2, "stale is acceptable, absent is not") now
binds the promotion path too, so the fixture builders in
`test_population_audit.py`, `test_promotion_governance.py`,
`test_archive.py`, and `test_rsi_safety.py` stamp that evidence alongside
the existing #854 stamps; no assertion or test name changed. The same stamp
was required by the two `formal/models` RSI conformance suites
(`test_rsi_audit_trail_conformance.py`, `test_rsi_rollback_conformance.py`;
run nightly by `formal-conformance-nightly.yml` with `maistro-evolve`
installed) — their legitimately-promotable fixtures initially hit the new
Rule-2 refusal (7 failures: "promotion candidate lacks transfer evidence
for proxy_ifeval") and were stamped identically; 10/10 pass, again with no
assertion or test name changed. One fixture
assumption was corrected rather than papered over: in
`test_production_cycle_repeats_evaluation_and_folds_ema` the fresh candidate
`g` rode the helper's `approved=True` default, which contradicted both the
test's own commentary (a candidate under evaluation is not yet approved) and
the SPEC-281 §2 duty binding promotion candidates; it is now
`approved=False`, which also makes the test's fitness commentary literally
true instead of coincidentally passing on all-zero fitness ties.

Fail-then-pass, re-executed by swapping the three source files against
commit `2d5525c4fa`: 6 of the 7 new `TestPromotionPathGate` nodes fail
pre-repair (the seventh pins that a carried transfer sample still unlocks
promotion — the over-blocking guard, intentionally green on both sides).

Post-repair battery:

- `pytest packages/maistro-evolve/tests -q` → **1189 passed, 6 skipped**
  (was 1182 before the 7 new nodes);
- `pytest packages/maistro-rsi/tests -q` (imports `maistro_evolve`) →
  **1729 passed, 4 skipped**;
- consumer sweep beyond the evolve suite: the only other `maistro_evolve`
  importers are `packages/hive-conductor/backend` (uses `get_champion` and
  the promotion path via `services/evolution.py`) and `formal/models`
  (above). `hive-conductor`'s evolution/optimizer/graph-runner tests all
  pass unchanged (**263 passed** across `test_evolution_*`,
  `test_optimizer*`, `test_dags_routes`, `test_graph_runner`,
  `test_optimizer_candidate_apply`); `maistro_core`'s
  `promote_audited` is the graph-template domain (unrelated);
- `pytest formal/models/test_rsi_audit_trail_conformance.py
  formal/models/test_rsi_rollback_conformance.py -q` (needs
  `PYTHONPATH=packages/maistro-evolve/src` locally; CI installs the
  package) → **10 passed**;
- `scripts/check-suite-inventory.py` → ok, this note's suite at **1195
  collected nodes** (651 folded + note deltas);
- `ruff check .` and `ruff format --check .` → clean;
- radon/vulture/execution-lifecycles/model-egress ratchets re-run against
  `origin/develop` → unchanged and passing (see the final validation block
  below).

## Independent verification round (2026-11-26, same lane, verifier+writer)

Every claim above was re-executed from the committed tree at `a82db87205`
before this section was written; nothing was taken on trust. Results:

- `pytest packages/maistro-evolve/tests -q` → **1189 passed, 6 skipped**
  (exact match); `pytest packages/maistro-rsi/tests -q` → **1729 passed,
  4 skipped** (exact match); the two `formal/models` RSI conformance suites →
  **10 passed**; `ruff check .` / `ruff format --check .` → clean;
  `check-suite-inventory.py` → ok, this suite at **1195** collected nodes;
  radon (0 new / 0 regressed / 0 stale), vulture (1302/1302, CI-exact args),
  execution-lifecycles (19/19), model-egress, direct-effects, and
  foreign-harness-egress gates all re-run green against `origin/develop`.
- Both fail-then-pass reproductions re-executed with the repaired sources
  shadowed out via pytest's ini `pythonpath` (file copies under `/tmp`, no
  git history operations): round 1 — the `2d5525c4fa` module against
  `8220813611`'s `fitness.py` fails **14/28**, passes **28/28** with the
  repaired `fitness.py`; round 2 — the 7 `TestPromotionPathGate` nodes
  against the `2d5525c4fa` sources fail **6/7**, pass 7/7 on the repaired
  tree. Numbers match the claims above exactly.
- Consumer sweep re-run: the hive-conductor evolution/optimizer/graph-runner
  set as named above measures **272 passed** today (the note recorded 263;
  the delta is develop-side test drift in files this branch does not touch —
  every file in the named set passes unchanged).
- Four production-path probe scripts (no test helpers, `/tmp` only)
  confirmed reachable behavior, not just suite agreement: (1) a measured
  transfer inversion with human approval and no incumbent is refused by
  `PopulationStore.promote_audited` (`PermissionError` naming the inversion,
  no genome active) and by `promotion.selection_eligibility`, while a
  carried positive sample still promotes — the over-blocking guard holds;
  (2) `run_conformance()` holds on all four graders (0 hostile accepted,
  4/4 mutants killed), spoofed/prose/negated/empty responses score 0.0 on
  every production grader, and `require_conformance` raises on a doctored
  report; (3) `EvolutionCycle.run_cycle` with `evidence_dir` publishes a
  manifest that `verify_evidence_manifest` accepts, a tampered result row
  and a removed metering section are both detected, and no target means no
  writes; (4) `attach_run_metering` stamps the block without rewriting
  adapter `metadata`, is idempotent, unresolved violations fail
  `metering_gate_failures`, and ARC-AGI grading is exact-match with spoof
  detection while `available()` honestly reports the absent corpus.
- The documented run-id collision limitation was re-observed live (two
  fresh `EvolutionCycle` instances at the same cycle count write the same
  `<genome>-cycle-<n>` directory); limitations 2 (publishing a manifest
  whose metering carries an unresolved violation) and the epic-remaining
  scope (ARC-AGI-3 corpus/evaluation run, real external-harness matched
  comparisons, fresh-workspace controls) stand as recorded — no new
  limitation found this round.

No test was added, removed, or moved in this round (docs-only append), so
the `inventory-delta` above is unchanged.
