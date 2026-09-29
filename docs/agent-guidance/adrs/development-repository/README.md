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

## ADR-087: Database Schema Evolution — expand/contract, zero-downtime

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create a successor ADR for pre-1.0 schema evolution, then supersede ADR-087.** Optimize for one clean canonical schema and fresh deployment, not old/new application coexistence or rollback compatibility. Destructive schema replacement is allowed before 1.0. Preserve/migrate beta user data only when that data itself is intentionally durable; compatibility columns, dual reads/writes, two-deploy expand/contract, and rollback-safe old-code support should not be requirements. CI should prove fresh-schema creation plus any explicitly required current-data restore/migration path.  
**Current state:** ADR-087's entire zero-downtime expand/contract discipline assumes rolling deploys where old and new application versions coexist against one database. That directly conflicts with the explicit pre-1.0 scratch-deployment standard and would add compatibility code/schema debt that hides architectural convergence.  
**ADR:** [ADR-087: Database Schema Evolution — expand/contract, zero-downtime](../../../adr/ADR-087-db-schema-evolution.md)

## ADR-090: Builders Pipeline — spec → tests → code → audit stage machine

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** **Create a successor ADR for the current autonomous engineering pipeline, then supersede ADR-090.** The replacement should use canonical Runs rather than a Builders-owned RunState/StageEvent lifecycle; GitHub issue/branch/worktree/PR as the collaboration artifact; explicit acceptance criteria and ADR-032 contract evidence; CI/review/comment resolution loops; mutation-quality baselines; merge authority; and the new agent development standards. Remove shadow-git, pre-1.0 hot-swap compatibility, and any parallel execution state machine.  
**Current state:** ADR-090 formalizes an older Frank/Mason/Auditor Builders 2.0 pipeline with its own durable stage lifecycle, deprecated ADR-049 shadow workspace, and ADR-075 runtime-version draining. The repository's actual autonomous development system and M1 convergence now demand one canonical execution spine and direct GitHub/CI evidence. Leaving ADR-090 as the canonical engineering pipeline would conflict with both.  
**ADR:** [ADR-090: Builders Pipeline — spec → tests → code → audit stage machine](../../../adr/ADR-090-builders-pipeline.md)

## ADR-095: Protected develop-to-main promotion model

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Keep live GitHub Rulesets and `.github/branch-protection.json` synchronized, and reference this ADR from agent development guidance. Normal work flows from topic branches through pull requests into `develop` only after the required checks, conversation resolution, autonomous-admissibility check, and gates-ran verification. Governance-sensitive changes follow the repository's separately controlled trusted-change process. `main` remains the explicit release-promotion branch.  
**Current state:** This is current repository governance, not historical design. Its acceptance criteria are checked against the live two-branch topology: `develop` is the canonical active integration branch, `main` is the promotion ledger, and the retired `integration` branch must not be recreated implicitly. This directly complements the new issue/PR/merge agent standards.  
**ADR:** [ADR-095: Protected develop-to-main promotion model](../../../adr/ADR-095-four-tier-branch-model.md)

## ADR-097: Lifecycle Status State Machine for ADRs and Specs

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Make lifecycle enforcement real at the merge boundary: wire `tools/lint_lifecycle.py` into required CI (or explicitly replace it with an equivalent canonical gate), then close the remaining date-consistency and cross-reference checks. Keep the forward-only/correction-with-reason model. Use the progressive-disclosure ADR index's `Next steps` field for "accepted but successor required" rather than inventing a misleading implementation status.  
**Current state:** ADR-097 is the canonical lifecycle vocabulary and transition machine, and its correction-with-reason rule is actively used throughout the corpus. The ADR and SPEC-232 still record that the lifecycle linter is not invoked by GitHub Actions, so the governance contract is not yet fully enforced pre-merge even though the schema/front-matter registry gate exists.  
**ADR:** [ADR-097: Lifecycle Status State Machine for ADRs and Specs](../../../adr/ADR-097-lifecycle-status-machine.md)

