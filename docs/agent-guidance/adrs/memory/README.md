# Memory ADRs

Progressive-disclosure index for ADRs governing durable memory, recall, learning, context assembly, and related persistence behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-011: Memory engine + session factory wiring

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-011 implementation work remains. Reconcile SPEC-212's stale `Proposed` lifecycle status against the same implementation/test evidence during the specification audit.  
**Current state:** Cached DB-optional async engine/session-factory wiring is implemented, the server lifespan initializes and disposes the engine, cache reset is wired, and focused tests cover configured/unconfigured engine creation plus usable async sessions. ADR-011 was promoted from `Accepted` to `Implemented` during this audit based on direct code and test evidence.  
**ADR:** [ADR-011: Memory engine + session factory wiring](../../../adr/ADR-011-memory-engine.md)

## ADR-013: Memory types — Learning, EpisodicMemory, Outcome, scopes, tiers

**Status:** Implemented  
**Last updated:** 2026-09-28  
**Next steps:** No ADR-013 implementation work remains. Later memory ADRs/specs should continue to treat `maistro.types.memory` and the shared scope rule as canonical rather than re-declaring these primitives.  
**Current state:** The seven-tier memory types, weight bounds, Learning/Outcome/EpisodicMemory domain types, and tenant-aware scope filtering are implemented and directly tested. Subsequent work has extended these types and added shared Python/SQL scope-conformance enforcement without invalidating ADR-013's original invariants.  
**ADR:** [ADR-013: Memory types — Learning, EpisodicMemory, Outcome, scopes, tiers](../../../adr/ADR-013-memory-types.md)
