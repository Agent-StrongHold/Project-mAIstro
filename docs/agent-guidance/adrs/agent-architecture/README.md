# Agent Architecture ADRs

Progressive-disclosure index for ADRs governing agent identity/specification, composition, recipes, selection, spawning, and related agent architecture.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-003: Agent runtime gap analysis (archived branch resolution)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the five original gap claims against their owning ADRs/specs as those records are audited; do not use the 2026-04-26 gap-status table as current implementation truth.  
**Current state:** ADR-003 is an accepted historical runtime-gap analysis and backlog mapping, not a current implementation inventory. Memory has materially advanced beyond the original "schema defined, not wired" state, while closure of identity, workspace context, scheduled autonomy, and runtime skill composability must be established from their owning architecture records and current implementations rather than inferred from this roadmap ADR.  
**ADR:** [ADR-003: Agent runtime gap analysis (archived branch resolution)](../../../adr/ADR-003-agent-runtime-gap-resolution.md)

## ADR-004: AgentSpec + AgentOutput envelopes

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Bring completion-duration evidence into compliance with the ADR: ensure a completed `AgentOutput` reliably records `duration_ms > 0`, strengthen the test from `>= 0` to `> 0`, verify the full ADR-004 acceptance set, then transition the ADR to `Implemented`.  
**Current state:** The typed agent request/response envelope is implemented and dedicated tests cover defaults, unique IDs, JSON round-trip, error recoverability, and completion timing. The implementation is not yet being promoted because the current timing test permits zero-duration completion while the accepted ADR requires a positive duration.  
**ADR:** [ADR-004: AgentSpec + AgentOutput envelopes](../../../adr/ADR-004-agent-spec.md)
