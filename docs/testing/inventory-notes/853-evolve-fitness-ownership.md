---
inventory-delta:
  packages/maistro-evolve/tests: +35
---

# Evolve fitness is population-owned, missing-data-pessimistic, capability-grounded (#853)

## What changed

The scoring ruler moved out of the genome and into a campaign-owned, frozen,
versioned `objective.EvaluationObjective` (`DEFAULT_OBJECTIVE` carries the
pre-#853 weight values verbatim — the issue's stop condition forbids tuning
weights before ownership/missing-data semantics are corrected). Concretely:

- `fitness._weighted_eval_score` reads the objective's benchmark weights and
  never `genome.eval_weights`; the genome's weight field is inert legacy
  schema. `mutate.mutate_eval_weights` is a loud tombstone (raises
  `NotImplementedError`) and is out of `mutate_all`; `crossover` no longer
  averages the parents' weight vectors.
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
- `PopulationStore._promote` additionally fails closed on measured capability
  evidence (`fitness._check_hard_gate`) — a do-nothing/NotImplemented
  candidate cannot be promoted regardless of missing metrics or objective
  reweighting (the audited compensation path restores with
  `require_capability=False`; the approval gate always applies).

## Test delta (+30)

- `tests/test_fitness_ownership.py` (new, 29): objective ownership (genome
  reweighting attack is dead; frozen objective; mutation/crossover cannot move
  the ruler; cycle scores one campaign objective), missing-data pessimism
  arithmetic, degenerate/malformed evidence boundaries (zero avg_elo with
  battle counts, Elo band clamps, non-numeric evidence fields score missing
  credit without crashing), non-tradeable gates under an adversarially
  generous objective, role separation, deterministic recomputation/order-independence/hash
  sensitivity, literal calibration pins that kill swapped weights, restored
  missing→1.0 freebies, reinstated default-Elo awards, and removed gates, and
  the re-battle-without-improvement tenure probe.
- `tests/test_fitness.py` (+3): missing/zero cost and latency are unknown
  (`None`), Elo requires battle evidence, capability immunity to context
  terms; weight-sum pin moved to the objective.
- `tests/test_rsi_safety.py` (+3): `TestCapabilityPromotionGate` — never-
  evaluated and gate-failing genomes refuse promotion even with padded
  harness evidence; a reweighted objective cannot rescue a gated candidate.
- `tests/test_mutate.py` (net 0): the two weight-mutation operator tests are
  replaced by a tombstone test and a `mutate_all` never-touches-weights test.
- `tests/test_crossover.py` (net 0): weight-averaging test replaced by a
  does-not-mix (inherits parent_a verbatim) test.
