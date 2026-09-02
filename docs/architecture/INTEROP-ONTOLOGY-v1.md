# MAIstro Cross-Product Interoperability Ontology v1

**Status:** M1 freeze candidate  
**Current v1 version:** `1.1.0`  
**Machine-readable contract:** `quality/shared-interop-ontology-v1.json`  
**Importable contract:** `maistro.interop.INTEROP_ONTOLOGY_V1`  
**Owner:** #458

This document is the named cross-product contract for MAIstro. It does not introduce a parallel domain model. It packages the accepted architecture into one versioned language that Builders, Conductor, Evolve, Canvas/Design Studio, schedules, the persistent Workspace Agent, and later RSI must use when exchanging shared concepts.

## Rule

A shared concept has one canonical identity, one canonical semantic owner, and one versioned meaning. Product-local DTOs and views may project that concept for presentation or transport, but they may not redefine its identity, lifecycle, ownership, or lineage.

The canonical scope and desired-outcome hierarchy is:

`Workspace → Project → Goal`

The canonical accountability relationship is:

`Agent → owns Goal`

Exactly one `Agent` owns a `Goal` at a time. Reassignment or Subgoal delegation changes accountability explicitly; it does not create a second Goal type or grant authorization.

The canonical physical execution chain is:

`Graph → Run → NodeRun → Attempt → ExecutionRuntime`

A Project-scoped `Goal` may select zero, one, or many `Graph` strategies and may accumulate zero, one, or many `Run` records as execution evidence. A `Graph` is a plan/tool, never the accountable Goal owner. A completed or failed `Run` is evidence and does not silently become Goal terminal truth. Infrastructure/system Runs outside Goal semantics remain valid, so Goal is not forced into the physical execution parent chain.

`GraphExecutionState` is traversal state attached to the canonical `Run`; it is not another Run lifecycle.

`Persona` supplies behavioral flavor to an `Agent`. It is not authorization, Goal state, Graph state, or execution state.

The canonical governed effect chain is:

`Capability → Provider → Binding → Invocation`

## Executable surface

`maistro.interop.INTEROP_ONTOLOGY_V1` is the importable registry for the contract below. It exposes canonical owner/identity metadata, typed semantic relationships, validation for product projections, canonical parent/scope references, exact revision requirements where defined, and ontology-version compatibility.

It is metadata over canonical semantic owners, not a second set of Workspace, Project, Agent, Goal, Graph, Run, Capability, or other domain objects. The ontology can name a semantic owner before later milestone behavior is implemented; for example, M3 #804/#805/#806 consume canonical Goal semantics rather than defining a new Goal store or lifecycle.

The executable registry and `quality/shared-interop-ontology-v1.json` are required to serialize identically. A contract test fails if either representation drifts. Product migration onto this surface remains owned by the product/seam convergence issues; #459 owns the Builders → Conductor cross-product execution proof.

## Shared identities

| Concept | Canonical owner | Canonical identity | Required relationship |
|---|---|---|---|
| Workspace | `maistro.workspaces` | `workspace_id` | scope root |
| Project | `maistro.projects` | `project_id` | belongs to Workspace |
| Agent | `maistro.agents` | `agent_id` | scoped to Workspace |
| Persona | `maistro.personas` | `persona_id` | behavioral flavor, never authorization |
| Template | `maistro.prompts` | `template_id` | reusable configuration identity |
| Goal | `maistro.goals` | `goal_id` + `goal_revision` | belongs to Project; exactly one accountable Agent owner |
| Graph | `maistro.graph` | `graph_id` | Project-scoped execution strategy |
| Run | `maistro.runs` | `run_id` | executes Graph in Project scope |
| GraphExecutionState | `maistro.graph` | `run_id` | traversal state for Run |
| NodeRun | `maistro.runs` | `node_run_id` | belongs to Run |
| Attempt | `maistro.runs` | `attempt_id` | belongs to NodeRun |
| ExecutionRuntime | `maistro.runtime` | `execution_id` | physical execution for Attempt |
| Capability | `maistro.capabilities` | `capability_id` | governed effect definition |
| Provider | `maistro.capabilities` | `provider_id` | implementation of Capability |
| Binding | `maistro.capabilities` | `binding_id` | scoped Provider binding |
| Invocation | `maistro.capabilities` | `invocation_id` | governed effect occurrence |

