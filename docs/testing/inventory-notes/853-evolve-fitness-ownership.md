---
inventory-delta:
  packages/maistro-evolve/tests: +43
  packages/maistro-rsi/tests: +2
---

# Evolve fitness is population-owned, missing-data-pessimistic, capability-grounded (#853)

## What changed

The scoring ruler moved out of the genome and into a campaign-owned, frozen,
versioned `objective.EvaluationObjective` (`DEFAULT_OBJECTIVE` carries the
pre-#853 weight values verbatim — the issue's stop condition forbids tuning
weights before ownership/missing-data semantics are corrected). Concretely:

- `fitness._weighted_eval_score` reads the objective's benchmark weights and
  never `genome.eval_weights`; the genome's weight field is inert legacy
  schema. The `mutate_eval_weights` operator is removed outright (CI-repair
  pass: an uncalled raising tombstone is dead code, and the per-identity
  vulture ledger ratchet now guards re-introduction); `mutate_all` has no
  weight operator and `crossover` no longer averages the parents' weight
  vectors.
- Missing cost/latency/Elo evidence is `None` on `FitnessComponents`, named in
  `missing_evidence`, and scored with the objective's pessimistic
  `missing_evidence_credit` (0.0) — absence is never a perfect 1.0 anymore.
- Correctness hard gates stay non-tradeable constraints: a gate failure zeroes
  `total` and `capability_score` under any objective weighting. New
  `capability_score` is the gated measured task quality; Elo/diversity are
  role-tagged context terms (`COMPONENT_ROLES`) that can never move it.
- The Elo term fires only on recorded battle evidence (`elo_battles` > 0,
  written by `cycle._run_tournament_battles`); the old default-1200 freebie for
  never-battled genomes is gone.
- `FitnessComponents` records `objective_version` and a sha256
  `evidence_hash` over the exact inputs (scores, cost/latency/Elo evidence,
  population trait evidence, objective); scoring iterates sorted items so the
  same evidence recomputes bit-identical fitness in any cycle.
- CI-repair pass: the cycle enforces that contract at runtime —
  `EvolutionCycle.fitness_evidence` keeps the latest `FitnessEvidenceRecord`
  per genome (total, capability, objective version, evidence hash,
  missing-evidence names, component roles) and
  `_check_fitness_recomputability` raises `FitnessEvidenceDriftError` if a
  score moves while hash + version are unchanged. Identical evidence across
  cycles can never manufacture a gain; any movement names its recorded
  reason. The objective's defensive weight copy is expressed as an anonymous
  `BeforeValidator(dict)` so the framework-registered copy step cannot
  masquerade as dead code.
- `PopulationStore._promote` additionally fails closed on measured capability
  evidence (`fitness._check_hard_gate`) — a do-nothing/NotImplemented
  candidate cannot be promoted regardless of missing metrics or objective
  reweighting (the audited compensation path restores with
  `require_capability=False`; the approval gate always applies).

## Test delta (+43 evolve, +2 rsi; diff-coverage CI-repair round)

The original 41, plus the two suites the CI diff-coverage gate measured below
its floor, both pinning the two promotion/battle-evidence refusal paths the
diff introduced but no public path reaches:

- `tests/test_fitness_ownership.py` (new, 30): objective ownership (genome
  reweighting attack is dead; frozen objective; mutation/crossover cannot move
  the ruler; cycle scores one campaign objective), missing-data pessimism
  arithmetic, degenerate/malformed evidence boundaries (zero avg_elo with
  battle counts, Elo band clamps, non-numeric evidence fields score missing
  credit without crashing), non-tradeable gates under an adversarially
  generous objective, role separation, deterministic recomputation/order-independence/hash
  sensitivity, literal calibration pins that kill swapped weights, restored
  missing→1.0 freebies, reinstated default-Elo awards, and removed gates, and
  the re-battle-without-improvement tenure probe. One late review addition:
  `test_objective_weight_mapping_is_read_only` pins that the objective's
  benchmark-weight mapping cannot be mutated in place (including on the
  shared `DEFAULT_OBJECTIVE`).
- `tests/test_fitness.py` (+3): missing/zero cost and latency are unknown
  (`None`), Elo requires battle evidence, capability immunity to context
  terms; weight-sum pin moved to the objective.
- `tests/test_rsi_safety.py` (+3 → +5): `TestCapabilityPromotionGate` — never-
  evaluated and gate-failing genomes refuse promotion even with padded
  harness evidence; a reweighted objective cannot rescue a gated candidate.
- `tests/test_cycle.py` (+4): `TestFitnessEvidenceLedger` — identical
  evidence recomputes identically and is recorded (same-cycle double pass
  does not raise); a score drift under unchanged hash+version raises
  `FitnessEvidenceDriftError`; real evidence changes and governed objective
  swaps re-record without raising.
- `tests/test_mutate.py` (net 0): the two weight-mutation operator tests are
  replaced by an operator-absence pin and a `mutate_all`
  never-touches-weights test.
- `tests/test_crossover.py` (net 0): weight-averaging test replaced by a
  does-not-mix (inherits parent_a verbatim) test.
