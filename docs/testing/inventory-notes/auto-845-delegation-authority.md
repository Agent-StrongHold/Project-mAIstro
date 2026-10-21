---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +20
---
# #845 host-authorized delegation and execution tiers

The new core tests prove that a host grant binds the agent, owner, target,
Goal/Run/Invocation, scope, exact artifact, expiry, and provenance; the
resulting effective action set is an intersection rather than a target
manifest grant; approvals cannot be reused for another artifact; and an
agent manifest cannot delegate without a host grant. The Hive adapter tests
prove request `execution_tier` values do not select isolation and
`tier_approved_by` metadata cannot clear a host block.

## Repair: wired host policy must keep benign nodes runnable

Validation-round evidence: with the container-composed Sentinel
(`canonical_dag_runner` wires `container.sentinel` into every
`LegacyConductorNode`), `resolve_authorized_execution_mode` flowed the
synthetic `graph.node.*` actions through the fail-closed tool capability
table, which never names them — so every DAG node was denied in the shipped
full-stack wiring, with no configuration surface to recover. The repair:
graph node isolation resolves from host tier records only
(`Sentinel.resolve_authorized_execution_mode` no longer applies the
tool-capability gate to these synthetic actions; the elevation-needs gate is
kept), and `create_container` ships the host record
`("graph.node.execute", "user") -> ROLE_AUTO` (ADR-068 base role). Anonymous
callers and untrusted nodes without an explicit record remain denied, and the
adapter's capability floor still forces the sandbox for dangerous nodes. The
core tests compose the container Sentinel exactly as shipped and prove
benign-runnable / anonymous-blocked / untrusted-blocked; the Hive adapter
tests run `LegacyConductorNode._execute` end-to-end against that Sentinel.

## Repair: the shipped delegation authority must be durable and reachable

Validation-round evidence: `create_container` wired an empty
`InMemoryDelegationAuthority` into Sentinel, so every in-agent delegation
(`Agent._delegate` consults `Sentinel.authorize_delegation` unconditionally)
was refused in the shipped composition unless an operator hand-built a
replacement; `add_host_grant` had no production caller and no restart path.
The repair wires the durable store from the same backend as the elevation
store (`_wire_delegation_authority` -> `build_delegation_authority`: PG ->
SQLite -> in-memory fallback), and `DelegationAuthority.authorize` becomes async
so a durable implementation can read the canonical backend. The decision logic
moves into a shared `decide` helper so the in-memory seam and the durable store
resolve identically. New tests: a SQLite grant authorizes a *new* authority
instance (restart), expired / wrong-principal grants stay hidden, durable and
in-memory authorities decide identically, the PG restart contract and pool
preference, and `create_container` exposes a `DurableDelegationAuthority` that
authorizes the exact subset from a host grant written before the decision.
