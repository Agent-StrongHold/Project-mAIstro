# Development & Repository Architecture ADRs

Progressive-disclosure index for ADRs governing repository workflow, branching, and development process.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-001: Branching strategy — integration as default PR base

**Status:** Superseded  
**Last updated:** 2026-09-28  
**Next steps:** None. Follow ADR-095 for the active branch and promotion model.  
**Current state:** ADR-001 is historical. ADR-095 explicitly supersedes it; the live topology is `topic branches -> develop -> main`, and the former `integration` branch is retired.  
**ADR:** [ADR-001: Branching strategy — integration as default PR base](../../../adr/ADR-001-branching-strategy.md)

## ADR-002: Per-port spec-first workflow

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR defining the canonical pre-1.0 agent-native development workflow. Once that successor is accepted, transition ADR-002 to `Superseded` and set `superseded-by` to the successor ADR.  
**Current state:** ADR-002 remains lifecycle-valid `Accepted`, but parts of its fixed 12-step ceremony are stale against current standards and repository topology. Specification-first intent, meaningful tests, verification, and traceability remain useful; mandatory ADR-only review staging, the retired `integration` target, sequential numbering, and routine manual ceremony are not current operating guidance.  
**ADR:** [ADR-002: Per-port spec-first workflow](../../../adr/ADR-002-porting-workflow.md)
