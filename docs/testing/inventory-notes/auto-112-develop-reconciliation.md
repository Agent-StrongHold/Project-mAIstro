# auto-112 — develop reconciliation + CI gate repair (M4-A5 retrodiction prefilter)

inventory-delta:
  branch: auto-112
  base: b4b9e187e29b44cc9f567fe9c15c14cb514844cb (origin/develop tip, merged in commit f06f33953)
  suites:
    packages/maistro-evolve/tests: 0   # still 799 collected; matches recorded inventory
    tests/: 0                          # untouched by this branch (byte-identical to develop)
  new_notes: []
  notes: no test added or removed; two existing test_retrodiction.py cases were
    updated to the reconciled production behavior (see below), node count unchanged.

## What this round did

CI at 862ad3647 (M4-A5) failed three required jobs. This repair merges
origin/develop (b4b9e187e, 95 commits) into the branch and fixes each named
gate against evidence:

1. **Merge reconciliation (f06f33953).** Two files conflicted:
   - `cycle.py`: kept the M4-A5 prefilter path (`_decide_batch`,
     `_evaluate_one`, `EvolutionConfig.retrodiction`, per-cycle
     `RetrodictionPrefilter` over a persistent `TraceLedger`) AND develop's
     #853/#854 machinery (`FitnessEvidenceRecord` + drift guard,
     `_eval_and_fold` with objective-version/evidence-cycle stamping,
     `reconfirm_per_cycle`). `_evaluate_one` now evaluates through
     `_eval_and_fold`, so prefiltered first-evals stamp evidence currency —
     required for `selection_eligibility` to ever admit them.
   - `fitness.py`: kept `hard_gate_threshold`/`passes_hard_gate` (prefilter's
     single-source gate oracle) beside develop's objective-aware
     `_weighted_eval_score`.

2. **lint-and-type-check**: mypy union-attr at `reflect.py:334` (mypy cannot
   narrow `prefilter` through the `decisions` dict) — guarded with an explicit
   `prefilter is not None`, behavior-preserving because `_triage_candidates`
   populates `decisions` only when the prefilter exists.

3. **exact-debt-ledger**: every vulture identity the M4-A5 commit introduced
   is eliminated by load-bearing references rather than new ledger rows (new
   rows cannot be authorized from this base — grants are read from the merge
   base, and this branch cannot land one on develop first):
   - `PrefilterStats.record_verdict` owns verdict/savings accounting
     (`self.`-reads inside the defining class); `decide()` locals renamed to
     the field names they feed.
   - `TraceLedger.replay` iterates via `traces_for` (one fingerprint-index
     reader).
   - the stats log line reads `self.prefilter_stats`, so the diagnostic
     property is production-reachable.
   - pruned the stale ledger row
     `packages/maistro-evolve/src/maistro_evolve/types.py::unused variable
     'samples_evaluated'`: the merged tree reads `r.samples_evaluated`
     (retrodiction.py:158), so the finding no longer exists and the exact
     ledger must shrink with it.
   Gate proof: `uv run python scripts/check-vulture-baseline.py packages/*/src
   --min-confidence 60 --exclude '*/third_party/*'` → exit 0 (1357 reviewed
   identities → 1356 findings, base b4b9e187e).

4. **test_retrodiction.py** (existing cases, count unchanged):
   - cycle-level prefilter tests pin `reconfirm_per_cycle=0` — develop's #854
     per-cycle reconfirmation adds fresh samples that would pollute the
     harness-call accounting those tests use to prove savings; the promotion
     test keeps reconfirmation on because `get_champion` requires the #854
     independent-evidence floor.
   - the human-gate refusal now expects develop's
     `["promotion_attempt", "promotion_rejected"]` audit trail.

## Local evidence

- evolve suite: 790 passed, 6 skipped, 3 failed — the 3 are
  `tests/benchmarks/test_sandbox_exec.py` / `test_swebench.py` cases that need
  a live Docker daemon (socket present, daemon down on this box; CI runners
  have one). Not touched by this branch.
- maistro-rsi (evolve consumer): 841 passed. formal/ hypothesis: 663 passed.
- lint-and-type-check steps: monorepo layout, merge markers, ruff check +
  format, mypy (9 packages), cross-package imports — all green.
- Quality gate steps run locally (all green): radon baseline, version bump
  --check, release consistency, doc links, enumerations, workspace retirement,
  route permissions, principal identity, vendored IFEval/BFCL provenance,
  reachability + dispositions, credential authority, wiring reads, agent store
  writes, contract markers, convergence matrix, security inventory, image
  inventory/pins, backlog consistency, execution lifecycles, model egress,
  vulture ledger, mypy --strict (core), pyright (21 == baseline 21), xenon
  (66 <= 77), interrogate (4 targets), alembic upgrade head against live PG,
  acceptance-state ratchet + mandate (0 criteria touched, all proven).
- Known local-only observation, NOT caused by this branch: the root `tests/`
  suite collects 4410 nodes here vs 4392 expected — develop's own tree collects
  the identical 4410 in this environment (files byte-identical), so the drift
  is an environment-collection artifact, deliberately left unrecorded rather
  than baked into the inventory with `--update`.
