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

## Validation round (2026-10-20) — open blockers for the next repair

Re-ran the full acceptance battery on head `46f6d3a06`. The branch's own
tests pass (`tests/security/test_delegation_authority.py` 9 passed,
`tests/a2a/test_broker.py` 13 passed, Hive `test_legacy_dag_node.py` +
`test_security_regression.py` 36 passed; full Hive backend 2354 passed /
4 skipped; `ruff check`/`ruff format --check` clean; `radon-baseline` 72->72;
`wiring-reads` 11->11; `security-inventory` OK; `cross-package-imports` OK).
Two open blockers remain, both actual evidence, not scanner guesses.

### B1 — the graph-node gate blocks every production DAG node under shipped defaults

`LegacyConductorNode._execute` resolves `graph.node.execute` (trusted) /
`graph.node.untrusted` (untrusted) and calls
`Sentinel.resolve_authorized_execution_mode`, which authorizes against the
fail-closed permission table (ADR-072726-0d6b / #1165). The action is
registered in NO permission preset (`permission_policy.py` has only
`dangerous_tools_admin = DANGEROUS_TOOL_NAMES`), in no default config
(`hive-conductor/backend/config.py` ships `maistro_permissions = {}` and
`permission_preset = "none"`), and in no capability slot
(`default_capability_registry()`). The shipped container therefore builds
an empty table, `authorize` misses, and `resolve_authorized_execution_mode`
returns `"blocked"` for every node.

Proof: `packages/hive-conductor/backend/tests/test_legacy_dag_node.py::test_shipped_default_permissions_block_every_gated_node`
asserts `PermissionError` for a role-bearing principal against
`_production_sentinel({})` — the exact shipped wiring. The repair commit
`3caff90f6` fixed the *role* half of the unsatisfiable gate but never
registered the *action*, so under the shipped container the Run dies as
`PhysicalExecutionError` and no configuration surface in the repo states the
grant. This is the ADR's own warned failure mode: "Every missed tool name
is an outage."

Recommended repair (needs the lane owner's posture call, not a unilateral
gate edit): ship a deployment grant for `graph.node.execute` /
`graph.node.untrusted` in the Hive Conductor default `maistro_permissions`
(the lane's own contract — "a deployment's permission grant for the action
is itself the host policy record that makes graph-node execution
reachable"), or document and enforce a mandatory `MAISTRO_PERMISSIONS`
requirement at startup. The fail-closed posture for every other action is
preserved either way.

### B2 — vulture ratchet fails (CI `quality.yml` hard gate)

`check-vulture-baseline.py packages/*/src --min-confidence 60` exits 1.
Branch-caused new debt: `packages/maistro-core/src/maistro/security/_types.py::39`
— `AuthContext.delegation_grant_id` is assigned at
`agents/base.py:1006` but never read in `src` (only the test at
`test_delegation_authority.py:298` reads it). Pre-existing / develop-sync
staleness (branch is 1044 commits behind `develop`): unledgered
`capabilities/invocation.py::127 observed_at` (added by `d7a9a75bf`, an
ancestor of the merge-base, after the ledger's last update `838357134`) and
a stale ledger row `security/trust_boundary.py::grant_id`. Ledger edits are
prohibited in an ordinary implementation PR, so the branch-caused finding
should be fixed (use or remove the field) and the staleness resolved by a
develop sync or a dedicated CI-repair round.

`inventory-delta` for this note is unchanged (+6 core / +2 hive); this
round adds no tests.
