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

## ADR-046: Scheduler — Recurring agent tasks

**Status:** Superseded  
**Last updated:** 2026-09-28  
**Next steps:** None. Follow ADR-082126-f69c: recurrence produces canonical Runs rather than owning a second scheduler execution lifecycle.  
**Current state:** ADR-046 is explicitly superseded and records that its APScheduler/TaskRecord-centered mechanism was never the canonical implementation. Its durable/timezone/max-runs requirements informed the successor, but its execution mechanism must not be revived. Note that ADR-044's historical reference to a future "ADR-046" for Canvas legacy deletion is stale because this ID belongs to Scheduler.  
**ADR:** [ADR-046: Scheduler — Recurring agent tasks](../../../adr/ADR-046-scheduler.md)

## ADR-052: Parallel agent waves — per-wave branch isolation and fan-in merge

**Status:** Deprecated  
**Last updated:** 2026-09-28  
**Next steps:** No implementation work against ADR-052. Remove its unreachable fan-in/shadow-git island during convergence cleanup. Any current parallel-agent execution must be designed on the canonical Graph/Run/workspace architecture rather than reconnecting this deprecated lifecycle.  
**Current state:** Reachability analysis proved the implementation was never connected, and the design depends on deprecated ADR-049 shadow-git machinery. It was correctly moved from an implementation claim to Deprecated with no successor; ADR-062 addresses a different traversal concern and does not revive this filesystem-wave model.  
**ADR:** [ADR-052: Parallel agent waves — per-wave branch isolation and fan-in merge](../../../adr/ADR-052-parallel-agent-waves.md)

## ADR-053: Recipe overlay composition — engine simple + product overlay

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR that carries the useful composition rules into the current Persona/Template/Capability-Binding architecture: deterministic schema-driven overrides, explicit versioned code references where still applicable, and non-overridable security-sensitive fields. Do not preserve RecipeRegistry compatibility as a goal. Once the successor is accepted, transition ADR-053 to `Superseded`.  
**Current state:** ADR-053 is built on the stale ADR-006 RecipeRegistry and ADR-035 catalog model, and one acceptance criterion explicitly requires backward compatibility with ADR-006. That conflicts with both current architecture and the pre-1.0 rule that compatibility has no positive design weight. The composition/governance idea remains useful, but the owning abstraction must change.  
**ADR:** [ADR-053: Recipe overlay composition — engine simple + product overlay](../../../adr/ADR-053-recipe-overlay-composition.md)
