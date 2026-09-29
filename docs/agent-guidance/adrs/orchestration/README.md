# Orchestration ADRs

Progressive-disclosure index for ADRs governing scheduling, selection, orchestration, execution coordination, and related runtime control behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-007: VariantSelector (Thompson sampling)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Add acceptance-strength tests that exercise the real seeded Thompson-sampling path and demonstrate that a strongly successful variant is favored after sufficient outcomes without replacing `random.betavariate` with a deterministic stub. Verify deterministic behavior under `random.seed()`, run the focused suite, then transition ADR-007 to `Implemented` if the full acceptance set passes.  
**Current state:** VariantSelector is implemented with round-robin warm-up, exploration, Beta-distribution Thompson sampling, outcome bookkeeping, and optional Langfuse-backed statistics. Current tests strongly cover control flow and bookkeeping, but they mock the sampler for winner selection and therefore do not yet prove the ADR's actual statistical-favoring and seedability criteria.  
**ADR:** [ADR-007: VariantSelector (Thompson sampling)](../../../adr/ADR-007-variant-selector.md)

## ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether reserved-capacity LIVE/BACKGROUND scheduling remains a requirement under the canonical durable Run/worker architecture. If it remains required, replace the obsolete TaskRunner-slot design with a current spec and implementation that preserves the latency-isolation invariant; if it is no longer desired, create or identify the withdrawing/successor ADR and transition ADR-010 accordingly.  
**Current state:** The accepted ADR describes a TaskRunner split into reserved live/background worker slots, but repository search finds no implementation of those slots and SPEC-211 still has the corresponding criteria unchecked. Newer campaign/priority architecture does not supersede this decision because it explicitly does not add a scheduler, so ADR-010 is currently an accepted but apparently unimplemented scheduling requirement tied to an obsolete execution shape.  
**ADR:** [ADR-010: Lane-based scheduling (LIVE vs BACKGROUND)](../../../adr/ADR-010-lane-scheduling.md)
