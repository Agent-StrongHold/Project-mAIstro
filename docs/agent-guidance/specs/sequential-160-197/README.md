# Sequential Specs 160-197

## SPEC-160: maistro-design acceptance
**Status:** Accepted. **Next:** close the known production reachability gap for `design.orchestrate`, then remeasure all ACs. **Current:** implementation/tests are substantial but the node was green-and-unreachable. [SPEC](../../../specs/SPEC-160-maistro-design-acceptance-criteria.md)

## SPEC-175: Task progress webhook
**Status:** AC Defined. **Next:** retire or remap from legacy TaskRunner to canonical Run/Event progress; do not preserve conductor-router compatibility pre-1.0. [SPEC](../../../specs/SPEC-175-task-progress-webhook.md)

## SPEC-176: Hive Conductor package
**Status:** AC Defined. **Next:** reinterpret package existence through ADR-096: Hive is UI/BFF, not execution authority. Remove tests/ACs that require legacy backend ownership. [SPEC](../../../specs/SPEC-176-hive-conductor-package.md)

## SPEC-177: Hyperagent graph execution
**Status:** AC Defined. **Next:** supersede/retire legacy graph executor in favor of SPEC-081226-69ee/a66b/1f7c. Preserve only useful behavior through parity tests. [SPEC](../../../specs/SPEC-177-hyperagent-graph-execution.md)

## SPEC-178: Legacy snapshot retention
**Status:** AC Defined. **Next:** delete obsolete snapshots under the pre-1.0 rule unless needed as explicit migration evidence; no compatibility retention requirement. [SPEC](../../../specs/SPEC-178-legacy-snapshot-retention.md)

## SPEC-179: Flutter gateway node
**Status:** Deprecated. **Next:** none. App tree was removed; do not revive. [SPEC](../../../specs/SPEC-179-flutter-gateway-node.md)

## SPEC-180: maistro-install bootstrap
**Status:** AC Defined. **Next:** use as the current installer foundation and reconcile with SPEC-072726-3439 end-to-end onboarding/current identity. [SPEC](../../../specs/SPEC-180-maistro-install-bootstrap.md)

## SPEC-181: Hive missions → core bridge
**Status:** Proposed. **Next:** replace mission/task bridge with canonical Run admission and Workspace/Project scope; likely superseded by ADR-096/current server boundary. [SPEC](../../../specs/SPEC-181-hive-missions-maistro-core-bridge.md)

## SPEC-182: A2A delegation broker
**Status:** Proposed. **Next:** do not complete the old broker. Map delegation to in-node provenance or child Runs plus canonical capability/provider effects. [SPEC](../../../specs/SPEC-182-a2a-delegation-implementation.md)

## SPEC-183: OAuth2 user auth
**Status:** Proposed. **Next:** rewrite OAuth/OIDC product wiring to authenticate canonical principals/Workspace memberships; retain PKCE/state/provider-subject security mechanics. [SPEC](../../../specs/SPEC-183-oauth2-user-auth-implementation.md)

## SPEC-184: Modular capability platform
**Status:** Proposed. **Next:** supersede its generic slots/toggles with canonical Capability/Provider/Binding/Invocation while migrating useful provider-discovery requirements. [SPEC](../../../specs/SPEC-184-modular-capability-platform.md)

## SPEC-185: Canonical source registry
**Status:** Proposed. **Next:** if federated search remains desired, implement sources as authorized providers under the canonical capability model, with outbound policy and provenance. [SPEC](../../../specs/SPEC-185-canonical-source-registry.md)

## SPEC-186: Knowledge aggregator/cache
**Status:** Proposed. **Next:** separate retrieval/cache concerns from orchestration; use canonical providers and durable provenance. Do not build another graph/state authority. [SPEC](../../../specs/SPEC-186-knowledge-aggregator-cache.md)

## SPEC-187: Infra control/monitor/approval
**Status:** Proposed. **Next:** express monitor/action capabilities as Bindings/Invocations under scoped authority, approvals, sandbox/outbound controls; no bespoke slot authorization. [SPEC](../../../specs/SPEC-187-infra-control-monitor-approval.md)

## SPEC-188: Self-repair loop
**Status:** Proposed. **Next:** rebuild autonomous remediation as canonical Runs using authorized monitor/action capabilities, current approval gates, evidence, and sandbox; preserve detect→diagnose→propose→act concept only. [SPEC](../../../specs/SPEC-188-self-repair-loop.md)

## SPEC-189: Lossless rolling context
**Status:** Proposed. **Next:** reconcile with ADR-091/SPEC-244 and hard physical context limits. "Lossless" cannot mean exceeding provider context; external state may be lossless while assembled prompt is bounded. [SPEC](../../../specs/SPEC-189-lossless-rolling-context-assembly.md)

## SPEC-190: Pluggable sandbox
**Status:** Proposed. **Next:** resolve ADR-093's Tier-1-vs-Tier-2 floor, remove migration compatibility goals, and directly cut untrusted execution to the required isolated backend through canonical capability execution. [SPEC](../../../specs/SPEC-190-pluggable-sandbox-substrate.md)

## SPEC-191: Code-health backlog
**Status:** Proposed. **Next:** convert concrete live findings into issues/quality ratchets and prune findings against deleted/dead code; avoid one giant stale remediation backlog. [SPEC](../../../specs/SPEC-191-code-health-remediation-backlog.md)

## SPEC-192: Persona authoring pipeline
**Status:** Proposed. **Next:** rewrite around current Persona-as-preference model and Template architecture; remove AgentRecipe/roster authority. Split evaluation/scoring from Persona creation. [SPEC](../../../specs/SPEC-192-persona-authoring-pipeline.md)

## SPEC-193: Slot-aware inference gateway
**Status:** Proposed. **Next:** reconcile with current model/provider routing and verify whether the referenced gateway app still exists/reachable. Do not create a second model-routing authority. [SPEC](../../../specs/SPEC-193-slot-aware-inference-gateway.md)

## SPEC-194: Ultra-think parallel generation
**Status:** Proposed. **Next:** if retained, implement as a canonical Graph/Run strategy over current provider routing with explicit cost/evidence, not a gateway-specific parallel runtime. [SPEC](../../../specs/SPEC-194-ultra-think-parallel-generation.md)

## SPEC-195: Operational training data
**Status:** Proposed. **Next:** route any training/eval capture through canonical execution provenance, sensitivity/redaction, consent, and retention. Never scrape unscoped product traces into training data. [SPEC](../../../specs/SPEC-195-operational-training-data.md)

## SPEC-196: Agent builder
**Status:** Proposed. **Next:** map generated agents to Persona/NodeTemplate/GraphTemplate/Bindings rather than AgentRecipe/legacy roster concepts. [SPEC](../../../specs/SPEC-196-agent-builder.md)

## SPEC-197: LLM API capability lanes
**Status:** Proposed. **Next:** reconcile with current Provider/Model registry and canonical scheduling/priority. Avoid parallel "lane" routing authority. [SPEC](../../../specs/SPEC-197-llm-api-capability-lanes.md)
