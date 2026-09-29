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

## ADR-031: Front-Matter and Registry Conventions

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile historical four-repo and numbering prose with the consolidation monorepo/current ID policy while preserving the active machine-readable front-matter contract. Treat ADR-097 as authoritative for lifecycle states/transitions and ADR-098 as authoritative for layer taxonomy; ensure registry/lifecycle CI actually enforces the resulting current contract.  
**Current state:** ADR-031 remains active repository governance: structured front matter and relationship fields are the machine-readable source of truth. Later ADR-097 replaced its lifecycle machine and ADR-098 extended its layer taxonomy. Portions describing cross-four-repo registry generation and migration-era numbering are historical and should be updated so new agents do not infer obsolete repository topology.  
**ADR:** [ADR-031: Front-Matter and Registry Conventions](../../../adr/ADR-031-front-matter-and-registry.md)

## ADR-032: Contracts as Acceptance Criteria

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Keep this as the canonical contract/evidence quality policy and reconcile historical Copier/four-product language with the monorepo. Ensure agent development guidance references, rather than duplicates, the live contract-marker ledger, AC-state execution checks, lifecycle-discovery gate, and mutation-testing baseline/ramp. Continue shrinking existing evidence debt instead of permitting new unevidenced contract claims.  
**Current state:** ADR-032 remains active and has been extended with enforceable contract-marker evidence rules, AC-state execution semantics, lifecycle-owner discovery, and mutation-testing quality targets. Its quality model is directly relevant to autonomous issue-to-merge work: an implementation claim requires executable evidence, not merely code presence or line coverage. Some original repository-template framing is historical after consolidation.  
**ADR:** [ADR-032: Contracts as Acceptance Criteria](../../../adr/ADR-032-contracts-as-acceptance-criteria.md)

## ADR-033: Templates and Copier Workflow

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the body so Copier's current role is unambiguous: it is a template/bootstrap mechanism for generated/downstream product surfaces, not the integration or synchronization model among packages absorbed into this monorepo. Preserve and maintain the live template render/origin tests and bootstrap resolver integration.  
**Current state:** Copier/template tooling remains present and tested, and maistro-bootstrap still emits Copier commands. The original three-templated-peer rebase workflow is historical after monorepo consolidation, as the ADR itself now notes. Agents must not use that obsolete workflow to reason about package ownership or cross-package changes inside this repository.  
**ADR:** [ADR-033: Templates and Copier Workflow](../../../adr/ADR-033-templates-and-copier-workflow.md)

## ADR-039: External Library Adoption Policy

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Reconcile the historical per-repo policy table with the consolidation monorepo/package boundaries, then audit which layered supply-chain controls are actually enforced in current CI (lock/hash discipline, dependency review, SBOM, signed artifacts, Scorecard). Agent development guidance should reference this ADR whenever adding a runtime dependency or external service rather than inventing a separate dependency policy.  
**Current state:** The core decision remains active: minimize process-internal dependency trust, prefer explicit service boundaries where appropriate, apply maintainer/license/transitive-dependency review, and record external pattern influences separately from legal dependency attribution. The four-repo framing and several "gap-impl" control statuses are historical and require current reconciliation.  
**ADR:** [ADR-039: External Library Adoption Policy](../../../adr/ADR-039-external-library-adoption-policy.md)

## ADR-065: Test harness with full wiring factory

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Create a successor ADR for the canonical integration-test harness and then supersede ADR-065. The replacement should construct the real composition root with canonical principal/Workspace context, Run/NodeRun/Attempt storage, durable Graph execution/recovery, Capability Binding/Invocation, current quota/credential routing, and Faux external providers. Keep legacy `GraphRun` helpers only for domain/unit tests, not as evidence of production execution wiring.  
**Current state:** The harness is implemented and useful, but its defining "full pipeline" path still includes `GraphRun` as an executor and exposes `run_graph()` as an integration helper. ADR-062 now explicitly states that GraphRun is not canonical execution authority. A harness built around a retired execution path can make tests green while production authority remains untested, so the architectural contract needs replacement rather than simple completion.  
**ADR:** [ADR-065: Test harness with full wiring factory](../../../adr/ADR-065-test-harness.md)