## ADR-098: Layer taxonomy extension — Evolve, Crypto, Connectivity, Ability, Identity

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Maintain the closed layer taxonomy as repository classification governance and keep `maistro_registry.schema.Layer` plus touched ADR/spec front matter synchronized. Use layer as a discovery/classification aid, not as proof of architectural ownership; canonical ownership still comes from the relevant ADRs and current package boundaries.  
**Current state:** The five added layer values are implemented in the registry schema and referenced by ADR-031. This is ongoing taxonomy governance rather than a finite runtime feature, so Accepted is the appropriate standing status.  
**ADR:** [ADR-098: Layer taxonomy extension — Evolve, Crypto, Connectivity, Ability, Identity](../../../adr/ADR-098-layer-taxonomy-extension.md)

## ADR-099: Builders pipeline as a DAG with gated verify-and-revise loops

**Status:** Proposed  
**Last updated:** 2026-09-28  
**Next steps:** Rewrite the proposal to describe the **canonical** Builders adapter that now exists, then finish the remaining M1 convergence debt: Builders domain stages/gates/revision feedback may project onto canonical Graph/Run, but they must not own a second traversal/lifecycle. Retire legacy executor/state authority and classify/remove `StageStatus` universal-lifecycle behavior per the convergence ledger. Preserve gated revise loops only as domain routing that creates canonical NodeRun/Attempt evidence.  
**Current state:** #734-era code now includes `CanonicalGraphPipelineExecutor` and behavioral tests proving Builders work produces one canonical Run with NodeRuns/Attempts, including revisions. However, the reachability/convergence ledgers still classify the Builders executor/state lifecycle as RETIRE/CONVERGE debt. ADR-099's original "two execution models coexist" decision is therefore obsolete even though its DAG/gate semantics are being successfully adapted to the canonical spine.  
**ADR:** [ADR-099: Builders pipeline as a DAG with gated verify-and-revise loops](../../../adr/ADR-099-builders-pipeline-graph.md)

## ADR-062026-9b30: Date-based ADR/SPEC IDs for new records

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Enforce the date/hash ID rule in repository lint/CI so new sequential IDs cannot reappear and duplicate IDs are rejected before merge. Reconcile lifecycle metadata: the ADR carries an `implemented` date but no Implemented history/status transition.  
**Current state:** The decision solved a real concurrent-PR collision and the registry accepts both legacy sequential IDs and current date/hash IDs. The foreign-harness duplication discovered during this audit shows that unique IDs alone do not prevent duplicate decision content, so decision-level duplication detection/review still matters.  
**ADR:** [ADR-062026-9b30: Date-based ADR/SPEC IDs](../../../adr/ADR-062026-9b30-date-based-adr-spec-ids.md)

## ADR-081226-034b: Package Ownership and Dependency Direction

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Enforce inward dependency direction mechanically and continue moving canonical semantics into maistro-core while specialized packages remain extensions. Remove the phrase/assumption that physical moves require compatibility planning before 1.0 unless preserving user data or an external stable contract is explicitly justified; parity/reachability tests should protect useful behavior, not obsolete interfaces.  
**Current state:** This is the current package-ownership map: core owns reusable semantics/platform mechanisms, server is transport/control-plane composition, Hive is product/UI, specialized packages extend core, and bootstrap owns installation/environment setup. It directly supports the convergence work in M1.  
**ADR:** [ADR-081226-034b: Package Ownership and Dependency Direction](../../../adr/ADR-081226-034b-package-ownership-dependency-direction.md)

## ADR-073126-c4e1: Release and versioning process

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Rewrite the release-candidate branch rules to match ADR-095's current topology: `integration` is retired, so RCs cannot depend on it. Preserve lockstep monorepo versioning, immutable annotated tags, one workflow-controlled publish path, artifact verification, and independent release approval. Before 1.0, do not let package-version compatibility bounds drive architecture or preserve obsolete interfaces.  
**Current state:** The release ADR contains useful publication controls but still describes RC/hotfix flows around a branch model that ADR-095 explicitly retired. Its own implementation inventory also records that some publish controls were never exercised/configured. It needs operational reconciliation before the first real release.  
**ADR:** [ADR-073126-c4e1: Release and versioning process](../../../adr/ADR-073126-c4e1-release-and-versioning-process.md)

