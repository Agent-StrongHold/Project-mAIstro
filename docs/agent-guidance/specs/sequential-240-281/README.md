# Sequential Specs 240-281

## Memory
- **SPEC-240 decay/reinforcement — Accepted.** Pure mechanics are tested; production scheduling/reachability belongs to SPEC-080126-9e42. [SPEC](../../../specs/SPEC-240-memory-decay-reinforcement.md)
- **SPEC-241 consolidation — Accepted.** Pure merge/contradiction mechanics exist; verify durable-store/event scheduling and newer contradiction-resolution follow-up. [SPEC](../../../specs/SPEC-241-memory-consolidation.md)
- **SPEC-242 cross-scope consent — Accepted.** Reconcile old scopes with canonical principals/Workspace/Project and newer same-user UserModelFact self-consent. [SPEC](../../../specs/SPEC-242-memory-cross-scope-consent.md)
- **SPEC-243 retrieval ranking — Accepted.** Verify hybrid ranking is on the real durable recall path and embedding/provider configuration is current. [SPEC](../../../specs/SPEC-243-memory-retrieval-ranking.md)
- **SPEC-244 context assembly — AC Defined.** Correct the hard-context flaw from ADR-091: protected memories may displace lower-priority content but cannot exceed physical model context. [SPEC](../../../specs/SPEC-244-context-assembly-policy.md)
- **SPEC-249 exposure mode — Accepted.** Pure gate exists; concrete durable-store/read integration remains in SPEC-062126-6a31. [SPEC](../../../specs/SPEC-249-memory-exposure-mode.md)
- **SPEC-250 session search — Accepted.** Pure snippet/cursor core exists; canonical route/auth/storage/performance/OTel integration remains missing. [SPEC](../../../specs/SPEC-250-session-search-snippets.md)
- **SPEC-262 memory scope truth table — Proposed.** Update truth table to canonical Workspace/Project/principal/UserModelFact semantics and use one shared helper across stores. [SPEC](../../../specs/SPEC-262-memory-scope-policy-truth-table.md)

## Authorization / tools
- **SPEC-245 tier ladder — Accepted.** Reconcile old global role/tier assumptions with scoped deny-wins grants; retain ADR-068 evaluation ordering where still current. [SPEC](../../../specs/SPEC-245-authz-tier-ladder.md)
- **SPEC-246 approver graph — Accepted.** Useful relational approver primitive; map identities/scopes to canonical principals. [SPEC](../../../specs/SPEC-246-authz-approver-graph.md)
- **SPEC-247 elevation flows — Accepted.** Reconcile re-auth/2FA flows with canonical sessions and ADR-090726-9a4e WebAuthn/Biscuit/hash-chain approval design. [SPEC](../../../specs/SPEC-247-authz-elevation-flows.md)
- **SPEC-248 RLPHD — Accepted.** Keep glass-box predictive approval bounded by hard security limits; verify whether RLPHD remains active scope and never let it clear budget/structural denies. [SPEC](../../../specs/SPEC-248-rlphd-predictive-approval.md)
- **SPEC-252 reversibility taxonomy — Accepted.** Migrate classification/compensators from legacy tool registration to canonical Binding/Invocation; do not revive unreachable registry paths. [SPEC](../../../specs/SPEC-252-tool-reversibility-taxonomy.md)
- **SPEC-253 approval gates — Accepted.** Migrate decision core to canonical Invocation/durable approvals/current crypto evidence; old ApprovalGate island is not the target. [SPEC](../../../specs/SPEC-253-tool-approval-gates.md)
- **SPEC-257 code registry core — Accepted.** Pure resolve/signature core exists; do not build a parallel invoke executor. Represent retained executable code as governed capability/provider or supersede. [SPEC](../../../specs/SPEC-257-code-registry-resolve-core.md)
- **SPEC-258 repertoire core — Accepted.** Generic cascade exists but is unreachable; decide vocabulary/pattern vs mandatory shared runtime before further wiring. [SPEC](../../../specs/SPEC-258-repertoire-pattern-core.md)

## Deprecated/legacy execution
- **SPEC-251 outbound delivery — Proposed but governing ADR-047 is Deprecated.** No implementation work; delete unreachable gateway or create a new notification capability decision. [SPEC](../../../specs/SPEC-251-outbound-delivery-gateway.md)
- **SPEC-254 shadow git — Proposed; governing ADR Deprecated.** No implementation work; current engineering uses real Git worktrees/branches/PRs. [SPEC](../../../specs/SPEC-254-shadow-git-workspace.md)
- **SPEC-255 parallel wave fan-in — Proposed; governing ADR Deprecated.** Do not reconnect. Parallel work belongs on canonical Runs/workspaces/current engineering fleet. [SPEC](../../../specs/SPEC-255-parallel-wave-fan-in.md)
- **SPEC-256 task checkpoint replay — AC Defined but obsolete authority.** Migrate surviving crash-loop/recovery requirements into canonical Run recovery; do not complete TaskCheckpoint lifecycle. [SPEC](../../../specs/SPEC-256-task-checkpoint-replay.md)

