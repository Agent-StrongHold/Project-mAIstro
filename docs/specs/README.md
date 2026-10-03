# Engine specs (`docs/specs/`)

Numbered specifications that live in this monorepo. Each file is `SPEC-NNN-<slug>.md` with front-matter per [`ADR-031`](../adr/ADR-031-front-matter-and-registry.md).

Frozen **reference** trees that specs ported from (hyperagent bundle, gateway snapshot) were archived under `potential-dead-code/` and have since been **removed** ([SPEC-178](./SPEC-178-legacy-snapshot-retention.md)); provenance lives in git history and the sibling repos.

| ID | Document |
| --- | --- |
| SPEC-175 | [Task progress webhook](SPEC-175-task-progress-webhook.md) |
| SPEC-176 | [Hive Conductor package](SPEC-176-hive-conductor-package.md) |
| SPEC-177 | [Hyperagent graph execution](SPEC-177-hyperagent-graph-execution.md) |
| SPEC-178 | [Legacy snapshot retention](SPEC-178-legacy-snapshot-retention.md) |
| SPEC-179 | [Flutter gateway node](SPEC-179-flutter-gateway-node.md) |
| SPEC-180 | [maistro-install bootstrap contract](SPEC-180-maistro-install-bootstrap.md) |
| SPEC-181 | [Hive missions → maistro-core execution bridge](SPEC-181-hive-missions-maistro-core-bridge.md) |
| SPEC-182 | [A2A delegation broker — implementation](SPEC-182-a2a-delegation-implementation.md) |
| SPEC-183 | [OAuth2 user authentication — implementation](SPEC-183-oauth2-user-auth-implementation.md) |
| SPEC-184 | [Modular capability platform](SPEC-184-modular-capability-platform.md) |
| SPEC-185 | [Canonical source registry](SPEC-185-canonical-source-registry.md) |
| SPEC-186 | [Knowledge aggregator + three-layer cache](SPEC-186-knowledge-aggregator-cache.md) |
| SPEC-187 | [Infra control & monitoring](SPEC-187-infra-control-monitor-approval.md) |
| SPEC-188 | [Self-repair loop](SPEC-188-self-repair-loop.md) |
| SPEC-189 | [Lossless rolling context assembly](SPEC-189-lossless-rolling-context-assembly.md) |
| SPEC-190 | [Pluggable sandbox substrate](SPEC-190-pluggable-sandbox-substrate.md) |
| SPEC-191 | [Code-health remediation backlog](SPEC-191-code-health-remediation-backlog.md) |
| SPEC-192 | [Persona authoring pipeline](SPEC-192-persona-authoring-pipeline.md) |
| SPEC-193 | [Slot-aware local inference gateway](SPEC-193-slot-aware-inference-gateway.md) |
| SPEC-194 | [Ultra Think — tiered parallel diverse generation](SPEC-194-ultra-think-parallel-generation.md) |
| SPEC-195 | [Operational training data collection](SPEC-195-operational-training-data.md) |
| SPEC-091226-1341 | [Gates Ran path-scoped execution evidence](SPEC-091226-1341-gates-ran-path-scope-evaluator.md) |
| SPEC-092626-1831 | [Workspace work campaigns (Proposed)](SPEC-092626-1831-workspace-work-campaigns.md) |
| SPEC-093026-7a90 | [Closed-loop design process contract (Proposed)](SPEC-093026-7a90-closed-loop-design-process-contract.md) |
| SPEC-100126-c041 | [Workspace cutover Phase 0 contract (Proposed)](SPEC-100126-c041-workspace-cutover-phase-0-contract.md) |

<!-- ac-defined-start -->

## AC Defined specs (implementation backlog)

**54 specs** with acceptance criteria defined but not yet fully implemented.
Regenerate: `uv run python scripts/generate-spec-ac-defined-index.py`.

