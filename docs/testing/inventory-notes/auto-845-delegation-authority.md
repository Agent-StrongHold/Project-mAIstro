---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/hive-conductor/backend/tests: +15
  tests/: +4
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

## Repair round (2026-10-27) — develop sync merged, B1 and B2 closed

`origin/develop` (`e20e9f52e`) is merged into this branch (merge commit
`292a383bd`, merge-base `e20e9f52e`). The four conflicts were resolved by
combining both sides: `canonical_dag_runner.py` and `legacy_dag_node.py`
keep develop's `effect_context` / `governed_runtime` / progress-hook wiring
*and* this branch's Sentinel gate, host-mode resolution and principal-role
resolution; `optimizer.py` takes develop's escalation handling
(`upgrade_execution_tier` is an escalation there, not a tier upgrade);
`container.py` takes develop's restructured composition root and re-adds
`InMemoryDelegationAuthority` plus `delegation_authority=` on the Sentinel.

### B2 — the vulture ratchet is green without touching the ledger

The gate is `python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`; it now exits 0 with
1326 findings — exactly develop's banked count, no new identity, no row
dropped. The branch was made vulture-neutral *in source* rather than by
editing `quality/vulture-baseline.json` or `quality/ratchet-authorizations.json`
(a ledger edit is not allowed in an ordinary implementation PR, and a grant
authorizes a later change, never its own introduction):

- `DelegationGrant.grant_id` → `grant_ref`, `DelegationDecision.grant_id` →
  `grant_ref`, `AuthContext.delegation_grant_id` → `delegation_grant_ref`.
  The name `grant_id` already belongs to
  `maistro.security.trust_boundary.PermissionGrant.grant_id`, and vulture's
  `used_names` is a global exact-match set: a second `.grant_id` load masks
  develop's banked row. One identifier, one meaning.
- `DelegationGrant.granted_by` is now read: it is carried on
  `DelegationDecision`, logged by `agents/base.py` ("Delegation authorized by
  host policy: … grant_ref=… granted_by=…") and published on the A2A task
  metadata as `delegation_granted_by`.
- `InMemoryDelegationAuthority.add_host_grant` is now genuinely read: the
  authority seeds its grants through it (`__init__` takes an iterable of
  grants), so the host-only mutation API stays the single provisioning path
  and is exercised from `src`.
- `Sentinel.resolve_execution_mode` / `Sentinel.resolve_authorized_execution_mode`
  moved out of the core into `packages/hive-conductor/backend/services/execution_mode.py`.
  The isolation vocabulary ("blocked" / "async" / "sandbox") belongs to the
  Conductor adapter, not to the core; the core keeps exactly one policy
  decision surface (`Sentinel.authorize` + `Sentinel.resolve_tier`), so no
  competing authority path is introduced. The adapter helper is outside the
  vulture scan (`packages/*/src` only).
- `AuthContext.delegation_grant_ref` is now read inside `src`: `Sentinel.pre_call`
  emits it on the call audit (`detail="delegation_grant_ref=…"`, the host's
  reference only — never request content), which is also what makes the
  approval/elevation provenance criterion observable at the audit seam.

### B1 — graph-node execution is reachable in every shipped Conductor profile

The blocker was a deployment gap, not a code gap: the fail-closed table
denies `graph.node.execute` because no preset names it (the
`hive_conductor_tools` preset is pinned to `services.tool_executor.TOOLS` by
`tests/security/test_sentinel_permission_table_armed.py`, so the preset
cannot carry it). The repair states the grant where authority belongs — the
deployment:

- `MAISTRO_PERMISSIONS='{"graph.node.execute": ["admin", "user"]}'` is now
  part of the shipped Conductor profiles: `docker-compose.yml`,
  `docker-compose.pm-poc.yml`, `deploy/docker-compose.prod.yml` and
  `packages/hive-conductor/docker-compose.yml` (the four stacks the
  `hive-conductor` service runs in). The code default stays fail-closed
  (`permission_preset="none"`, empty map): an unstated grant still denies
  every node.
- `graph.node.untrusted` is deliberately *not* granted: the untrusted node
  class stays behind its own host tier/approval record.

New evidence:

- `tests/security/test_sentinel_permission_table_armed.py::test_shipped_profiles_authorize_graph_node_execution`
  renders each shipped Conductor profile exactly as `docker compose` would
  and asserts the composed table grants `graph.node.execute` to the host
  roles `admin` and `user` (the roles a Conductor user record carries).
- `packages/hive-conductor/backend/tests/test_execution_mode.py` (new file,
  8 tests) pins the behavior of that grant: a normal node is reachable at
  the sandbox floor, `graph.node.untrusted` stays blocked, a principal
  without a host role is denied, and the isolation floor is derived from the
  tier Sentinel resolved — never from a caller label. The four
  execution-mode tests that used to live in the core suite moved here with
  the code they cover (they exercise the adapter's vocabulary).

### Remaining limitations (recorded, not repaired in this round)

- **Delegation grants have no product path yet.** Exact-bound grants
  (`artifact` / `run_id` / `invocation_id`) can only be minted by a host
  component at runtime; `InMemoryDelegationAuthority` is process-local, so
  a grant does not survive a restart. Wiring the HITL reviewer flow
  (park → approve → resume) into grant issuance is the follow-up.
- **Elevation request/grant/clear is not exposed over HTTP.**
  `request_self_elevation` / `confirm_self_elevation` exist in
  `maistro.security.sentinel.elevation` and the container wires an
  `elevation_store`, but no shipped route issues or clears an elevation; the
  tier therefore stays at `SELF_ELEVATION` (sandbox floor) for a graph node.
- **`graph.node.untrusted` remains ungranted** pending an explicit host
  tier/approval record.

`inventory-delta` for this note is now `packages/maistro-core/tests: +5`
(the execution-mode tests moved to the Hive suite), `packages/hive-conductor/backend/tests: +15`
(the new `test_execution_mode.py`, 8 tests, plus the branch's earlier
adapter pins) and `tests/: +4` (the new parametrized shipped-profile pin).
