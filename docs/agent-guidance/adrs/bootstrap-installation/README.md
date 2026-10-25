# Bootstrap & Installation ADRs

Progressive-disclosure index for ADRs governing installation, first-run bootstrap, setup, recovery/bootstrap ceremonies, and operator onboarding.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-020: Setup Wizard — Browser-first install ceremony

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether the browser-first secure 12-step first-run ceremony remains a current product requirement. If yes, create/update a current implementing spec that composes with `maistro-bootstrap`, current identity/security architecture, and the present monorepo product surface, then implement and verify its browser/resume/smoke-test guarantees. If no, create or identify the withdrawing successor ADR and transition ADR-020 to `Superseded`.  
**Current state:** A substantial `maistro-bootstrap` installer now exists and SPEC-180 defines a tested CLI/YAML/structured-plan bootstrap contract, but SPEC-180 neither implements nor supersedes ADR-020. The current installer is not the browser-first 12-step security/onboarding ceremony described here, so ADR-020 remains an accepted but unresolved product decision rather than an implemented one.  
**ADR:** [ADR-020: Setup Wizard — Browser-first install ceremony](../../../adr/ADR-020-setup-wizard.md)
