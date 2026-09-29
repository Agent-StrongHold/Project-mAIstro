# Canvas ADRs

Progressive-disclosure index for ADRs governing Canvas assets, scene graphs, compositing, routes, agent integration, and related visual-ability architecture.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-040: Canvas Asset Store — Persistence for ADR-041 Layer Model

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Verify or add production Postgres conformance evidence for the ADR's persistence contracts: org isolation, idempotent definition registration, monotonic/concurrent sheet revision, instance ordering/orphaning, and migration/schema behavior. Once both in-memory and production-store acceptance behavior is directly evidenced, transition ADR-040 to `Implemented`.  
**Current state:** The Canvas asset-store implementation is substantial and the named in-memory behavioral suite directly exercises definitions, sheets, instances, ordering, orphaning, profiles/books, and related contracts. The ADR also makes production Postgres and concurrency guarantees; no corresponding indexed conformance evidence was located in this audit, so promotion is held pending production-store proof.  
**ADR:** [ADR-040: Canvas Asset Store — Persistence for ADR-041 Layer Model](../../../adr/ADR-040-canvas-asset-store.md)

## ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Close the remaining SPEC-219 contract gap by implementing/verifying occlusion-reference DAG validation and `OcclusionCycleError`, add direct layer-model contract tests where indirect store/compositor coverage is insufficient, then reconcile SPEC-219's stale `Proposed` lifecycle and advance ADR-041 only when child-spec evidence permits it.  
**Current state:** The seven-kind layer taxonomy, asset definition/instance model, generalized sheets, personalization, world/render styles, ground plane, pose geometry, and domain errors exist and are used by later Canvas components. SPEC-219 records eight criteria satisfied but explicitly leaves occlusion-cycle enforcement unverified, so the ADR remains Accepted rather than being promoted on partial evidence.  
**ADR:** [ADR-041: Canvas Layer Taxonomy, Scene Graph, and World Style](../../../adr/ADR-041-canvas-layer-taxonomy-and-world-style.md)

## ADR-042: Canvas Asset HTTP Routes

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Verify or complete canonical production mounting of the v2 Canvas asset router, including current authentication/Workspace/org-scope integration, then run the route contract through the production composition rather than only an isolated FastAPI test app. If the canonical server surface satisfies the ADR's boundary/behavioral contracts, transition ADR-042 to `Implemented`.  
**Current state:** `asset_routes.py` and its dedicated FastAPI route suite exist and exercise the v2 HTTP contract in isolation. Repository search did not establish that this router is mounted as a canonical production surface; the ADR itself describes maistro-server mounting as a future cutover step. Implementation existence therefore does not yet prove production reachability/authority.  
**ADR:** [ADR-042: Canvas Asset HTTP Routes](../../../adr/ADR-042-canvas-asset-routes.md)

## ADR-043: Canvas Asset Executor and Tool — Agent Integration

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Audit ADR-044 Phase 4 and complete the legacy `canvas` → `canvas_asset` convergence. Under the current pre-1.0 development standard, preserving the old LayerType tool for backward compatibility has no architectural value; if the new path satisfies current requirements, remove the legacy path rather than maintaining dual behavior. Then verify canonical tool/capability registration and the executor/tool acceptance suite before promoting ADR-043.  
**Current state:** AssetExecutor, AssetTool, and dedicated tests exist, and Davinci currently registers both `canvas` and `canvas_asset`. The ADR intentionally preserved dual legacy/new flows during migration, but that compatibility strategy conflicts with the current pre-1.0 rule to prefer architectural convergence over backward compatibility. ADR-044 is named as the retirement owner, so lifecycle completion depends on that convergence audit.  
**ADR:** [ADR-043: Canvas Asset Executor and Tool — Agent Integration](../../../adr/ADR-043-canvas-asset-executor-and-tool.md)
