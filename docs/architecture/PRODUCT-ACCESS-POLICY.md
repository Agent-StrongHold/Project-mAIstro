# MAIstro product access policy and interface gaps

**Owner clarification:** 2026-10-03. **Scope:** product interface and application-service
responsibilities, separate from the serialized [interoperability ontology](INTEROP-ONTOLOGY-v1.md).

This policy does not add concepts, fields or serialized principles to `InteropOntology` or
change its `1.1.0` machine contract. It states how product interfaces must consume the existing
canonical services; it is not a claim that the current machine registry validates interface
parity. Any future change to the encoded ontology must follow that contract's versioning and
serialization rules explicitly. Product implementation and proof gaps remain open below.

## One product, three access paths — owner clarification 2026-10-03

MAIstro is one product. Workspace UI, CLI and API are three ways to access the same
features, the same Agent and the same tools. “Same Agent” means the common product-facing
Agent/tool contract and authority across interfaces; internal specialized agents, delegation
and domain roles remain valid and governed by that contract. Workspace encompasses every product
UI surface. Builders, Evolve and RSI are feature families within this product, not independent
products or execution/business-rule authorities. The historical “cross-product” terminology
in this contract names cross-package/feature integration; it does not permit separate products
inside this repository. Downstream packaging and isolation boundaries are unchanged.

This is stronger than matching DTOs or types. All three access paths must invoke the same
canonical capability and application-service authority for admission, scope/authorization,
Agent/tool selection, execution, approvals, cancellation/retry, durable state, events and
inspection. A CLI command or UI route cannot implement a second business rule or silently
select a private agent/tool registry. Transport, authentication entry mechanics and presentation
may differ; the resulting principal/scope and governed behavior must agree.

API and Workspace UI should have near feature parity. The CLI exposes the same functionality
with interface-appropriate presentation, including commands/structured output for operations
represented visually in Workspace. A temporary gap must be named with its owning work item,
release scope and reason; it cannot become an independent backend or an unsupported claim of
parity. Feature availability and authorization gates apply consistently across interfaces.

Domain-specific state and algorithms remain legitimate: Builders stage/spec artifacts,
Evolve populations/evaluation/lineage and RSI candidates/quarantine need not become the same
objects. They use canonical Run/NodeRun/Attempt and Capability/Provider/Binding/Invocation
services, one event/observer contract and the shared Run inspection surface. Domain receipts,
continuations and search algorithms do not create another universal execution lifecycle.
Security, isolation, privacy, budgets and approval requirements are not weakened by parity.

**Proof still required.** For each exposed feature, exercise equivalent UI/API/CLI intents
against the same scoped Agent/capability and compare canonical admission, allowed/refused
outcomes, Run/Invocation identity, durable effects and observable state. Presentation need not
be pixel-identical. Builders/Evolve/RSI work must be observable through the same Run browser.
These are target requirements, not a statement that interface parity or convergence ships today.
Release milestones remain in [ROADMAP.md](../../ROADMAP.md); this clarification does not move
the existing v1.0/v1.2 Evolution UI boundary. The owner explicitly retained that staged UI
release on 2026-10-03, with no interim compatibility layer or duplicate feature/Agent/tool
authority built to bridge it later. Implement the eventual interface on the canonical shared
services directly; retain necessary external-protocol adapters, data migration/import and
security boundaries.

## Interface gap ownership — 2026-10-03

[Issue #1874](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1874) owns the finite,
source-grounded UI/API/CLI feature and gap inventory under [#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449).
The initial rows below are **open work**, not a complete capability census or parity evidence.
#1874 must enumerate every actual entry point, fill unknown counterparts and name the existing
implementation owner/release scope before claiming coverage of a release. It does not move
feature milestones, create a parallel implementation epic or authorize new compatibility layers.

| Capability/access gap | Verified implementation/proof owner | Existing scope and reason still open | Required next evidence |
|---|---|---|---|
| Complete feature-by-feature Workspace/API/CLI inventory, including currently unknown counterparts | [#1874](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1874), release coordination [#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449) | Inventory for the supported set of each release; dates stay with existing feature owners. No complete three-interface inventory exists yet. | Registered UI controls, routes and commands mapped to one service authority; each gap has owner, release, reason and exact-commit evidence. |
| Shared Run inspection/control across interfaces | [#1036](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1036); richer Goal UX [#65](https://github.com/Agent-StrongHold/Project-mAIstro/issues/65) | M1 canonical seam vs M3 product UX; shared state/control and UI/API/CLI equivalence are still acceptance work. | Equivalent scoped list/detail/control results, canonical IDs and restart/reconnect behavior; consume [#459](https://github.com/Agent-StrongHold/Project-mAIstro/issues/459) strict proof. |
| Builders CLI/TUI and other feature surfaces use canonical execution | [#49](https://github.com/Agent-StrongHold/Project-mAIstro/issues/49), CLI [#1068](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1068), proof [#459](https://github.com/Agent-StrongHold/Project-mAIstro/issues/459) | M1/v1.0 convergence; a shipped CLI loop and test-only adapter are not shared service authority. Missing UI/API counterparts remain inventory work under #1874. | Real CLI-backed turn enters canonical Run/Attempt/Invocation and is inspectable/control-compatible; preserve ReAct domain UX. |
| Workspace Home controls accessible without requiring its UI | [#1046](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1046), [#1048](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1048) | M3; v1.0 Home scope stays in the cutover plan. API/Agent/UI operations have an owner, but full CLI equivalence is not yet inventoried. | Canonical layout/resource operations and refusal outcomes through each supported access path; #1874 assigns missing command counterparts. |
| Evolve Workspace surface | [#51](https://github.com/Agent-StrongHold/Project-mAIstro/issues/51) canonical runtime; [BACKLOG conductor-411](../../BACKLOG.md) UI staging | UI explicitly staged at v1.2, confirmed by owner; backend convergence remains M1. No interim feature backend or private Agent/tools. | Implement eventual Workspace UI on existing canonical services; #1874 enumerates equivalent API/CLI operations and explicit temporary presentation gaps. |
| RSI interfaces and authorized work-source consumption | [#50](https://github.com/Agent-StrongHold/Project-mAIstro/issues/50) | Existing gated M5 scope; RSI is excluded from M1 execution proof, not a separate product. No version advancement here. | Same public work-source/Run/inspection services after containment; register UI/API/CLI gaps under #1874 before claiming parity. |
| Legacy browser CLI page | [#292](https://github.com/Agent-StrongHold/Project-mAIstro/issues/292) | Bounded page/command contract; its tracker scope and v1.0 cutover projection are not a complete product-CLI inventory. | Honest command support, policy/audit and backend-unavailable evidence; no simulated execution. |

External CLI-Anything bundles (`engine-092`) and later self-CLI generation (`engine-093`)
are not substitutes for #1874. This matrix does not relabel or close any owner issue, and an
unverified row cannot be counted as an implemented feature or an accepted permanent omission.