## Contract-hardening specs 263-281
- **SPEC-263 graph optimizer prompt rendering — current contract-hardening.** Preserve exact prompt/render semantics only where optimizer remains reachable; bind to canonical graph objects. [SPEC](../../../specs/SPEC-263-graph-optimizer-prompt-rendering-contracts.md)
- **SPEC-264 quality scanner baselines.** Keep reproducible baselines and ratchets; do not normalize away new findings. [SPEC](../../../specs/SPEC-264-quality-scanner-baselines.md)
- **SPEC-265 graph execution exception accounting.** Keep every physical failure represented in canonical Attempt/NodeRun/Run evidence. [SPEC](../../../specs/SPEC-265-graph-execution-exception-accounting.md)
- **SPEC-266 tool guardrail policy table.** Converge guardrails onto canonical capability/Invocation policy and current Sentinel authorization. [SPEC](../../../specs/SPEC-266-tool-guardrail-policy-table.md)
- **SPEC-267 HTTP middleware policy contracts.** Keep auth/security middleware behavior explicit and fail closed; reconcile Hive-specific identity with canonical principals. [SPEC](../../../specs/SPEC-267-http-middleware-policy-contracts.md)
- **SPEC-268 engine task submission contracts.** Migrate Task submission semantics to canonical Run admission; do not preserve Task as an execution owner. [SPEC](../../../specs/SPEC-268-engine-task-submission-contracts.md)
- **SPEC-269 external payload normalization.** High-value ingress contract: normalize/validate untrusted payloads before domain use and Warden/Sentinel boundaries. [SPEC](../../../specs/SPEC-269-external-payload-normalization-contracts.md)
- **SPEC-270 credential pool selection.** Reconcile with September Invocation-integrated credential routing and use as selection/fallback conformance evidence. [SPEC](../../../specs/SPEC-270-credential-pool-selection-contracts.md)
- **SPEC-271 dead-code route baseline.** Keep reachability/dead-route census as a ratchet and delete unwanted surfaces rather than allowlisting them indefinitely. [SPEC](../../../specs/SPEC-271-dead-code-route-surface-baseline.md)
- **SPEC-272 node-run retry/beam.** Ensure retry/beam semantics create canonical Attempts/NodeRuns according to logical occurrence rules; no hidden executor state. [SPEC](../../../specs/SPEC-272-node-run-retry-and-beam-contracts.md)
- **SPEC-273 DAG validation fixtures.** Keep deterministic validation contracts aligned with canonical Graph definitions. [SPEC](../../../specs/SPEC-273-dag-validation-contract-fixtures.md)
- **SPEC-274 bootstrap plan golden contracts.** Keep installer plan generation deterministic while allowing intentional pre-1.0 schema/config replacement. [SPEC](../../../specs/SPEC-274-bootstrap-plan-golden-contracts.md)
- **SPEC-275 registry CLI pipeline.** Keep registry tooling explicit/reachable; ensure it does not mutate architecture authority outside ADR/SPEC governance. [SPEC](../../../specs/SPEC-275-registry-cli-command-pipeline.md)
- **SPEC-276 adapter port ownership.** Preserve dependency inversion/package ownership and eliminate adapters that secretly own domain semantics. [SPEC](../../../specs/SPEC-276-adapter-port-ownership.md)
- **SPEC-277 A2UI integration.** Remains tied to Proposed A2UI ADR; ensure UI actions route through canonical authorization/Invocation and cannot become an effect side-channel. [SPEC](../../../specs/SPEC-277-a2ui-surface-integration.md)
- **SPEC-278 CapabilityProfile.** Remains tied to Proposed ADR; competence/cost may be measured, but persisted permission must not become a parallel authorization truth. [SPEC](../../../specs/SPEC-278-capability-profile-schema-and-updater.md)
- **SPEC-279 Session Trust Floor.** Threat-model irreversible trust-floor poisoning/DoS before acceptance; provenance risk must not become a second authorization system. [SPEC](../../../specs/SPEC-279-session-trust-floor.md)
- **SPEC-280 Cross-model fallback.** Reconcile with the fallback chain already implemented at current provider/Invocation boundary; likely historical implementation plan rather than new work. [SPEC](../../../specs/SPEC-280-cross-model-llm-fallback.md)
- **SPEC-281 Harness lift measurement.** Use measurements to decide whether foreign harness adapters actually improve capability/quality/cost; keep evaluation on canonical Run/Invocation evidence. [SPEC](../../../specs/SPEC-281-harness-lift-measurement.md)
