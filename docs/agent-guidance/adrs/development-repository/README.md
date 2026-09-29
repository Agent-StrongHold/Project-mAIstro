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

## ADR-019: Canonical Source Split — maistro-engine vs Stronghold

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Keep the ownership/source-of-truth map synchronized with the consolidation monorepo and later architectural amendments, especially ADR-068's scope-vs-tenancy distinction. When package/product boundaries change, update this ADR and repository guidance together rather than creating competing ownership rules.  
**Current state:** ADR-019 remains an active governance decision. The repository is now a consolidation monorepo containing maistro-core and sibling packages, while downstream/product-specific concerns remain outside the shared runtime boundary; current WAYS-OF-WORKING guidance explicitly cites ADR-019 as the canonical source split. The obsolete four-peer extension in ADR-030 has already been reversed in this record.  
**ADR:** [ADR-019: Canonical Source Split — maistro-engine vs Stronghold](../../../adr/ADR-019-canonical-source-split.md)

## ADR-030: Four-Repo Governance — Substrate + Three Templated Products

**Status:** Superseded  
**Last updated:** 2026-09-28  
**Next steps:** None. Follow ADR-019 and current monorepo guidance; retain ADR-030 only as historical provenance.  
**Current state:** The four-repository templated-peer model is explicitly superseded by ADR-019/monorepo consolidation. Agent Conductor, Canvas, Turing, and shared runtime concerns now live in the consolidation monorepo/package structure described by current repository guidance; this ADR must not be used as a live ownership or repository-topology rule.  
**ADR:** [ADR-030: Four-Repo Governance — Substrate + Three Templated Products](../../../adr/ADR-030-four-repo-governance.md)
