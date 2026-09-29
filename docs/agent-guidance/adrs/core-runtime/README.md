# Core Runtime ADRs

Progressive-disclosure index for ADRs governing shared runtime contracts, schemas, parsing, execution primitives, and other cross-agent runtime behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-005: Pydantic schemas + SCHEMA_REGISTRY

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Strengthen ADR-005 acceptance evidence before promotion: explicitly assert that all 15 promised schema classes are importable and that `SCHEMA_REGISTRY` contains the complete 15-key contract, then run the focused suite and transition the ADR to `Implemented` if all acceptance criteria pass.  
**Current state:** The complete 15-class typed output schema surface and runtime schema resolver are implemented. Known/unknown/dynamic resolution, score bounds, round-trips, and forward-reference rebuilding are covered or present, but the current import and registry tests are weaker than the ADR's exact acceptance language because they verify module import and only a representative subset of registry keys.  
**ADR:** [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../../../adr/ADR-005-schemas.md)

## ADR-012: First Alembic migration (memory tables + pgvector)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Add or run fresh-Postgres migration verification that proves `alembic upgrade head`, the required downgrade semantics, pgvector extension setup, and model/migration drift detection (`alembic check` or equivalent). Once all four accepted criteria are directly evidenced, transition ADR-012 to `Implemented`. Reconcile SPEC-213's stale `Proposed` status during the spec audit.  
**Current state:** The initial migration exists, creates the memory-era schema and pgvector prerequisite, and the repository has a substantial live Alembic chain. SPEC-213 confirms most of the intended implementation but explicitly records that downgrade behavior was not independently re-verified and that no drift-check CI step currently proves the ADR's `alembic check` criterion, so the ADR is not yet promoted.  
**ADR:** [ADR-012: First Alembic migration (memory tables + pgvector)](../../../adr/ADR-012-alembic-migration.md)

## ADR-018: Persist TaskRecord at queue/runner boundaries

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the ADR's durability framing with the canonical Run spine: explicitly state that TaskRecord is a best-effort receipt, not execution/recovery authority, and add direct configured-database evidence that queue mutations persist the receipt row. If the narrowed receipt contract is the intended surviving decision, verify all three criteria and transition ADR-018 to `Implemented`; otherwise identify a successor ADR and supersede it.  
**Current state:** TaskQueue still performs ordered best-effort TaskRecord upserts and remains functional without a database, so the narrow receipt-persistence mechanism survives. Recovery authority has moved to canonical Runs and durable Run provenance; current code explicitly says TaskRecord is a receipt. No direct integration-test evidence was located for the ADR's configured-database row-exists criterion, so the record remains Accepted pending reconciliation and proof.  
**ADR:** [ADR-018: Persist TaskRecord at queue/runner boundaries](../../../adr/ADR-018-task-record-persistence.md)

## ADR-036: Ontology / Semantic Object Layer

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the proposed OntologyEntity/Ontology object system with the newer canonical Workspace object, Node/Graph, Template, and provenance architecture before implementation. If a distinct semantic layer is still required, specify it as a projection/schema layer over canonical objects rather than a competing identity/lifecycle/persistence authority; otherwise create/identify the successor decision and supersede ADR-036.  
**Current state:** No `maistro.ontology` implementation or OntologyEntity registry was located. The original semantic-object problem may still be valid, but the repository has since established substantially richer canonical object/template semantics. ADR-036 therefore remains an accepted but unimplemented design that must be reconciled before code is added.  
**ADR:** [ADR-036: Ontology / Semantic Object Layer](../../../adr/ADR-036-ontology-semantic-object-layer.md)

## ADR-070: The Repertoire Pattern — reuse-first cascade

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Decide whether this ADR is primarily normative architectural vocabulary/invariants or mandates a shared runtime `Repertoire/repertoire_run` abstraction. If vocabulary, revise/supersede the generic-runtime requirements and let subsystems conform conceptually without forced indirection. If a shared runtime is intended, wire at least one canonical reachable subsystem through it and reconcile signed/executable entries with the post-ADR-069 Capability Provider/Invocation architecture before promotion.  
**Current state:** SPEC-258 built the generic protocol/cascade but explicitly deferred migrating any existing subsystem, leaving the machinery unreachable. The reuse-first / verify-before-store / outcome-demotion pattern remains useful, but production value does not require every subsystem to call one generic helper. The ADR's signing dependency also inherits ADR-069's unresolved execution boundary.  
**ADR:** [ADR-070: The Repertoire Pattern — reuse-first cascade](../../../adr/ADR-070-repertoire-pattern.md)

