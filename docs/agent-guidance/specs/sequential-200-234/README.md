# Sequential Specs 200-234

## Builders / Evolve / quality
- **SPEC-200 Builders safety layer — AC Defined.** Preserve ephemeral/isolation requirements but migrate from shadow-git/legacy Builders contexts to canonical GitHub workspaces + ADR-093 sandbox. [SPEC](../../../specs/SPEC-200-builders-safety-layer.md)
- **SPEC-201 Builders interactive runtime — Accepted.** Do not treat its ReAct/Builders lifecycle as canonical; migrate useful turn/HITL behavior into the current autonomous engineering Run pipeline. [SPEC](../../../specs/SPEC-201-builders-dag-runtime.md)
- **SPEC-202 Evolve fitness fidelity — Proposed.** High-value principle: distinguish proxy vs real benchmarks and preserve signal provenance. Integrate with current candidate/eval evidence before promotion. [SPEC](../../../specs/SPEC-202-evolve-fitness-fidelity.md)
- **SPEC-204 Partial-feature hardening — Proposed.** Revalidate each finding against current reachability; delete demo/fake surfaces or make them explicitly honest rather than hardening dead code. [SPEC](../../../specs/SPEC-204-partial-feature-hardening.md)
- **SPEC-205 Test-suite fidelity — Proposed.** Preserve failure-mode/deterministic-time/multiprocess fidelity goals; align with current CI/mutation/reachability standards. [SPEC](../../../specs/SPEC-205-test-suite-fidelity.md)
- **SPEC-206 Policy conformance — Accepted.** Pure comparison engine exists; real invariant registry, prior-policy store, audit/admin workflow remain missing. [SPEC](../../../specs/SPEC-206-policy-conformance-engine.md)
- **SPEC-207 Reflective prompt evolution — Proposed.** Keep propose→verify/held-out evaluation, but integrate with current Evolve candidates, mutation bounds, and provenance. [SPEC](../../../specs/SPEC-207-evolve-reflective-prompt-evolution.md)

## Execution / capabilities / harness
- **SPEC-203 Canvas job lifecycle — Proposed.** Do not create a Canvas-owned background lifecycle; jobs should become canonical Runs/NodeRuns/Attempts with Canvas domain projection. [SPEC](../../../specs/SPEC-203-canvas-job-lifecycle.md)
- **SPEC-208 Foreign harness adapter — Proposed despite implementation history.** Rewrite around harness-as-Provider/Binding/Invocation and canonical Runs; consolidate duplicate governing ADR lineage. [SPEC](../../../specs/SPEC-208-foreign-harness-adapter.md)
- **SPEC-209 Core schemas/registry — Accepted.** Reconcile AgentSpec-era schemas with current NodeTemplate/GraphTemplate/Persona/Binding schemas; retain generic schema registry only where still used/reachable. [SPEC](../../../specs/SPEC-209-core-schemas-and-registry.md)
- **SPEC-210 Structured output parser — Accepted.** Useful generic typed-output primitive; verify current model/harness paths actually use it and avoid creating a second retry authority outside Attempts. [SPEC](../../../specs/SPEC-210-structured-output-parser.md)
- **SPEC-211 Lane scheduling — Proposed.** Replace Task lanes with canonical Run priority/service-class scheduling if still needed. [SPEC](../../../specs/SPEC-211-lane-based-scheduling.md)

## Memory foundation
- **SPEC-212 Memory/session wiring — Proposed.** Reconcile lazy DB-optional wiring with current PostgreSQL durable memory/session ownership. Production durable paths should not silently fall back to memory. [SPEC](../../../specs/SPEC-212-memory-engine-session-wiring.md)
- **SPEC-213 Alembic memory migration — Proposed.** Historical first migration; current schema correctness belongs to current Postgres/pgvector migration tests and pre-1.0 clean-schema policy. [SPEC](../../../specs/SPEC-213-alembic-memory-migration.md)
- **SPEC-214 Memory types/tiers/scopes — Proposed.** Reconcile old org/user/project scope vocabulary with canonical Workspace/Project/principal model and ADR-091 assembly layers. [SPEC](../../../specs/SPEC-214-memory-types-tiers-scopes.md)
- **SPEC-215 Memory protocols — Proposed.** Protocol separation remains useful; ensure current durable implementations conform and add needed protocol queries instead of backend-private access. [SPEC](../../../specs/SPEC-215-memory-protocols.md)
- **SPEC-216 Learning store — Accepted.** In-memory implementation is a useful protocol fixture, not durable production authority. Reconcile auto-promotion/scope semantics with current durable learning/user-model design. [SPEC](../../../specs/SPEC-216-learning-store.md)
- **SPEC-217 Outcome store — Proposed.** Move from in-memory-only analytics to current durable OutcomeStore/provenance/usage contracts. [SPEC](../../../specs/SPEC-217-outcome-store.md)
- **SPEC-218 Ontology semantic layer — Accepted.** Pure semantic registry/types appear healthy; verify production consumers before treating it as active architecture. [SPEC](../../../specs/SPEC-218-ontology-semantic-layer.md)

