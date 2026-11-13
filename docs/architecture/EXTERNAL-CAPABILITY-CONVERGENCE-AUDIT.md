# External capability and standards convergence audit

**Status:** investigation / review proposal, not a decision record or permission to add a dependency.
**Baseline:** Project-mAIstro develop, inspected 2026-11-13 through repository file reads and code search. External references are their public documentation on the same date.
**Scope:** existing implementations **and** accepted/proposed ADRs and specs, including specifications whose status was reverted to Proposed during governance reconciliation.
**Companions:** [Workspace cutover](WORKSPACE-CUTOVER-PLAN.md), [AG-UI spike on draft PR #2411](https://github.com/Agent-StrongHold/Project-mAIstro/blob/feat/ag-ui-canonical-projection-spike/docs/architecture/AG-UI-CONVERGENCE-SPIKE.md), [ADR-039 external-adoption policy](../adr/ADR-039-external-library-adoption-policy.md), [SPEC-277 A2UI](../specs/SPEC-277-a2ui-surface-integration.md).

> Research findings are not acceptance evidence. File inspection proves a code path exists, not that its end-to-end contract works. Tests, version/license/transitive-dependency audits, and reachable production wiring must be verified before a claim of completion. No tests were executed for this audit.

## Executive decision

There is **no case for importing another general-purpose agent orchestration runtime**. mAIstro already owns the canonical Goal / Graph / Run / NodeRun / Attempt lifecycle, durable EventEnvelope and Workspace authority. A new runtime or UI-side store would create a competing authority.

The strongest opportunities are **standardized boundary contracts** and **independent correctness validation**:

1. **AG-UI 1.0**: an agent-to-client protocol adapter, using the pinned 1.0 schema and the official lightweight SDKs where justified. The [draft adapter PR #2411](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2411) is only a CUSTOM-event projection spike; it is not AG-UI stream conformance or a wired endpoint.
2. **A2UI**: keep declarative UI, but reconcile SPEC-277's proposed catalogs/actions with the already implemented governed UI-extension contract (#967). One component authority, not two.
3. **Oracle Open Agent Specification**: test import/export of *portable agent and flow definitions* as an optional edge adapter. Internal ADR-004 AgentSpec is an invocation envelope, not a claim of conformance to Oracle Agent Spec. Existing SPEC-208 exports MCP + SKILL.md; that remains the default narrow export.
4. **Temporal / DBOS**: use their durable-execution guarantees as an adversarial test oracle before replacing any part of mAIstro. Only consider their runtimes if canonical recovery tests expose a gap that cannot be closed cleanly.
5. **Inspect AI**: evaluate as an *external, independent evaluator* for real agent/tool workloads. It need not become the evolutionary fitness authority or a runtime dependency.
6. **Omnara**: study outbound-only machine agents, mobile/operator intervention, offline migration and per-turn workers; retain Workspace Agent / fleet authority.
7. **W3C PROV-O**: test provenance *export/interchange* from Research Lab's canonical memory graph. Do not replace the internal ontology.

## Evidence semantics

- **Code observed:** the named module was fetched from develop. It may still be a fake, library, adapter or unconnected path.
- **Spec observed:** the ADR/spec was read. A Proposed or AC Defined contract does not equal shipped functionality. A status history mentioning Implemented does not override its current status.
- **Research/candidate:** upstream published capability is documented, but a missing mAIstro integration is a hypothesis until a consumer and E2E test are inspected.
- **Search-negative:** code search returned no exact term. Not proof of absence, especially if the implementation uses other names.
- **Disposition:** IMPORT-SDK, COMPAT (thin adapter), VENDOR-REVIEW, ADAPT, EVALUATE, DEFER, REJECT. No permission to install is implied.

## Capability convergence matrix

| Priority | Boundary and external candidate | Existing mAIstro contract and code evidence | Finding / implementation uncertainty | Preliminary disposition |
| --- | --- | --- | --- | --- |
| **P0** | **Agent ↔ frontend: [AG-UI 1.0](https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/spec/1.0/basic/index.mdx)** | [SPEC-081226-7248](../specs/SPEC-081226-7248-event-checkpoint-model.md); [EventEnvelope](../../packages/maistro-core/src/maistro/events/envelope.py); [run-scoped SSE](../../packages/hive-conductor/backend/routes/dag_runs.py); [M8-J](../research/909-human-agent-interaction-generative-ui-mixed-initiative.md) | Canonical stream and scoping exist; no verified AG-UI 1.0 server/client wiring. PR #2411 is deliberately not complete. | **COMPAT** + official schema/SDK conformance. No second Run store. |
| **P0** | **Declarative surfaces: A2UI v0.10** | [ADR-070426-3a1f](../adr/ADR-070426-3a1f-a2ui-declarative-ui-protocol-adoption.md), [SPEC-277](../specs/SPEC-277-a2ui-surface-integration.md), [governed UI #967](../../packages/maistro-core/src/maistro/extensions/ui.py) | Proposed A2UI catalog lifecycle overlaps shipped extension manifest/catalog/action controls. SPEC-277's session lifetime conflicts with persistent Workspace reconstruction unless surface state is projected from durable records. | **AMEND + IMPLEMENT**, reuse #967; reject duplicate registry/authority. |
| **P0** | **Durable execution: [DBOS](https://docs.dbos.dev/python/tutorials/workflow-tutorial), [Temporal](https://docs.temporal.io/encyclopedia/detecting-activity-failures)** | [Event/checkpoint contract](../specs/SPEC-081226-7248-event-checkpoint-model.md); [SPEC-256](../specs/SPEC-256-task-checkpoint-replay.md); [consumer cursor](../../packages/maistro-core/src/maistro/events/consumer_cursor.py); [recovery evidence](../testing/recovery-evidence-pack.md) | SPEC-256 explicitly bounds its work to pure replay and excludes persistence/reissue, external irreversible effects and full recovery orchestration. Other newer recovery modules may close parts of this; verify before declaring a product gap. | **EVALUATE/ADAPT** behavioral crash matrix. **REJECT** wholesale orchestration replacement absent hard evidence. |
| **P0** | **Frontend contract: OpenAPI generated client; possible AsyncAPI** | [Workspace cutover P0.3](WORKSPACE-CUTOVER-PLAN.md); [SPEC-100126-c041](../specs/SPEC-100126-c041-workspace-cutover-phase-0-contract.md); [OpenAPI dump script](../../scripts/dump-hive-openapi.py) | P0.3 is a hard precondition for new Workspace surface consumers. Search did not find AsyncAPI usage; do not impose it unless externally consumed event APIs need a published contract. | **REUSE/ENFORCE** generated types; **DEFER** AsyncAPI until demand. |
| **P1** | **Agent definition ↔ runtime: [Oracle Open Agent Specification](https://github.com/oracle/agent-spec)** | [ADR-004](../adr/ADR-004-agent-spec.md), [AgentSpec model](../../packages/maistro-core/src/maistro/agents/spec/agent_spec.py), [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md), [portability export](../../packages/maistro-core/src/maistro/portability/export.py) | Internal AgentSpec describes spawned-agent invocation, not portable agent/flow topology. SPEC-208 exports MCP + SKILL.md; adding a flow-format adapter is distinct. Avoid conflating identical names. | **COMPAT** import/export spike; optionally **IMPORT-SDK** for offline validation after ADR-039 gate. Do not import foreign runtime. |
| **P1** | **Independent agent evaluation: [Inspect AI](https://inspect.aisi.org.uk/)** | [SPEC-202](../specs/SPEC-202-evolve-fitness-fidelity.md), [Evolve harness](../../packages/maistro-evolve/src/maistro_evolve/harness.py), [M8-J](../research/909-human-agent-interaction-generative-ui-mixed-initiative.md) | SPEC-202 distinguishes proxy and real benchmark fidelity. Its described real adapters cover IFEval and BFCL, not a general independent end-to-end agent environment. Confirm current registry and benchmark execution before claiming any unsupported workload. | **EVALUATE** CI-side or isolated service integration; do not let external eval mutate canonical Runs or fitness truth silently. |
| **P1** | **Human operator ↔ autonomous fleet: [Omnara](https://github.com/omnara-ai/omnara)** | [#804 Workspace Agent / #1046](WORKSPACE-CUTOVER-PLAN.md); [Attention + HITL](../research/909-human-agent-interaction-generative-ui-mixed-initiative.md); [foreign harness SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md) | Omnara documents event-log-backed agent sessions, outbound-only machine daemon, workers that serve turns, cross-machine agent sessions and interactive approval. Overlap is high; most value would be machine-connectivity and operator UX patterns, not importing platform authority. | **ADAPT** via machine/harness provider seams; optional service-boundary pilot. **REJECT** replacement of Workspace runtime. |
| **P1** | **Knowledge provenance interchange: [W3C PROV-O](https://www.w3.org/TR/prov-o/)** | [SPEC-218](../specs/SPEC-218-ontology-semantic-layer.md); [InMemoryOntology](../../packages/maistro-core/src/maistro/ontology/registry.py); [Research Lab PR #2388](https://github.com/Agent-StrongHold/Project-mAIstro/pull/2388) | Internal provenance and graph semantics exist as designs, but SPEC-218 explicitly defers durable ontology / Dynamic facet / memory entity linking. Whether Research Lab needs external PROV consumers is not established. | **COMPAT** optional provenance export and round-trip tests; no RDF/OWL runtime mandate. |
| **P1** | **GenAI trace semantics: OpenTelemetry conventions** | [ADR-037](../adr/ADR-037-observability-taxonomy.md); [OTel tracing](../../packages/maistro-core/src/maistro/observability/tracing.py); [SPEC-070226-2b70](../specs/SPEC-070226-2b70-observability-replay-pii-tiers.md) | OTel API already integrated. Investigate GenAI span/attribute conformance and sensitivity tiers, not another telemetry infrastructure. The GenAI convention has moved into its own OTel repository; pin the target revision. | **ADAPT/CONFORMANCE**, no runtime replacement; prevent prompts/secrets in spans. |
| **P1** | **Cross-runtime agents: A2A** | [ADR-058](../adr/ADR-058-a2a-delegation-protocol.md); [SPEC-182](../specs/SPEC-182-a2a-delegation-implementation.md); [local A2ABroker](../../packages/maistro-core/src/maistro/a2a/broker.py); [API](../../packages/maistro-server/src/maistro_server/api/a2a.py) | SPEC-182 and broker code identify local phases 1–2 and federated egress/audit as follow-up. Verify newest server implementation and protocol version before claiming standards conformance. | **FINISH EXISTING** A2A; use official conformance tests, don't adopt Langroid's orchestration to solve this. |
| **P2** | **Agent messaging: [Langroid](https://github.com/langroid/langroid)** | [ADR-058/SPEC-182](../specs/SPEC-182-a2a-delegation-implementation.md), [canonical orchestration](../../packages/maistro-core/src/maistro/orchestrator/master.py) | Actor-inspired responder pattern, TaskTool, message lineage and rewind are interesting. Rewind must never erase canonical side effects; implement as a new Attempt/compensating event where relevant. | **ADAPT** targeted termination/lineage tests; **REJECT** framework import as second orchestrator. |
| **P2** | **Sandbox machines: [Daytona](https://github.com/daytonaio/daytona) / E2B** | [ADR-093](../adr/ADR-093-sandbox-isolation-model.md), [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md), [sandbox implementations](../../packages/maistro-core/src/maistro/tools/sandbox/docker.py) | SandboxProtocol and microVM/isolation floors already defined. Test real backend isolation, network egress, snapshots, cold-start and cost; don't use the word 'sandbox' as sufficient evidence of ADR-093 compliance. | **EVALUATE** provider adapter/service; keep isolation floor and governance unchanged. |
| **P2** | **External domain events: [CloudEvents](https://cloudevents.io/) / AsyncAPI** | [Canonical EventEnvelope](../../packages/maistro-core/src/maistro/events/envelope.py), [SPEC-081226-7248](../specs/SPEC-081226-7248-event-checkpoint-model.md) | No matching CloudEvents/AsyncAPI paths in targeted search; only potential need when third-party event consumers emerge. CloudEvents cannot become another event sequencing authority. | **DEFER** opt-in export adapter with explicit demand. |
| **P2** | **Tool/skill boundary: MCP / SKILL.md** | [MCP routes](../../packages/hive-conductor/backend/routes/mcp.py), [SPEC-208](../specs/SPEC-208-foreign-harness-adapter.md), [ADR-083](../adr/ADR-083-skills-mcp-trust.md) | Already an explicit project boundary. Importing another tool framework solves no established gap. Focus on authentication, remote transport and safety tests. | **REUSE/HARDEN**, no wholesale import. |

## Highest-value individual investigations and pass/fail criteria

### 1. AG-UI 1.0, A2UI and #967: one interface chain (P0)

**Observed:** [AG-UI 1.0 schema](https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/spec/1.0/schema.json) formalizes event shapes; RUN_STARTED/RUN_FINISHED, messages, state, activities, tools and subagents are distinct events. The first mAIstro spike emits CUSTOM events only. Validating a CUSTOM object alone is **not** enough to claim a compliant stream.

**Proposed chain:** canonical Run + EventStore -> authorized stream projection -> AG-UI 1.0 server adapter -> frontend client -> A2UI renderer, backed by one #967 governed component registry and server-authoritative action dispatch.

**Gate:** complete run lifecycle, reconnect from persisted sequence, two simultaneous clients, approval reauth/idempotency, version negotiation, schema-valid emitted events, unknown event handling and denial of cross-Workspace subscriptions. The frontend must obey Workspace cutover P0.3. No UI persistence becomes canonical truth.

**Decision needed:** amend proposed ADR-070426-3a1f/SPEC-277 to pin compatible AG-UI/A2UI versions, unify catalogs and separate surface presentation from persistent Workspace records. Keep pre-existing clients functioning until parity is proven.

### 2. Portable agent and graph definitions: Oracle Agent Spec (P1)

**Observed:** Oracle defines framework-neutral Agents and Flows; its PyAgentSpec SDK serializes JSON/YAML and includes adapters. Version-specific adapters are not guaranteed: the [26.3.1 release](https://github.com/oracle/agent-spec/releases) explicitly removed the CrewAI adapter over a dependency vulnerability, illustrating the need to pin and audit.

**Minimal spike:** map one read-only, tool-using mAIstro agent and one simple Graph to the selected version's format and back. Persist a semantic-difference report. Unsupported nodes, policies, loops, effects, recursion or HITL must produce explicit errors; never silently drop them. Exports must be credential-free, and imports must be data only until Warden/authority checks. Preserve MCP + SKILL.md export as the default SPEC-208 path.

**Gate:** round-trip structural fidelity for supported primitives; explicit unsupported-construct failures; no runtime execution/side effects during import; host policy remains authoritative; optional pyagentspec dependency passes ADR-039.

### 3. Durable external-effect and crash-window correctness (P0)

**Observed:** [DBOS workflow guarantees](https://docs.dbos.dev/python/tutorials/workflow-tutorial) distinguish completed steps and exactly-once database transactions from retryable external operations. [Temporal's activity documentation](https://docs.temporal.io/encyclopedia/detecting-activity-failures) makes worker heartbeat, timeout and retry behavior explicit. mAIstro already has Event/Checkpoint and idempotent Invocation designs; SPEC-256's pure task replay is not itself an end-to-end resume.

**Required failure matrix:** kill/restart (a) before external call, (b) after external call but before recording response, (c) after DB commit before event publish, (d) during approval settlement, (e) during checkpoint/version migration, (f) while two workers race to resume, and (g) while a consumer cursor advances around a sequence hole.

**Gate:** neither lost approved work nor duplicated irreversible effects; failures that cannot be resolved automatically escalate to the existing human review path; canonical Attempt remains the recovery record; no second queue/ledger without approved ADR. Compare measured failure outcomes to the reference guarantees; do not claim exactly-once for arbitrary external HTTP side effects.

### 4. Omnara remote-machine operations and operator continuity (P1)

**Observed:** [Omnara's architecture](https://github.com/omnara-ai/omnara/blob/main/README.md) includes a daemon that connects outward without inbound machine ports, machine mobility/sandbox fallback, event stream, notifications, human approvals and persisted agents.

**Minimal spike:** compare one mAIstro long-running task on a disconnected machine to a provisioned fallback machine, preserving git/workspace artifacts and canonical Run identity. Test credentials ownership, remote tool grants, machine revocation, duplicate operator actions, disconnect/reconnect and audit continuity. Prefer an adapter to HarnessRunner/SandboxProtocol over a platform import.

**Gate:** fewer manual interventions or shorter recovery time under a repeatable failure drill, *without* exposing credentials to a replacement machine or creating a second lifecycle truth. If no improvement, record pattern-only and stop.

### 5. Independent evaluations with Inspect AI (P1)

**Observed:** [Inspect](https://inspect.aisi.org.uk/) supports agent/tool evaluations, datasets, scorers and isolated execution. SPEC-202 already forbids falsely representing proxies as official benchmarks and documents two real benchmark adapters.

**Minimal spike:** export a fixed mAIstro agent + task set to an external evaluator that scores tool correctness, safety refusal, replay robustness and true task completion. Compare against Evolve's proxy tier, recording source dataset/version and grader, not just a scalar score.

**Gate:** independent reproducibility, no shared mutable evaluation truth, clear provenance and reported disagreement. Run as CI job or isolated service initially, not an automatic promotion authority.

### 6. Research Lab source provenance and typed claims (P1)

**Observed:** [PROV-O](https://www.w3.org/TR/prov-o/) defines Entity, Activity and Agent provenance interchange. mAIstro's SPEC-218 defines only an in-memory Semantic ontology reference, with deferred durability/entity linking; the Research Lab work is still converging.

**Minimal spike:** export and reimport a Topic, source, proposition, derived conclusion, contradictory evidence and revision history in a small PROV-compatible mapping. Define lossless internal identifiers and time semantics; if PROV-O cannot represent confidence/truth values directly, use a documented extension namespace instead of discarding fields.

**Gate:** reconstruct provenance links and source attribution, preserve valid-time vs discovery-time distinction, no fabricated truth conversion and no new memory authority.

## Restraint / rejected shortcuts

- **No Langroid, Omnara, Temporal or DBOS as the core orchestrator** without a separately accepted decision and a failing native invariant they can demonstrably resolve.
- **No A2UI-specific independent security registry** when #967 already governs component manifests/actions. DesignSystem tokens remain the style authority.
- **No Oracle Agent Spec as a new canonical AgentSpec replacement.** Portable definitions live at ingress/egress; policy-bearing executable identity stays in mAIstro.
- **No external evaluator as a second source of lifecycle truth** and no proxy benchmark renamed as official.
- **No protocol adoption solely for feature parity**: require a concrete consumer, differential test and measurable reduction in bespoke code or failure risk.
- **No vendoring by default**: pinned upstream spec and official SDK or compatibility adapter first; vendoring requires source provenance, license/NOTICE, hash verification, patch inventory and CI drift checks.

## Adoption and security gate (ADR-039)

Before an IMPORT-SDK or VENDOR-REVIEW decision is accepted, record the pinned version/commit, license and NOTICE obligations, active maintenance, release and issue health, test/CI coverage, transitive dependency/SBOM review, known vulnerabilities and affected runtime. The core/Stronghold substrate uses ADR-039's stricter dependency posture. Service-boundary execution is preferred when full process import would widen the secret/tool blast radius. An adapter that parses untrusted YAML/JSON must use allowlisted types and must not execute arbitrary deserialization hooks. No external library was installed or vendored during this investigation.

## Proposed sequencing and ownership

| Gate | Work package | Owner/reference | Unlock condition |
| --- | --- | --- | --- |
| **G0** | Approve dispositions; decide which items belong in M1 freeze vs later milestones | ADR-039 + [M1 convergence freeze](M1-CONVERGENCE-FREEZE.md) | Explicit reviewer decision; do not silently expand M1 scope |
| **G1** | Reconcile AG-UI/A2UI/#967 and Workspace typed-client contract | #2411, ADR-070426-3a1f, SPEC-277, #967, SPEC-100126-c041 | One authority, version pin and renderer/action conformance |
| **G2** | Run native crash-window comparison against Temporal/DBOS guarantees | SPEC-256, SPEC-081226-7248, ADR-056 | Executed Postgres, kill/restart, side-effect and concurrency evidence |
| **G3** | Prototype Oracle Agent Spec round-trip | ADR-004, SPEC-208 | Loss report and rejected-construct tests; no imported runtime |
| **G4** | Benchmark Omnara-like machine failover and independent Inspect evaluation | #804 / fleet; SPEC-202 | Quantified operator recovery and reproducible external scoring |
| **G5** | PROV-O mapping for Research Lab; finish A2A federation and GenAI tracing semantics | SPEC-218, SPEC-182, ADR-037 | Consumer-backed provenance and interoperability conformance |

G1 and G2 are engineering-correctness priorities; only their affected contracts should block dependent production UI/runtime migration. G3–G5 are candidates for milestone-scoped discovery; they do **not** automatically block M1 convergence. The quality-gate owner must register acceptance criteria and executed tests in their owning implementation specs; this audit does not impersonate those contracts.

## Investigation backlog: unresolved evidence, not asserted defects

1. **Live AG-UI event map:** compare actual durable event types with PR #2411's provisional allowlist and AG-UI 1.0 event patterns; identify exact server entry point.
2. **P0.3 state:** inspect actual generated frontend types and remaining direct fetch baseline at the current merge base, not just the dated plan.
3. **SPEC-208 coverage:** inspect all native importer and harness provider consumers, not only the export module; distinguish tested code from live activation.
4. **Crash recovery:** review later Graph, Attempt, effect-ledger and checkpoint wiring before concluding the exclusions in SPEC-256 are still system-wide gaps.
5. **SPEC-202 benchmark current state:** run real and proxy harness availability tests with official grader checks; record actual version/data hashes.
6. **Research Lab:** re-evaluate after PR #2388 changes its schemas and confirmed store integration.
7. **External service/provider gate:** verify vendor source license, specific tagged version, release signature/dependency health for every candidate before writing import ADRs.

## Primary sources

- AG-UI 1.0 spec and [schema](https://github.com/ag-ui-protocol/ag-ui/blob/main/docs/spec/1.0/schema.json); [1.0 release announcement](https://github.com/ag-ui-protocol/ag-ui/discussions/2792).
- Oracle [Agent Spec](https://github.com/oracle/agent-spec), [releases](https://github.com/oracle/agent-spec/releases) and [documentation](https://oracle.github.io/agent-spec/development/docs_home.html).
- [Omnara](https://github.com/omnara-ai/omnara/blob/main/README.md), [Langroid](https://github.com/langroid/langroid).
- [DBOS durability semantics](https://docs.dbos.dev/python/tutorials/workflow-tutorial), [Temporal activity failure semantics](https://docs.temporal.io/encyclopedia/detecting-activity-failures).
- [Inspect AI](https://inspect.aisi.org.uk/), [Daytona](https://github.com/daytonaio/daytona).
- [OpenTelemetry semantic conventions](https://opentelemetry.io/docs/specs/semconv/), [W3C PROV-O](https://www.w3.org/TR/prov-o/).

**Next review outcome:** mark each candidate **Adopt, Trial, Learn only, Defer or Reject** with named owner and the acceptance evidence required; keep the audit separate from binding ADR status transitions.
