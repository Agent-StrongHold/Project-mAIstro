---
inventory-delta:
  packages/maistro-core/tests: +12
  packages/hive-conductor/backend/tests: +4
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