## ADR-075: Universal Artifact Versioning and Release Channels

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR mapping runtime-artifact identity/versioning onto current canonical artifacts: Persona, NodeTemplate/GraphTemplate, Capability Provider/Binding, governed policy/config, and other actual runtime definitions. Preserve version pinning/history where it serves reproducibility, evaluation, safe promotion, and rollback of evolving artifacts, but explicitly separate that from pre-1.0 backward compatibility for deployments, which is not a goal. Remove Recipe/CodeRegistry-era assumptions and define the real registry/storage authority.  
**Current state:** The learn-forward vs stable-promotion problem remains valid, especially for evolve-generated artifacts. The concrete artifact taxonomy and dependencies are stale, and "rollback any prior version" should not be interpreted as an obligation to preserve compatibility with old pre-1.0 deployments. This ADR needs a current successor rather than literal implementation against obsolete artifact kinds.  
**ADR:** [ADR-075: Universal Artifact Versioning and Release Channels](../../../adr/ADR-075-universal-artifact-versioning.md)

## ADR-078: Configuration Management — DB source of truth, RBAC online edit, file export

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Complete SPEC-062226-fb23: real ConfigStore persistence/cache, canonical-principal authorization, audited API/CLI edit paths, explicit export/restore, and tests. Then migrate hot-editable settings subsystem-by-subsystem instead of assuming all named tunables are already DB-backed. Reconcile ADR-078's "scheduled/on-change git export" wording with the SPEC's safer explicit export/restore contract unless automated repository mutation is intentionally required.  
**Current state:** The static bootstrap config path exists, but the implementing SPEC states the online DB-backed ConfigStore did not yet exist when specified and its acceptance criteria remain unchecked. The DB-vs-static split remains a useful architecture rule, while the actual hot-config control plane is still incomplete.  
**ADR:** [ADR-078: Configuration Management — DB source of truth, RBAC online edit, file export](../../../adr/ADR-078-configuration-management.md)

## ADR-092: Capability-vs-control posture

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Correct the document's stale internal `Status: Proposed` line and broken/misleading related-ADR commentary, then refresh examples against current canonical architecture. Preserve the principle that security, interpretability, auditability, and governed authority justify structural cost, while unnecessary scaffolding does not. Any "trusted local lane" must still have explicit authority/effect boundaries rather than becoming a bypass around canonical principals, Sentinel, or Invocation evidence.  
**Current state:** The front matter/history make this an Accepted architectural posture, while the body still says Proposed and one related reference mislabels ADR-091 as durable execution. The core decision remains highly relevant: MAIstro intentionally accepts some capability/smoothness cost for control, but must continuously prove that each structural constraint serves a real governance requirement.  
**ADR:** [ADR-092: Capability-vs-control posture](../../../adr/ADR-092-capability-vs-control-posture.md)

## ADR-062226-674b: Constant tunability ladder

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep the Tunable → Enumerated → Locked evidence ladder, but apply it only after ADR-078's real ConfigStore exists and only to genuine operational tuning knobs. Do not force configuration indirection onto constants that are already architectural invariants or implementation details with no plausible deployment-specific value. Require evidence for narrowing as the ADR states.  
**Current state:** The maturity model is useful governance, but its universal default of ConfigStore-backing every new implementation-defined numeric constant currently depends on an unfinished configuration control plane and risks over-configuration. Treat it as a target policy, not proof that existing constants are dynamically tunable today.  
**ADR:** [ADR-062226-674b: Constant tunability ladder](../../../adr/ADR-062226-674b-constant-tunability-ladder.md)

## ADR-081226-9944: Canonical Product Hierarchy and Ownership

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Treat this as the ownership constitution for convergence. Every durable object must carry Workspace identity; project-scoped objects additionally carry exactly one Project; Templates are the intentional Workspace-wide reusable-definition exception. Continue deleting obsolete compatibility facades after callers move, exactly as this ADR's migration posture requires.  
**Current state:** This decision resolves the product hierarchy and explicitly adopts the pre-1.0 posture we are enforcing in this audit: build canonical model → move useful behavior → change real callers → delete obsolete system. It cleanly separates Persona, Templates, Project objects, execution hierarchy, and capability fulfillment.  
**ADR:** [ADR-081226-9944: Canonical Product Hierarchy and Ownership](../../../adr/ADR-081226-9944-canonical-product-hierarchy-and-ownership.md)

