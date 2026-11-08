# Design ADRs

Progressive-disclosure index for ADRs governing maistro-design, Design Studio, design skills/systems, creative orchestration, and related design-product capabilities.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-061: maistro-design — composable design skills + design systems package

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Resolve production reachability/authority for `design.orchestrate` under the current Design Studio and canonical Graph/Run architecture. If maistro-design remains the implementation package, wire its node through a supported product/runtime entry path and prove the SPEC-160 acceptance set end-to-end; if Design Studio has replaced part of its authority, reconcile/supersede those portions rather than preserving an unreachable package path.  
**Current state:** maistro-design has substantial implementation and tests, including node registration when its module is imported. SPEC-160 was rolled back from Implemented to Accepted because `maistro_design.nodes` is in the reachability baseline and nothing outside the module imports or invokes `design.orchestrate`. The package therefore exists but is not yet proven as a canonical reachable product capability.  
**ADR:** [ADR-061: maistro-design — composable design skills + design systems package](../../../adr/ADR-061-maistro-design-package.md)