## ADR-082226-ff3c: Design coverage metric

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep decision-weighted reachable-AC coverage as the primary "distance to designed state" metric and harden its inputs against gaming: missing criteria score zero, generated evidence cannot self-judge, branch-note folding must be deterministic, and reachability must remain stronger than passing tests. Use it alongside debt ratchets, not as a replacement for them.  
**Current state:** This solves a real measurement problem: criterion-weighted coverage hid the 76/99 accepted decisions with no criteria. Decision-weighting makes undocumented/unmeasured design visible instead of disappearing from the denominator. Later August/September ADRs refine the metric's evidence and branch aggregation.  
**ADR:** [ADR-082226-ff3c: Design coverage metric](../../../adr/ADR-082226-ff3c-design-coverage-metric.md)

## ADR-082526-0d30: CI cost is measured per PR head

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep CI cost measurement tied to the concrete PR head and actual job-minutes so optimization work cannot hide behind time-window estimates. Use the metric to identify expensive gates without weakening required evidence.  
**Current state:** Direct tooling tests make this a measured repository-governance instrument.  
**ADR:** [ADR-082526-0d30](../../../adr/ADR-082526-0d30-ci-runner-cost-is-measured-per-head.md)

## ADR-082526-1899: Gate wired-but-unread DI attributes

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep the wiring-read gate as a complement to import reachability: constructing/storing a dependency is not evidence it has a production consumer. New Container attributes must demonstrate a real read or be explicitly authorized as transitional debt.  
**Current state:** This catches exactly the class that let the unused local A2A broker and other fake-supported surfaces survive ordinary dead-code scans.  
**ADR:** [ADR-082526-1899](../../../adr/ADR-082526-1899-wired-but-unread-di-attributes-gate.md)

## ADR-082526-3011: One pinned uv setup wrapper

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep one reviewed wrapper as the source of both setup-uv action version and uv tool pin; prevent workflow-local drift. Update deliberately in one place when either pin changes.  
**Current state:** This separates action-release flake fixes from tool-version determinism while centralizing both controls.  
**ADR:** [ADR-082526-3011](../../../adr/ADR-082526-3011-one-pinned-uv-in-one-place.md)

## ADR-082526-547c: Suite inventory count is sum of deltas

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Preserve per-change delta accounting so concurrent PRs cannot overwrite one shared baseline row and silently erase each other's inventory movement.  
**Current state:** This is a concurrency-safe ratchet design for repository quality inventory.  
**ADR:** [ADR-082526-547c](../../../adr/ADR-082526-547c-the-inventory-count-is-a-sum-of-deltas.md)

## ADR-082526-9fa2: The gates are gated too

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep repo-truth scripts inside diff-coverage measurement even when their workflows are temporarily parked. Exempt only tooling that genuinely does not assert repository truth, with explicit reasons.  
**Current state:** This prevents CI/security/quality gates from becoming untested privileged code.  
**ADR:** [ADR-082526-9fa2](../../../adr/ADR-082526-9fa2-the-gates-are-gated-too.md)

## ADR-082526-aef8: Reachability for repository tooling

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep workflow-executed scripts in the same reachable-evidence ladder as production modules and maintain the unreached tooling ledger. Dynamic plugin/string loads must remain modeled so live gates are not falsely classified dead.  
**Current state:** This lets governance ADRs truthfully reach the top design-coverage rung instead of being structurally capped at passing.  
**ADR:** [ADR-082526-aef8](../../../adr/ADR-082526-aef8-reachability-for-repo-tooling.md)

## ADR-082526-cb51: Diff coverage declares measured scope

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep measured roots and workflow producers mechanically synchronized. A changed measured file absent from coverage is a failure, while exemptions must be explicit and reasoned rather than inferred from missing data.  
**Current state:** This closes a dangerous false-green path where broken measurement looked identical to intentional exclusion.  
**ADR:** [ADR-082526-cb51](../../../adr/ADR-082526-cb51-diff-coverage-measured-scope-is-declared.md)

## ADR-082526-ef55: Missing ADR→Spec→AC links are per-change violations

**Status:** Accepted  
**Last updated:** 2026-09-29  
**Next steps:** Keep legacy absence populations ratcheted while enforcing zero newly introduced orphan decisions/specs/criteria per change. Continue deriving base and head with the same text-only logic so comparison artifacts cannot create false violations.  
**Current state:** This prevents new design debt from being paid for by unrelated legacy cleanup and makes traceability a per-change mandate rather than only an aggregate ceiling.  
**ADR:** [ADR-082526-ef55](../../../adr/ADR-082526-ef55-absent-link-chain-per-change-mandate.md)