## ADR-081226-bb3a: Template, Object and Provenance Semantics

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep immutable template-version provenance and explicit instantiate/save-as-template semantics as canonical. Finish replacing older Recipe/Agent/GraphConfig reusable definitions with NodeTemplate/GraphTemplate or clearly domain-specific templates, and enforce exact version pinning inside GraphTemplate snapshots. Do not interpret immutable provenance as a pre-1.0 compatibility promise.  
**Current state:** This ADR cleanly separates reusable immutable definitions from mutable Project objects. Instantiation is copy-plus-provenance, existing objects never silently follow template updates, and execution state cannot leak into templates. This is the right successor for much of ADR-053/075-era artifact versioning.  
**ADR:** [ADR-081226-bb3a: Template, Object and Provenance Semantics](../../../adr/ADR-081226-bb3a-template-object-provenance-semantics.md)

## ADR-081426-b1d3: Project Scope Tree

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Use this as canonical Project semantics and migrate/delete Project-as-Workspace or execution-hierarchy remnants. Enforce one immutable Root Project per Workspace, acyclic same-Workspace trees, creation-time defaults rather than live inheritance, downward-only resource visibility, atomic move validation, deny-wins scoped authorization, and fail-closed nonrecursive deletion.  
**Current state:** This restores Project as a legitimate nested scope rather than an obsolete Workspace synonym. It composes directly with canonical ownership and scoped grants, and explicitly rejects compatibility-only Project machinery that does not match the tree/resource contract.  
**ADR:** [ADR-081426-b1d3: Project Scope Tree](../../../adr/ADR-081426-b1d3-project-scope-tree.md)

## ADR-082926-0b72: Conductor settings are durable or write fails

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Apply honest durable acknowledgement to every settings surface and migrate ownership out of module globals as Hive thins.  
**Current state:** A successful settings write now means the durable owner accepted it; optimistic in-memory success is not allowed.  
**ADR:** [ADR-082926-0b72](../../../adr/ADR-082926-0b72-conductor-settings-are-durable-or-the-write-fails.md)

## ADR-082926-3b80: Dashboard layouts are durable or save fails

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep one durable data-boundary owner and remove duplicate local-file/PostgREST authorities.  
**Current state:** This applies the same honest-write contract to user layout state.  
**ADR:** [ADR-082926-3b80](../../../adr/ADR-082926-3b80-conductor-dashboard-layouts-are-durable.md)

## ADR-082926-65bf: Template candidate state before activation

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Implement candidate → validated → explicit promotion semantics in immutable Template versions with audit/provenance. Use this instead of broad compatibility-heavy release channels for learned/evolved templates.  
**Current state:** This fills a real gap between Evolve's gated candidates and NodeTemplate/GraphTemplate versioning.  
**ADR:** [ADR-082926-65bf](../../../adr/ADR-082926-65bf-template-versions-hold-a-candidate-before-they-become-active.md)

## ADR-082926-730d: One asyncpg pool per database

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep pool identity database-specific, registry-owned, and explicitly closed at shutdown; prevent callers from silently opening parallel pools.  
**Current state:** This fixes split store ownership and a singleton that previously ignored later database URLs.  
**ADR:** [ADR-082926-730d](../../../adr/ADR-082926-730d-one-pool-per-database-one-owner.md)

## ADR-082926-d0dc: Save-as-template records source object

**Status:** Proposed  
**Last updated:** 2026-09-29  
**Next steps:** Add source-object provenance outside content hashes for Node/Graph save-as-template operations.  
**Current state:** This completes the reverse provenance direction missing from ADR-081226-bb3a.  
**ADR:** [ADR-082926-d0dc](../../../adr/ADR-082926-d0dc-save-as-template-records-its-source-object.md)

## ADR-083026-427c: Prompt versions and labels are separate facts

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep immutable prompt versions separate from mutable labels and update them transactionally.  
**Current state:** This fixes a relational model that could not represent multiple labels pointing at one version.  
**ADR:** [ADR-083026-427c](../../../adr/ADR-083026-427c-prompt-versions-and-labels-are-separate-facts.md)
