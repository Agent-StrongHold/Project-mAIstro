# Crypto & Payments ADRs

Progressive-disclosure index for ADRs governing optional cryptocurrency, payment, chain-backend, and related financial-infrastructure capabilities.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-025: Electrum Server — Medley plugin for household-private Bitcoin backend

**Status:** Deferred  
**Last updated:** 2026-09-28  
**Next steps:** None for current M1-M4 architecture convergence. Re-evaluate only if optional agent crypto operations and the private Bitcoin-backend product surface return to active scope; at that point reconcile the design with current plugin, networking, vault, and bootstrap architecture before implementation.  
**Current state:** This ADR is already explicitly Deferred and depends on the unresolved optional crypto stack. It does not define current runtime, security, identity, or milestone-critical behavior and should not be loaded into normal agent context unless work specifically concerns the optional Bitcoin/Electrum capability.  
**ADR:** [ADR-025: Electrum Server — Medley plugin for household-private Bitcoin backend](../../../adr/ADR-025-electrum-server.md)
