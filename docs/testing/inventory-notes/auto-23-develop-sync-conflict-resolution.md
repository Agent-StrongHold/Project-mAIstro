---
inventory-delta:
  packages/maistro-evolve/tests: -2
---
# auto-23 develop-sync conflict resolution

The previous block left a mid-flight merge of develop into auto-23 with seven
unresolved conflicts (cycle.py, fitness.py, population.py, local_loop.py,
test_rsi_safety.py, test_live_evolution.py, and the #853 inventory note
itself); every driver check failed only because the conflict markers made the
files unparseable. This round resolved all seven semantically, merged the
newer develop tip (257e1d99), and re-proved the gate battery. No tests were
added or removed by the merge: comparing complete per-file collected node-ID
sets, the merged tree is a strict superset of both parents
(`415acd24b` and `5765efce`) — zero test functions present in either parent
are absent after the merge.

## Provenance of the −2

`expected = baseline(629) + Σ note deltas` over-counts by exactly 2 because
the two lineages recorded the same review corrections in different notes, and
the merge keeps one copy of each test:

- `+1` — `test_objective_weight_mapping_is_read_only` is counted twice: once
  inside develop's `853-evolve-fitness-ownership` delta (+43, whose prose
  names the "late review addition" explicitly) and once in this branch's
  `auto-23-9725` reconciler (+1, "the #853 review driver-commit added
  `test_objective_weight_mapping_is_read_only` without recording an inventory
  delta on its own lane"). The test exists once in the merged
  `test_fitness_ownership.py`; the notes sum it twice.
- `+1` — the same pair of notes both re-measure the #853 series delta:
  `auto-23-9725` records "+1 — the 853 note records +39, but the ported #853
  series collects +40 over the same base", while develop's version of the 853
  note was re-measured on its side to +43 (it subsumes the same correction in
  its own count). After the merge only develop's note text survives (it won
  the both-added conflict as the superset), but the branch-only `auto-23-9725`
  note still contributes its +1 alongside it.

Measured: `expected 868, collected 866` at the merge commit; the −2 here
records the double-count so the ledger matches what actually collects. The
shared `inventory/baseline.json` is unchanged, and no other suite moved
(`check-suite-inventory.py` reports all remaining suites ok).
