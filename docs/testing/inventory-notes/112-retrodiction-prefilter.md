---
inventory-delta:
  packages/maistro-evolve/tests: +17
---

# Retrodiction prefilter before expensive evaluation (#112, M4-A5)

Adds `maistro_evolve.retrodiction` and wires it into the evaluation spend
points, with 17 focused tests in `packages/maistro-evolve/tests/test_retrodiction.py`
(+17 to that package's suite; no tests removed or renamed).

What the tests pin down, mapped to the issue's acceptance criteria:

1. **Versioned/addressable traces, deterministic replay** — `genome_fingerprint`
   determinism/sensitivity (payload-only, node-order normalized, weights
   excluded), `TraceLedger` trace_id addressability, schema versioning, stub
   evidence refusal (SPEC-202), and `replay()` returning the latest trace per
   benchmark identically on repeated calls.
2. **Decisions record why** — allow (`no_prior_evidence`, `partial_prior_evidence`),
   reject (`prior_total_failure`, citing resolvable trace ids), deprioritize
   (`duplicate_of_scored_payload`, `repeat_already_scored`), each persisted on
   the genome as `harness_params["retrodiction"]`.
3. **Measured false-negative risk** — `observe_outcome` counts deprioritized
   candidates that later pass full evaluation as false negatives;
   `shadow` mode records reject verdicts while still evaluating everything, so
   the false-negative rate is directly measurable before enforcement; the
   cycle test reconciles a shadow-rejected candidate that was really evaluated.
4. **Promotion untouched** — after fully exercising the prefilter across two
   cycles, no genome carries `approved_for_promotion`/`is_active`;
   `promote_audited` still raises `PermissionError` with only a
   `promotion_attempt` audit entry. Rejected candidates stay scoreless
   (gate-failed fitness 0.0) and cannot win tournaments or breed.
5. **Measured savings** — `evals_saved`/`cost_saved_usd`/`runtime_saved_seconds`
   on the decision and in `EvolutionCycle.prefilter_stats`; the cycle test
   proves a known-total-failure repeat is skipped with zero harness calls in
   cycle 2 while the ledger persists across `run_cycle()` calls.

Also covered: the frontier-verification spend points (`reflect._evaluate_candidates`,
`hyper_mutator.hyper_mutate`) skip known-failure repeat proposals without a
model call and record their novel verifications back into the ledger, and
`retrodiction: "off"` restores the exact pre-#112 behavior (no prefilter stats,
no decisions recorded, duplicates re-evaluated).
