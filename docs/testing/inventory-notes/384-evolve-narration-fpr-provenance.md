---
inventory-delta:
  packages/maistro-evolve/tests: +28
---

# Evolve narration-proof fitness: adversarial calibration + evidence provenance (#384)

M4-C: remove the gameable text-mention/fuzzy-substring fallbacks from the Evolve
proxy fitness. Net effect on the test inventory: 716 → 744 collected tests in
`packages/maistro-evolve/tests` (+28).

## What the tests pin

- `tests/benchmarks/test_gaia.py` — `TestExactMatchScore` rewritten from pinning
  the fuzzy tiers (substring 0.9 / digit-set 0.85 / word-overlap 0.7) to pinning
  their removal: only normalized/numeric exact equality earns the unjudged point;
  narration quoting the expected answer, digit-set coincidences, word overlap and
  empty samples all score 0.0. New `TestRunGaia` cases: narration goes to the
  judge and scores judged-only (no `max(exact, judged)` inflation), judge failure
  is fail-closed 0.0 (never the heuristic), `judge_llm_call` override is the
  verification channel, and evidence metadata counts exact vs judge-verified.
- `tests/benchmarks/test_ragas.py` — the "high static score skips the judge"
  tests are inverted: the judge now runs for every sample, a near-perfect-overlap
  response judged low scores low (no `max`), the static overlap is reported as an
  explicitly uncredited diagnostic, and the `judge_llm_call` override is pinned.
- `tests/benchmarks/test_adversarial_calibration.py` (new) — the narration
  fixtures really contain everything the old fallbacks matched on; the
  `calibrate_proxy_scorers()` report shows `narration_false_positive_rate == 0.0`
  and `verified_positive_rate == 1.0` for all four scorers (bfcl, tau_bench,
  gaia, ragas) over the real sample sets; a monkeypatched gameable runner
  surfaces as a nonzero FPR (the report measures, it does not hardcode); tau
  narration unit-level zero + structured-call 1.0.
- `tests/test_champion_provenance.py` (new) — `harness.evidence_method()` string
  extraction (dict/str/missing/empty → "unverified"), cycle folding of evidence
  alongside scores (including the unverified record for evidence-less results),
  and `PopulationStore.champion_provenance()` exposing score→evidence for the
  max-fitness champion.
- `tests/benchmarks/test_tau_bench.py` — two metadata equality pins extended with
  the new `evidence` record.
- `tests/test_serialize.py` — `_genome()` fixture sets the new `eval_evidence`
  field so the block-style YAML pin keeps covering every serialized field.

## Non-test behavior changes

`gaia.py` (exact-match-or-judge, no fuzzy tiers, no max-merge, `judge_llm_call`,
evidence metadata), `ragas.py` (judge-only credit, static overlap diagnostic,
`judge_llm_call`, evidence metadata), `bfcl.py`/`tau_bench.py` (evidence
metadata), `calibration.py` (new adversarial fixture harness reporting FPR),
`harness.py` (`evidence_method()`), `types.py` (`eval_evidence` field),
`cycle.py`/`reflect.py`/`hyper_mutator.py` (fold evidence at all three score
folds), `population.py` (`champion_provenance()`), package `CLAUDE.md` +
`__init__.py` docstrings (fidelity statements updated to match reality).