- `tests/test_cycle_gaps.py` (+1):
  `test_run_tournament_battles_clears_inherited_elo_without_battles` — review
  fix: crossover/mutation deepcopy the parent's harness evidence, so a child
  that sat out the tournament inherited its Elo evidence; the cycle now pops
  the inherited Elo keys when the child fought zero battles.

## develop-merge reconciliation (this branch)

Merged `origin/develop` (c0582c4ae, carrying #852 anchored-judge/benchmark
integrity and #854 governed promotion) into the branch. The two features
compose rather than compete:

- The #853 capability gate (`fitness._check_hard_gate`) now also runs inside
  #854's `promotion_eligibility`/`selection_eligibility` (which import it
  directly) and remains defense-in-depth in `PopulationStore._promote`
  (`require_capability=True`; the audited compensation path restores with
  `require_capability=False`). `TestCapabilityPromotionGate` in
  `tests/test_rsi_safety.py` was updated to pin the merged refusal shape:
  the governed promotion policy refuses first and names the hard-gate reason
  (e.g. `hard gate: proxy_ifeval score 0.100 below gate 0.25`); the
  reweighting-rescue test now carries complete #854 evidence so the ONLY
  remaining refusal is the weight-blind threshold gate.
- `fitness.py` keeps the #853 `COMPONENT_ROLES`/objective-owned weights and
  gains #854's `hard_gate_thresholds()` accessor (the pre-#853
  `_FITNESS_WEIGHTS` dict is retired — its values live verbatim in
  `objective.FitnessTermWeights`).
- The two objective-version notions remain distinct and both recorded: #854's
  `promotion.objective_version` digest (benchmarks + gate thresholds +
  weights) stamps evidence identity for promotion comparison; #853's
  `objective.EvaluationObjective.version` (`pop-owned-v2`) is recorded on
  every `FitnessComponents` with the evidence hash.

## CI-repair pass (this branch)

- `formal/models/test_rsi_{audit_trail,rollback}_conformance.py`: the #853
  capability promotion gate correctly refuses unevaluated genomes, so the
  models' fixture genomes now carry one passing benchmark score — the models
  audit the promote/rollback *trail* and need legitimately promotable
  fixtures. `formal/fixtures/security_oracle.json` is untouched (oracle
  independence holds).
- `quality/vulture-baseline.json`: pruned the three retired
  `FitnessComponents` efficiency/weight identities. The five new record
  fields have production readers (the cycle evidence ledger) and the
  tombstone function was removed outright, so no new identity needed
  banking — net vulture debt shrank by 3.

## CI-repair round 2: diff-coverage floor (this branch)

CI's Coverage gate failed the per-file diff-coverage step at 172ecfbe on two
files (`population.py` line 206 uncovered; `local_loop.py` 50% of 2 branch
arcs at 2068) while the publish-set floor passed. Reproduced locally against
the same base (4e7ef1ab1) with the same producer flags; both were genuine
test-evidence gaps in this change's own guard rails, not measurement noise:

- `population.py:206` is `_promote`'s capability-gate `PermissionError`.
  Since #854 the governed policy (`promotion_eligibility`) refuses first via
  the same `_check_hard_gate`, so no public path reached the defense-in-depth
  raise. Two tests pin the guard at its own layer:
  `test_raw_transition_gates_capability_out_from_under_the_policy` (a future
  caller bypassing the governed entrypoint cannot flip a gate-failing genome
  active) and `test_compensation_restore_skips_capability_never_approval`
  (the `require_capability=False` restore path still enforces the
  human-approval gate unconditionally).
- `local_loop.py:2068` is `_record_cycle_battles`'s `if battles > 0:` — the
  unmeasured arc was the FALSE branch: a fought variant with zero recorded
  battles. `test_zero_battle_variant_writes_no_elo_evidence` pins that it
  gains neither `avg_elo` nor `elo_battles` (the #853 freebie removal), and
  `test_same_slot_battle_writes_elo_evidence_for_both_fighters` pins the
  positive half.
- Writing the positive-half test exposed a real defect in the battle-
  evidence gate itself: with a DB-backed `PopulationStore`, `list_all()`
  deserializes fresh objects, so the harness_params mutation landed on a
  throwaway copy and the Elo evidence was never persisted — the gate could
  not actually feed `compute_fitness` after a restart, and even in-process
  `get()` returned the un-evidenced original. `_record_cycle_battles` now
  writes the genome back via `store.add(genome)`, the same write-back the
  adjacent `_fold_cycle_scores` performs for the same reason. No gate or
  threshold changed; the evidence the gate records is now durable.

Post-fix local gate evidence: `scripts/check-diff-coverage.py coverage.xml
--base 4e7ef1ab1` → ok (evolve 776+6skipped, rsi 788, hive-conductor 3013+6,
all under the CI producers' exact `--source` flags); suite-inventory
re-recorded via `--update --note 853-evolve-fitness-ownership` (+43 evolve,
+2 rsi); vulture ratchet clean at 1380 banked findings; ruff clean.
