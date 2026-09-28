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

**Status:** Superseded  
**Last updated:** 2026-09-28  
**Next steps:** None in ADR-002. Use the active pre-1.0 development standards and current repository governance for new work.  
**Current state:** The original fixed 12-step porting ceremony is historical. Its specification, meaningful-testing, verification, and traceability principles remain useful, but mandatory ADR-only review staging, `integration` targeting, sequential numbering, and manual ceremony no longer govern pre-1.0 development.  
**ADR:** [ADR-002: Per-port spec-first workflow](../../../adr/ADR-002-porting-workflow.md)