## Canvas / providers / security / repository
- **SPEC-219 Canvas layer taxonomy — Proposed.** Reconcile with ADR-067 compositor evidence and direct AssetInstance cutover; update previously unverified occlusion DAG criterion from compositor tests. [SPEC](../../../specs/SPEC-219-canvas-layer-taxonomy.md)
- **SPEC-220 Canvas asset store — Accepted.** Verify durable store ownership/scope and current production mounting; remove legacy LayerRecord compatibility. [SPEC](../../../specs/SPEC-220-canvas-asset-store.md)
- **SPEC-221 Canvas asset executor/tool — Accepted.** Complete legacy-tool retirement and canonical Binding/Invocation integration. [SPEC](../../../specs/SPEC-221-canvas-asset-executor-and-tool.md)
- **SPEC-222 Credential pool/rotation — Accepted.** Remeasure after canonical Invocation integration; old detached retry-loop behavior is obsolete. [SPEC](../../../specs/SPEC-222-credential-pool-and-rotation.md)
- **SPEC-223 Secret redaction — Accepted.** Pure redactor is mature; end-to-end log/error/event integration belongs with SPEC-080226-4c1f. [SPEC](../../../specs/SPEC-223-secret-redaction.md)
- **SPEC-224 Test harness — Accepted.** Replace GraphRun-centered integration harness with real composition root + canonical Run/Invocation execution. [SPEC](../../../specs/SPEC-224-test-harness.md)
- **SPEC-225 Intent classifier — Accepted.** Audit production reachability/necessity; map retained routing to current Graph/provider/child-Run architecture or supersede. [SPEC](../../../specs/SPEC-225-intent-classifier.md)
- **SPEC-226 maistro-server task backend — Accepted.** M1-critical migration surface: replace Task backend semantics with canonical Run API/control-plane composition and delete compatibility task execution. [SPEC](../../../specs/SPEC-226-maistro-server-task-backend-boundary.md)
- **SPEC-227 Episodic tiers/store — Accepted.** Reconcile with durable PostgreSQL episodic store and current memory dynamics; in-memory implementation is not production authority. [SPEC](../../../specs/SPEC-227-episodic-memory-tiers-store.md)
- **SPEC-228 Observability baseline gaps — Accepted.** Continue closing durable event/trace/metrics/correlation reachability against ADR-037 and later Event/ExecutionContext decisions. [SPEC](../../../specs/SPEC-228-observability-baseline-gaps.md)
- **SPEC-229 Canvas compositor — Accepted.** Dedicated tests cover scene graph/occlusion/prompt composition; likely close to strict-evidence promotion. [SPEC](../../../specs/SPEC-229-canvas-asset-compositor.md)
- **SPEC-230 DB schema evolution — Accepted.** Needs successor for pre-1.0 clean-schema/direct-cutover policy; do not implement expand/contract compatibility machinery. [SPEC](../../../specs/SPEC-230-db-schema-evolution-migrations.md)
- **SPEC-231 Branch model — Accepted.** Reconcile with current ADR-095 develop→main topology and live Rulesets; retired integration branch must not return. [SPEC](../../../specs/SPEC-231-four-tier-branch-model.md)
- **SPEC-232 Lifecycle linter — Accepted.** Wire into required CI or explicitly replace with equivalent; current governance gap remains. [SPEC](../../../specs/SPEC-232-lifecycle-status-linter.md)
- **SPEC-233 Layer taxonomy schema — Accepted.** Current classification support; ongoing governance rather than runtime feature. [SPEC](../../../specs/SPEC-233-layer-taxonomy-schema.md)
- **SPEC-234 Bundled Open Design systems — Accepted.** Reconcile lifecycle metadata/tests; narrow content/import contract appears close to completion. [SPEC](../../../specs/SPEC-234-bundled-open-design-systems.md)
