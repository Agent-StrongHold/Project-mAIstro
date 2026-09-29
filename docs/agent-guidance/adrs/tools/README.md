# Tools ADRs

Progressive-disclosure index for ADRs governing tool-layer contracts, structured transformations, tool execution surfaces, and related utility boundaries.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-008: StructuredOutputParser

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Strengthen the validation-error retry-context test to assert the Pydantic error type as well as the field name, run the focused StructuredOutputParser suite, then transition ADR-008 to `Implemented` if the full acceptance set passes. Audit SPEC-210 separately because its checked criteria and prose say the design is implemented while its lifecycle status remains `Accepted`.  
**Current state:** StructuredOutputParser is implemented and exercises schema injection, pure/fenced/embedded JSON extraction, shape validation, and retry-context formatting. SPEC-210 records all eight criteria as satisfied, but the current validation-error test only asserts the field name even though the accepted ADR requires both field name and error type, so promotion is held until that evidence gap is closed.  
**ADR:** [ADR-008: StructuredOutputParser](../../../adr/ADR-008-structured-output-parser.md)

## ADR-035: Catalog Ownership Split — Engine Simple, Stronghold Multi-Tenant

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR that defines canonical ownership for today's reusable capability/catalog architecture: Capability/Binding authority, NodeTemplate/GraphTemplate, Persona exposure, agent/provider registries, skills/tools, and legacy recipe projections. Once accepted, transition ADR-035 to `Superseded` with the explicit successor relationship rather than preserving the obsolete RecipeRegistry/Spawner-centered catalog model.  
**Current state:** The anti-duplication intent remains useful, but the concrete "simple catalog = RecipeRegistry + Spawner" architecture is stale. RecipeRegistry is now explicitly a legacy compatibility adapter into canonical templates, and Spawner's production authority is unresolved against the newer Run/harness architecture. Monorepo consolidation also invalidates much of the historical cross-repo migration narrative.  
**ADR:** [ADR-035: Catalog Ownership Split — Engine Simple, Stronghold Multi-Tenant](../../../adr/ADR-035-catalog-ownership-split.md)

## ADR-049: Agent file-edit rollback via shadow git

**Status:** Deprecated  
**Last updated:** 2026-09-28  
**Next steps:** No implementation work against ADR-049. Delete the unreachable shadow-git/fan-in island during convergence cleanup unless a new accepted architecture explicitly requires the capability. Pre-1.0 compatibility provides no reason to retain dead paths.  
**Current state:** Reachability analysis proved the shipped shadow-git implementation was never connected to a process entry point; its only importer is another unreachable subsystem. The ADR was correctly rolled back from an implementation claim to Deprecated and has no successor.  
**ADR:** [ADR-049: Agent file-edit rollback via shadow git](../../../adr/ADR-049-shadow-git-rollback.md)

## ADR-050: Tool reversibility taxonomy and compensator contract

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Complete the successor architecture on the canonical Capability Binding → Invocation path, including the durable approval/elevation mechanism that ADR-081226-6b46/SPEC-081226-6e34 do not currently cover. Once one successor ADR genuinely owns reversibility classification, compensators, impact/approval semantics, and invocation evidence, transition ADR-050 to `Superseded`. Do not revive the unreachable legacy tool-registration island merely to satisfy this ADR.  
**Current state:** The reversibility/compensator concept remains required by ADR-068 authorization semantics, but the original implementation was unreachable and its old registration boundary is no longer canonical. ADR-050 was correctly rolled back to Accepted; its own convergence note identifies Capability Binding/Invocation as the target architecture while explaining why no existing ADR yet fully qualifies as the successor.  
**ADR:** [ADR-050: Tool reversibility taxonomy and compensator contract](../../../adr/ADR-050-tool-reversibility-taxonomy.md)

## ADR-069: Code Registry — versioned, signed, microVM-isolated execution of substrate code refs

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether arbitrary executable `name@version` code refs remain a first-class architecture concept now that Capability Provider/Binding/Invocation and sandbox/harness boundaries exist. If retained, create a successor that represents registered code as a governed capability/provider executed through canonical Invocation with real isolation, authorization, resource caps, and effect evidence; if the provider architecture already subsumes the need, supersede ADR-069 accordingly. Do not build a parallel `CodeRegistry.invoke` execution path.  
**Current state:** SPEC-257 implemented only the pure registry/resolve/signature core. The ADR's security-critical execution contract, microVM isolation, Sentinel/Warden routing, and resource caps were never built or reachable. Its own convergence note records this. Several substrate dependencies are also stale, so completing the original design literally would risk creating another non-canonical execution boundary.  
**ADR:** [ADR-069: Code Registry — versioned, signed, microVM-isolated execution of substrate code refs](../../../adr/ADR-069-code-registry.md)
