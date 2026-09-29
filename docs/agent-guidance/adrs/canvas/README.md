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

## ADR-044: LayerRecord → AssetInstance Migration Plan

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create a successor ADR for direct pre-1.0 Canvas cutover, then supersede ADR-044.** The successor should make AssetInstance/canvas_asset canonical, remove legacy LayerRecord/tool/compositor/schema paths wherever the current architecture does not require them, and explicitly reject bridge/backfill/deprecation-delay work whose only purpose is backward compatibility. Pre-1.0 deployments are rebuilt from scratch, so preserving old production rows/callers has no architectural value.  
**Current state:** ADR-044's four-phase six-week migration strategy conflicts with the current pre-1.0 development standard. It deliberately preserves dual models, builds compatibility bridges/backfills, waits through deprecation periods, and delays deletion for legacy consumers. That work is now counterproductive because backward compatibility is not a design objective before 1.0 and may conceal failure to converge on the new architecture.  
**ADR:** [ADR-044: LayerRecord → AssetInstance Migration Plan](../../../adr/ADR-044-layerrecord-to-assetinstance-migration.md)

## ADR-045: Canvas capability ↔ maistro-server /v2/canvas boundary

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Revise this proposal before acceptance to conform to the current pre-1.0 development standard: preserve canonical authority, durable-state, authorization, execution identity, cancellation, provenance, and truthful dependency wiring, but remove backward-compatibility/parity/legacy-consumer preservation as independent design goals for pre-1.0 deployments. Then verify the canonical maistro-server Canvas composition and Design Studio consumption path and define acceptance evidence.  
**Current state:** The proposal correctly reframes Canvas as a capability under Design Studio and maistro-server as the governed HTTP composition boundary, with missing dependencies failing visibly. Its remaining compatibility-window language predates the explicit pre-1.0 decision that deployments are rebuilt from scratch and backward compatibility carries no positive architectural weight, so that portion should be revised before this ADR is accepted.  
**ADR:** [ADR-045: Canvas capability ↔ maistro-server /v2/canvas boundary](../../../adr/ADR-045-canvas-studio-engine-cutover.md)

## ADR-061: maistro-design — composable design skills + design systems package

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Connect `maistro_design.nodes` to the canonical node/plugin discovery/composition path and prove `design.orchestrate` is reachable through a real Graph/Run without test-only imports. Then re-evaluate lifecycle promotion against SPEC-160. Reconcile this ADR's informal Warden-feedback "RLPHD" wording with ADR-068's precise authorization-policy RLPHD definition so two different learning mechanisms do not share one architectural term accidentally.  
**Current state:** maistro-design has extensive implementation and tests, but SPEC-160 explicitly records AC-35/36 as passing rather than reachable: `DesignOrchestrateNode` registers only when its module is directly imported, and no live process imports/names it. This green-but-unreachable gap is why the earlier Implemented claim was correctly rolled back to Accepted.  
**ADR:** [ADR-061: maistro-design — composable design skills + design systems package](../../../adr/ADR-061-maistro-design-package.md)

## ADR-067: Canvas Asset Compositor — Scene Graph, Occlusion, Prompt Composition

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Bind/remeasure the compositor's stated contracts against `test_asset_compositor.py` and transition ADR-067 to `Implemented` if the suite and lifecycle evidence are complete. Feed that evidence back into ADR-041/SPEC-219: occlusion self-loops/cycles and unknown references are directly tested here, so SPEC-219's "unverified" occlusion-DAG criterion should be reconciled. Legacy Canvas retirement is separate from this pure compositor's correctness.  
**Current state:** `asset_compositor` has a substantial dedicated behavioral suite covering scene-graph parent errors/cycles, transform composition, occlusion ordering and cycle rejection, personalization/skin validation, prompt/style composition, and render planning. It is used by the newer AssetExecutor path. The remaining work is evidence/lifecycle reconciliation rather than an obvious missing compositor mechanism.  
**ADR:** [ADR-067: Canvas Asset Compositor — Scene Graph, Occlusion, Prompt Composition](../../../adr/ADR-067-canvas-asset-compositor.md)

## ADR-100: Bundled and cataloged Open Design design systems for maistro-design

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile lifecycle/evidence metadata. The front matter contains `implemented: 2026-06-14` while current status/history remain Accepted with no Implemented transition. Bind the actual tests for the six ACs, verify vendored license/scan/import behavior, then either add a valid Implemented lifecycle transition or remove the unsupported `implemented` field. Keep ADR-061's production reachability gap separate from this ADR's narrower content/import contract.  
**Current state:** The bundled/catalog content, importer, trust tiers, rescanning, notices, and default design-system registration are present in source, and the ADR is much closer to completion than most of this tranche. Its main visible defect is lifecycle/evidence inconsistency rather than an obvious missing architecture mechanism.  
**ADR:** [ADR-100: Bundled and cataloged Open Design design systems for maistro-design](../../../adr/ADR-100-bundled-open-design-systems.md)

## ADR-062326-616c: Design skills React/TSX code export

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Re-evidence the narrow output-format contract and move code preview/execution safety onto the canonical sandbox/capability boundary. Generated TSX is untrusted code: Warden scanning alone is not sufficient for execution, and preview must obey ADR-093 isolation plus outbound/effect policy. Remove pre-1.0 compatibility language and avoid making Hive/Canvas own a second code-execution path.  
**Current state:** The output-format direction is useful, but the earlier Implemented claim was rolled back and the ADR intentionally leaves the security-critical preview/execution mechanism downstream. Completion therefore requires proving both the format behavior and a canonical safe consumer path, not merely an enum value and prompt instructions.  
**ADR:** [ADR-062326-616c: Design skills code export](../../../adr/ADR-062326-616c-design-skills-code-export-capability.md)

## ADR-062326-702b: Multi-modality design outputs and hierarchical artifact containers

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Remeasure the seven ACs against the listed tests/source and promote if still complete. Reconcile binary persistence with the current object/archive storage decisions and keep renderer execution behind capability providers rather than DesignEngine. Treat the existing `implemented` date plus rollback-to-Accepted history as requiring fresh strict evidence before promotion.  
**Current state:** This ADR has unusually concrete source anchors, tests, AC modules, and a coherent ArtifactNode tree that separates prompt assembly from rendering. It appears close to completion; remaining work is lifecycle/evidence reconciliation and alignment with newer storage/provider ownership, not redesign of the artifact model.  
**ADR:** [ADR-062326-702b: Multi-modality design outputs](../../../adr/ADR-062326-702b-multi-modality-design-outputs-hierarchical-artifact-containers.md)
