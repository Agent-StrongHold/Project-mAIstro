---
inventory-delta:
  packages/maistro-evolve/tests: +0
  packages/maistro-rsi/tests: +0
---
# auto-115 repair: develop sync, radon floors after attribution merge

The round inherited (a) a preserved mid-flight develop merge with one
unresolved conflict, (b) the Quality gate (Pillars 1–4, 7, 8) failure, and
(c) the exact-debt-ledger repair mandate. No tests were added or removed —
suite inventory unchanged (evolve 922, rsi 852, both matching
`docs/testing/inventory/baseline.json`).

## Develop sync resolution

Two merges bring the branch onto `origin/develop` (045cfdfbe):

1. Completing the preserved merge of 8c8fc8d6: `reflect.py` kept both the
   M4-A8 attribution import and develop's `evidence_method` (both are used
   in the merged body).
2. Merging 045cfdfbe on top: `reflect.py`/`hyper_mutator.py` import blocks
   and the `EvolutionConfig` field block (attribution knobs + `retrodiction`)
   are additive on both sides, so both sides were kept. Ledger JSON merged
   without row loss: the only rows removed relative to either parent are the
   ones that parent itself eliminated (branch: five dead-code fixes;
   develop: `types.py::passed_hard_gate` / `samples_evaluated`, whose code
   moved to `lane_comparison.py`/`fitness.py` in the same merge).

## Radon floors after the merge (refactor, not grants)

Merging attribution stamping into develop's code pushed three blocks over
their baselines. Each was refactored down instead of granted, and the
improvements banked in `quality/radon-baseline.json`:

- `cycle.py::EvolutionCycle._breed_island` 22 → 16: the duplicated
  crossover+register+island-placement block became `_spawn_island_child`,
  shared by both breeding paths (attribution stamping cannot drift apart).
- `mutate.py::mutate_topology` 21 → 15: the two random edge mutations moved
  into `_rewire_edges(topo, rate)`.
- `crossover.py::crossover` 14 → 13: parent-edge rewiring moved into
  `_rewire_parent_edges(edges, node_id_map)`.

Vulture ledger needed no amendment: the refactors moved code without
removing any banked identity (gate re-run post-refactor: 1360 reviewed →
1355 findings, exact match).

## Test-stub scoping after the merge

Develop's evidence-folding characterization tests build inline `_Cfg` stubs
that predate the `producer_attribution` config field, so `_evaluate_unevaluated`
raised `AttributeError`. The two stubs now declare
`producer_attribution=False` with a comment: those tests pin evidence
folding (#854), not producer credit, and their assertions stay scoped
accordingly. Assertion bodies unchanged.

## Gates re-proven locally (CI-exact arguments where they exist)

ruff check/format; check-radon-baseline; xenon (145 = floor, no module/avg
violations); check-vulture-baseline (exact ledger); mypy --strict core;
pyright ratchet (21 = baseline); formal/ property suite (663 passed);
acceptance-state ratchet with pg18 (`--run-tests --ratchet`, then banked
`quality/ac-state-notes/auto-115.json` for the bounds the sync tightened);
bandit 0 Medium+; semgrep 0 findings; suite inventories evolve/rsi;
full evolve (916 passed) + rsi (852 passed) suites; interrogate battery;
coverage on the three refactored files 96–100% (lines+branches).