| ID | Title | File |
| --- | --- | --- |
| SPEC-001 | "Bouncer — security screening (20+ regex + LLM)" | [SPEC-001-bouncer.md](SPEC-001-bouncer.md) |
| SPEC-081226-034b | Package Ownership and Dependency Direction | [SPEC-081226-034b-package-ownership-dependency-direction.md](SPEC-081226-034b-package-ownership-dependency-direction.md) |
| SPEC-081226-69ee | Graph and Node Execution Model | [SPEC-081226-69ee-graph-node-execution-model.md](SPEC-081226-69ee-graph-node-execution-model.md) |
| SPEC-081226-6b46 | Capability, Provider, Binding and Invocation | [SPEC-081226-6b46-capability-provider-binding-invocation.md](SPEC-081226-6b46-capability-provider-binding-invocation.md) |
| SPEC-081226-6e34 | Scoped Grants and Deny-Wins Authorization | [SPEC-081226-6e34-hierarchical-permissions.md](SPEC-081226-6e34-hierarchical-permissions.md) |
| SPEC-081226-7248 | Event and Checkpoint Model | [SPEC-081226-7248-event-checkpoint-model.md](SPEC-081226-7248-event-checkpoint-model.md) |
| SPEC-081226-9944 | Canonical Product Hierarchy and Ownership | [SPEC-081226-9944-canonical-product-hierarchy-and-ownership.md](SPEC-081226-9944-canonical-product-hierarchy-and-ownership.md) |
| SPEC-081226-a66b | Run, NodeRun and Attempt Lifecycle | [SPEC-081226-a66b-run-noderun-attempt-lifecycle.md](SPEC-081226-a66b-run-noderun-attempt-lifecycle.md) |
| SPEC-081226-bb3a | Template, Object and Provenance Semantics | [SPEC-081226-bb3a-template-object-provenance-semantics.md](SPEC-081226-bb3a-template-object-provenance-semantics.md) |
| SPEC-081226-e626 | Persona and Product Surface Model | [SPEC-081226-e626-persona-surface-model.md](SPEC-081226-e626-persona-surface-model.md) |
| SPEC-081426-1f7c | ExecutionRuntime Contract | [SPEC-081426-1f7c-execution-runtime-contract.md](SPEC-081426-1f7c-execution-runtime-contract.md) |
| SPEC-081426-b1d3 | Project Scope Tree | [SPEC-081426-b1d3-project-scope-tree.md](SPEC-081426-b1d3-project-scope-tree.md) |
| SPEC-082926-061d | Convergence Matrix Unreachable Share | [SPEC-082926-061d-convergence-matrix-unreachable-share.md](SPEC-082926-061d-convergence-matrix-unreachable-share.md) |
| SPEC-082926-0b72 | Conductor Settings Durability | [SPEC-082926-0b72-conductor-settings-durability.md](SPEC-082926-0b72-conductor-settings-durability.md) |
| SPEC-082926-25a2 | AC-State Per-Branch Notes | [SPEC-082926-25a2-ac-state-per-branch-notes.md](SPEC-082926-25a2-ac-state-per-branch-notes.md) |
| SPEC-082926-2844 | Attempt typed output serialization | [SPEC-082926-2844-attempt-typed-output-serialization.md](SPEC-082926-2844-attempt-typed-output-serialization.md) |
| SPEC-082926-3b80 | Conductor Dashboard Layout Durability | [SPEC-082926-3b80-conductor-dashboard-layout-durability.md](SPEC-082926-3b80-conductor-dashboard-layout-durability.md) |
| SPEC-082926-6f49 | A corrected measurement can lower an AC-state floor; a regression still cannot | [SPEC-082926-6f49-authorized-floor-fall-for-a-corrected-measurement.md](SPEC-082926-6f49-authorized-floor-fall-for-a-corrected-measurement.md) |
| SPEC-082926-730d | Container Pool Ownership | [SPEC-082926-730d-container-pool-ownership.md](SPEC-082926-730d-container-pool-ownership.md) |
| SPEC-082926-a44e | A parked schedule Run resumes where it stopped, or stays parked | [SPEC-082926-a44e-resume-a-parked-schedule-run-without-repeating-its-effects.md](SPEC-082926-a44e-resume-a-parked-schedule-run-without-repeating-its-effects.md) |
| SPEC-082926-c2d7 | An ac-modules anchor must name a module the reachability graph knows | [SPEC-082926-c2d7-ac-modules-anchor-must-resolve.md](SPEC-082926-c2d7-ac-modules-anchor-must-resolve.md) |
| SPEC-082926-d90e | Schedule consumer node invocation fidelity | [SPEC-082926-d90e-schedule-consumer-node-fidelity.md](SPEC-082926-d90e-schedule-consumer-node-fidelity.md) |
| SPEC-082926-f1c3 | The reachability baseline is written in module identities | [SPEC-082926-f1c3-reachability-baseline-module-identity.md](SPEC-082926-f1c3-reachability-baseline-module-identity.md) |
| SPEC-083026-14c3 | Repairing an emptied Attempt output carries its accepted outcome, or reports why it cannot | [SPEC-083026-14c3-repairing-an-emptied-attempt-output.md](SPEC-083026-14c3-repairing-an-emptied-attempt-output.md) |
| SPEC-083026-20b2 | "The canonical execution ids reach every log line, span and event" | [SPEC-083026-20b2-execution-correlation-context-binding.md](SPEC-083026-20b2-execution-correlation-context-binding.md) |
| SPEC-083026-2601 | DAG run history is durable, bounded on purpose, and reports what it holds | [SPEC-083026-2601-dag-run-history-is-durable-and-bounded-on-purpose.md](SPEC-083026-2601-dag-run-history-is-durable-and-bounded-on-purpose.md) |
| SPEC-083026-2642 | Node metrics are measured or absent, and the ingest that reads them has a caller | [SPEC-083026-2642-node-metrics-are-measured-or-absent.md](SPEC-083026-2642-node-metrics-are-measured-or-absent.md) |
| SPEC-083026-427c | Prompt version creation and label promotion are one serialized, idempotent write | [SPEC-083026-427c-serialized-prompt-versions-and-labels.md](SPEC-083026-427c-serialized-prompt-versions-and-labels.md) |
| SPEC-083026-4b70 | "memory_entries.embedding holds vectors, and its type is asserted rather than assumed" | [SPEC-083026-4b70-memory-entries-embedding-is-a-vector.md](SPEC-083026-4b70-memory-entries-embedding-is-a-vector.md) |
| SPEC-083026-56ee | "A session turn names its producing Run, and an outcome names its session" | [SPEC-083026-56ee-a-session-turn-names-its-producing-run.md](SPEC-083026-56ee-a-session-turn-names-its-producing-run.md) |
| SPEC-083026-58de | The thumbs signal is durable, and is read through the store protocol | [SPEC-083026-58de-thumbs-are-durable-and-read-through-the-protocol.md](SPEC-083026-58de-thumbs-are-durable-and-read-through-the-protocol.md) |
| SPEC-083026-5fab | A retried turn appends its session messages once, under an identity it was given | [SPEC-083026-5fab-a-retried-turn-appends-its-messages-once.md](SPEC-083026-5fab-a-retried-turn-appends-its-messages-once.md) |
| SPEC-083026-6bc5 | A design project's scope is writable on a clean database and enforced on every read | [SPEC-083026-6bc5-design-project-scope-is-writable-and-enforced.md](SPEC-083026-6bc5-design-project-scope-is-writable-and-enforced.md) |
| SPEC-083026-6cef | A turn reports the usage it was given, and the unreached layer says it is unreached | [SPEC-083026-6cef-a-turn-reports-the-usage-it-was-given.md](SPEC-083026-6cef-a-turn-reports-the-usage-it-was-given.md) |
| SPEC-083026-73c1 | Durable HITL timeout and cancellation | [SPEC-083026-73c1-hitl-timeout-cancel.md](SPEC-083026-73c1-hitl-timeout-cancel.md) |
| SPEC-083026-b2b5 | "Learnings, outcomes and design outputs carry their producing execution" | [SPEC-083026-b2b5-record-producer-provenance.md](SPEC-083026-b2b5-record-producer-provenance.md) |
| SPEC-083026-ba26 | Episodic memory survives a restart, and its scope rule is written once | [SPEC-083026-ba26-episodic-memory-survives-a-restart.md](SPEC-083026-ba26-episodic-memory-survives-a-restart.md) |
| SPEC-083026-ef62 | A user profile is durable, deletable, and has exactly one owner | [SPEC-083026-ef62-user-profile-durability-and-deletion.md](SPEC-083026-ef62-user-profile-durability-and-deletion.md) |
| SPEC-083026-fcc9 | "A grant independent landings have durably superseded can be pruned" | [SPEC-083026-fcc9-a-grant-superseded-by-independent-landings-can-be-pruned.md](SPEC-083026-fcc9-a-grant-superseded-by-independent-landings-can-be-pruned.md) |
| SPEC-083126-5e62 | "Generated quality evidence is not the judge after trusted-base migration" | [SPEC-083126-5e62-generated-quality-evidence-is-not-the-judge.md](SPEC-083126-5e62-generated-quality-evidence-is-not-the-judge.md) |
| SPEC-090226-e4a1 | "An episodic memory names the execution that stored it" | [SPEC-090226-e4a1-episodic-memory-names-its-producing-run.md](SPEC-090226-e4a1-episodic-memory-names-its-producing-run.md) |
| SPEC-090326-b7e2 | Browser navigation governed by the canonical outbound policy | [SPEC-090326-b7e2-browser-navigation-canonical-outbound-policy.md](SPEC-090326-b7e2-browser-navigation-canonical-outbound-policy.md) |
| SPEC-091226-1341 | "Gates Ran path-scoped execution evidence" | [SPEC-091226-1341-gates-ran-path-scope-evaluator.md](SPEC-091226-1341-gates-ran-path-scope-evaluator.md) |
| SPEC-091726-7c2a | "A requirements interview precedes every Goal and CreativeBrief commit" | [SPEC-091726-7c2a-brief-interview-before-goal-commit.md](SPEC-091726-7c2a-brief-interview-before-goal-commit.md) |
| SPEC-092826-a774 | CreativeBrief is a versioned Design Studio projection of one canonical Goal revision | [SPEC-092826-a774-creative-brief-contract.md](SPEC-092826-a774-creative-brief-contract.md) |
| SPEC-100126-b779 | "Cross-artifact consistency evaluation and targeted refinement" | [SPEC-100126-b779-cross-artifact-consistency-evaluation.md](SPEC-100126-b779-cross-artifact-consistency-evaluation.md) |
| SPEC-175 | Task progress webhook (conductor-router compatibility) | [SPEC-175-task-progress-webhook.md](SPEC-175-task-progress-webhook.md) |
| SPEC-176 | Hive Conductor monorepo package | [SPEC-176-hive-conductor-package.md](SPEC-176-hive-conductor-package.md) |
| SPEC-177 | Hyperagent graph execution (legacy port) | [SPEC-177-hyperagent-graph-execution.md](SPEC-177-hyperagent-graph-execution.md) |
| SPEC-178 | Legacy snapshot directories — retention and removal | [SPEC-178-legacy-snapshot-retention.md](SPEC-178-legacy-snapshot-retention.md) |
| SPEC-180 | maistro-install bootstrap contract | [SPEC-180-maistro-install-bootstrap.md](SPEC-180-maistro-install-bootstrap.md) |
| SPEC-200 | Builders Safety Layer — execution contexts + ephemeral workspace | [SPEC-200-builders-safety-layer.md](SPEC-200-builders-safety-layer.md) |
| SPEC-244 | "ContextAssemblyPolicy — Layer 0-4 memory assembly (ADR-091)" | [SPEC-244-context-assembly-policy.md](SPEC-244-context-assembly-policy.md) |
| SPEC-256 | "Task crash recovery — checkpoint replay and crash-loop quarantine core (ADR-056)" | [SPEC-256-task-checkpoint-replay.md](SPEC-256-task-checkpoint-replay.md) |

<!-- ac-defined-end -->