## Typed relationships

The machine contract records relationships separately from physical execution lineage when the semantics are not containment.

| Relationship | Meaning | Cardinality invariant |
|---|---|---|
| Project → Goal | desired-outcome scope | each Goal has exactly one Project; a Project may have many Goals |
| Agent → Goal | accountability | each Goal has exactly one owning Agent; an Agent may own many Goals |
| Goal → Goal | Subgoal lineage | a Goal may have one parent Goal and many child Subgoals |
| Goal → Graph | execution-strategy selection | many-to-many over a Goal lifetime; not ownership |
| Goal → Run | execution evidence | a goal-driven Run binds to at most one Goal context; a Goal may accumulate many Runs |
| Persona → Agent | behavioral flavor | an Agent may have at most one Persona binding; Persona does not grant authority |

The exact Goal revision consumed by a goal-driven Run or artifact must remain recoverable. A later Goal revision must not rewrite historical evidence. The v1 contract therefore requires `goal_revision` whenever a product projects a canonical Goal.

## Invariants

1. A product must not mint a second authoritative ID for any shared concept above.
2. A product-specific record may retain a local UI or transport identifier only as a projection/reference. Canonical cross-product correlation uses the canonical ID.
3. `Workspace → Project → Goal` is scope/desired outcome. `Agent → Goal` is accountability. Neither relationship is a Run lifecycle.
4. Exactly one Agent owns a Goal at a time. Delegation/reassignment is explicit and does not grant capabilities, permissions, or approvals.
5. Goal lifecycle is distinct from Run lifecycle. Run success/failure is evidence, not automatic Goal completion/failure.
6. One Goal may use zero, one, or many Graphs/Runs while retaining its identity and revision history.
7. A Graph is an executable plan/tool. It never becomes the accountable Goal owner and may be used outside user-facing Goal semantics.
8. Lifecycle truth for physical execution is owned by `Run`, `NodeRun`, and `Attempt`. Product state may describe domain progress but may not become a competing universal execution lifecycle.
9. `GraphExecutionState` owns traversal/frontier state only. It cannot independently redefine Run terminality.
10. An `Attempt` maps to one physical `ExecutionRuntime` identity. Retry creates or advances Attempt semantics rather than silently replacing Run identity.
11. Side effects that are part of the governed effect plane carry canonical Capability/Provider/Binding/Invocation identity.
12. Persona affects behavior/taste/purpose only. It never grants authorization or substitutes for Goal/Graph/execution state.
13. Product adapters may translate wire formats, but semantic reconstruction between independently owned models is not an interoperability contract.
14. Historical records remain interpretable after ontology evolution. Breaking semantic changes require a new ontology version and an explicit compatibility/migration rule.
15. M3 Workspace-Agent reconciliation and Design Studio, and later RSI, consume this ontology rather than establish separate Goal, Agent, or execution universes.

## M1 interoperability proof

M1 product convergence is not complete merely because each product can execute independently against pieces of the spine. At minimum, the parity suite owned by #459 must prove that a Builders-created Graph/Run can be listed and interpreted by Conductor using the same canonical identities and semantics, without product-specific semantic reconstruction.

Where a scenario is goal-driven, the observation must preserve the same Workspace, Project, Goal revision, Agent/delegation context, Graph, and Run identity. Schedules, Conductor chat/voice, Evolve, Canvas/Design Studio, and later persistent Workspace-Agent reconciliation must ultimately enter the same canonical object universe rather than introducing product-private Goals or Runs.

## Evolution policy

The machine-readable contract carries a semantic version. Compatible additive changes increment the minor version. Version `1.1.0` adds Agent/Goal identity, Goal revision semantics, and typed Goal relationships to the original v1 contract without changing existing identity fields. Any change that alters an existing concept's identity, owner, lifecycle meaning, or required lineage is breaking and requires a new major version plus the compatibility policy owned by #461.

During M1, #460 prevents new universal owners or side runtimes from being introduced as an implicit way around this ontology. M3 #804/#805/#806 and Design Studio #773/#777 are explicit downstream consumers of the same Goal/Agent semantics.
