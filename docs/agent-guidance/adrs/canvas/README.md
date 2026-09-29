# Canvas ADRs

Progressive-disclosure index for ADRs governing Canvas assets, scene graphs, compositing, routes, agent integration, and related visual-ability architecture.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-040: Canvas Asset Store — Persistence for ADR-041 Layer Model

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Verify or add production Postgres conformance evidence for the ADR's persistence contracts: org isolation, idempotent definition registration, monotonic/concurrent sheet revision, instance ordering/orphaning, and migration/schema behavior. Once both in-memory and production-store acceptance behavior is directly evidenced, transition ADR-040 to `Implemented`.  
**Current state:** The Canvas asset-store implementation is substantial and the named in-memory behavioral suite directly exercises definitions, sheets, instances, ordering, orphaning, profiles/books, and related contracts. The ADR also makes production Postgres and concurrency guarantees; no corresponding indexed conformance evidence was located in this audit, so promotion is held pending production-store proof.  
**ADR:** [ADR-040: Canvas Asset Store — Persistence for ADR-041 Layer Model](../../../adr/ADR-040-canvas-asset-store.md)
