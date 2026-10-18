---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/hive-conductor/backend/tests: +2
---
# #845 host-authorized delegation and execution tiers

The new core tests prove that a host grant binds the agent, owner, target,
Goal/Run/Invocation, scope, exact artifact, expiry, and provenance; the
resulting effective action set is an intersection rather than a target
manifest grant; approvals cannot be reused for another artifact; and an
agent manifest cannot delegate without a host grant. The Hive adapter tests
prove request `execution_tier` values do not select isolation and
`tier_approved_by` metadata cannot clear a host block.

## Repair round (graph-node gate reachability)

Core (`test_delegation_authority.py`, net +3 tests): the execution-mode
contract is now "an authorized action gets its tier's isolation floor".
`blocked` is reserved for host denial (permission miss or `Tier.BLOCKED`);
authorized-but-uncleared elevation runs at the sandbox floor and only an
explicit `OPEN`/`ROLE_AUTO` host tier record selects inline. New pins: a
permission miss denies even a role-bearing principal; an explicit
`Tier.BLOCKED` tier denies; a stored TTL-bound elevation grant clears
SELF_ELEVATION while staying action-bound and off the inline mode; an
uncleared `DELEGATED` tier never reaches inline.

Hive (`test_legacy_dag_node.py`, +5 tests): `LegacyConductorNode._execute`
is now driven end-to-end against a production-shaped Sentinel (fail-closed
`build_permission_table` + live `CapabilityPermissionSource` over the
default capability registry). Pins: the shipped empty table blocks every
node; a stated `graph.node.execute` permission grant makes the node run at
the sandbox floor; a configured grant cannot authorize a roleless principal
(the unsatisfiable-gate regression this repair fixes — the adapter now
carries host-resolved roles into its Principal); an untrusted node needs an
explicit tier record, not just a permission grant; an explicit
`ROLE_AUTO` record is the only path to inline execution.

Core grant provisioning goes through the documented host-only mutation API
(`InMemoryDelegationAuthority.add_host_grant`), keeping the trust boundary
itself covered by tests rather than constructor backdoors.
