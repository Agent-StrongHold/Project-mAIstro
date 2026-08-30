# MAIstro Cross-Product Interoperability Ontology v1

**Status:** M1 freeze candidate  
**Machine-readable contract:** `quality/shared-interop-ontology-v1.json`  
**Owner:** #458

This document is the named cross-product contract for MAIstro. It does not introduce a parallel domain model. It packages the Accepted architecture into one versioned language that Builders, Conductor, Evolve, Canvas/Design, schedules, and later RSI must use when exchanging shared concepts.

## Rule

A shared concept has one canonical identity, one canonical semantic owner, and one versioned meaning. Product-local DTOs and views may project that concept for presentation or transport, but they may not redefine its identity, lifecycle, ownership, or lineage.

The canonical execution chain is:

`Workspace → Project → Graph → Run → NodeRun → Attempt → ExecutionRuntime`

`GraphExecutionState` is traversal state attached to the canonical `Run`; it is not another Run lifecycle.

The canonical governed effect chain is:

`Capability → Provider → Binding → Invocation`

## Shared identities

| Concept | Canonical owner | Canonical identity | Required relationship |
|---|---|---|---|
| Workspace | `maistro.workspaces` | `workspace_id` | scope root |
| Project | `maistro.projects` | `project_id` | belongs to Workspace |
| Persona | `maistro.personas` | `persona_id` | reusable configuration identity |
| Template | `maistro.prompts` | `template_id` | reusable configuration identity |
| Graph | `maistro.graph` | `graph_id` | belongs to Project |
| Run | `maistro.runs` | `run_id` | executes Graph in Project scope |
| GraphExecutionState | `maistro.graph` | `run_id` | traversal state for Run |
| NodeRun | `maistro.runs` | `node_run_id` | belongs to Run |
| Attempt | `maistro.runs` | `attempt_id` | belongs to NodeRun |
| ExecutionRuntime | `maistro.runtime` | `execution_id` | physical execution for Attempt |
| Capability | `maistro.capabilities` | `capability_id` | governed effect definition |
| Provider | `maistro.capabilities` | `provider_id` | implementation of Capability |
| Binding | `maistro.capabilities` | `binding_id` | scoped Provider binding |
| Invocation | `maistro.capabilities` | `invocation_id` | governed effect occurrence |

## Invariants

1. A product must not mint a second authoritative ID for any shared concept above.
2. A product-specific record may retain a local UI or transport identifier only as a projection/reference. Canonical cross-product correlation uses the canonical ID.
3. Lifecycle truth for work is owned by `Run`, `NodeRun`, and `Attempt`. Product state may describe domain progress but may not become a competing universal execution lifecycle.
4. `GraphExecutionState` owns traversal/frontier state only. It cannot independently redefine Run terminality.
5. An `Attempt` maps to one physical `ExecutionRuntime` identity. Retry creates or advances Attempt semantics rather than silently replacing Run identity.
6. Cross-product execution lineage must be recoverable from Workspace/Project through Graph/Run to NodeRun/Attempt.
7. Side effects that are part of the governed effect plane carry canonical Capability/Provider/Binding/Invocation identity.
8. Product adapters may translate wire formats, but semantic reconstruction between independently owned models is not an interoperability contract.
9. Historical records remain interpretable after ontology evolution. Breaking semantic changes require a new ontology version and an explicit compatibility/migration rule.
10. RSI is not an M1 product-convergence blocker, but when it converges in M5 it must consume this contract rather than establish a separate shared model.

## Executable enforcement

`packages/maistro-core/tests/fitness/test_shared_interop_ontology.py` is the blocking conformance surface for ontology v1. It validates the machine contract's semantic version, canonical owners and identities, parent/scope relationships, exact required lineage, M1/M5 consumer assignments, and agreement with this document's shared-identity table and two canonical chains.

The conformance suite also contains planted regressions. A conflicting owner or identity, an unknown or duplicate lineage edge, a lineage relationship that disagrees with concept metadata, a missing required consumer, or documentation drift must make the fitness suite fail. This enforcement protects the contract itself; #460 owns prevention of newly introduced product-local universal owners, and #459 owns live cross-product behavioral parity through real product/store boundaries.

## M1 interoperability proof

M1 product convergence is not complete merely because each product can execute independently against pieces of the spine. At minimum, the parity suite owned by #459 must prove that a Builders-created Graph/Run can be listed and interpreted by Conductor using the same canonical identities and semantics, without product-specific semantic reconstruction.

Schedules, Conductor chat/voice, and Evolve must ultimately enter the same Run universe. Their source-specific metadata may differ; the execution identity does not.

## Evolution policy

The machine-readable contract carries a semantic version. Compatible additive changes increment the minor version. Any change that alters an existing concept's identity, owner, lifecycle meaning, or required lineage is breaking and requires a new ontology version and an explicit compatibility/migration rule owned by #461.

During M1, #460 prevents new universal owners or side runtimes from being introduced as an implicit way around this ontology.
