# Orchestration ADRs

Progressive-disclosure index for ADRs governing scheduling, selection, orchestration, execution coordination, and related runtime control behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-007: VariantSelector (Thompson sampling)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Add acceptance-strength tests that exercise the real seeded Thompson-sampling path and demonstrate that a strongly successful variant is favored after sufficient outcomes without replacing `random.betavariate` with a deterministic stub. Verify deterministic behavior under `random.seed()`, run the focused suite, then transition ADR-007 to `Implemented` if the full acceptance set passes.  
**Current state:** VariantSelector is implemented with round-robin warm-up, exploration, Beta-distribution Thompson sampling, outcome bookkeeping, and optional Langfuse-backed statistics. Current tests strongly cover control flow and bookkeeping, but they mock the sampler for winner selection and therefore do not yet prove the ADR's actual statistical-favoring and seedability criteria.  
**ADR:** [ADR-007: VariantSelector (Thompson sampling)](../../../adr/ADR-007-variant-selector.md)
