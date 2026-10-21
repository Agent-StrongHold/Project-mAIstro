# Repair notes — #845 round (job 9d1d8b32, branch auto-845 @ 89875a6e0)

Continuation of the rate-limit-killed prior attempt; its uncommitted work was
preserved as `incoming-845.patch` (backup at `/home/dev/Git/wt/incoming-845.patch`)
and completed rather than restarted.

## What this round changed

1. **Host-resolved principal roles land.** `canonical_dag_runner` resolves the
   node principal's roles server-side from the user store
   (`_host_principal_roles`), threaded through `_resolver` into
   `LegacyConductorNode`; the adapter prefers them over the ADR-068 base-role
   fallback. Roles never come from a request field; an unknown/unreadable user
   resolves to no roles and the fail-closed tier gate denies.
2. **Debug instrumentation removed.** The prior attempt had left stderr/stdout
   `print` probes in `dag_agents.py`, `legacy_dag_node.py` and
   `test_dag_execution_transport_parity.py`; all removed. Salvage scratch test
   `test_dbg.py` (zero assertions) preserved at
   `/home/dev/Git/wt/salvage-845/test_dbg.py`, not committed.
3. **Nine core tests** in `tests/security/test_delegation_authority.py` close
   the degenerate delegation paths (no grant id, naive expiry, no provenance,
   human principal, foreign owner, expired grant, sentinel without authority)
   and pin execution-mode floors (BLOCKED tier -> blocked; non-OPEN tier ->
   sandbox). Delta recorded in
   `docs/testing/inventory-notes/auto-845-0cbc.md` (+9 maistro-core).
4. **CI producer for the durable delegation suite**: `test_delegation_durable.py`
   joins the under-coverage PG-schema job in `quality.yml` (same rule that put
   PgElevationStore there); `delegation_grants` joins the core conftest PG
   scratch-table sweep.
5. **`delegation_grants` registered in `quality/durable-table-retention.json`.**
   The committed `delegation_durable.py` creates the table on both backends but
   no retention row existed, so `check-durable-table-inventory.py` failed. The
   entry mirrors `elevation_grants` (security_evidence, retention undecided,
   expiry-sweep owner decision #72). This is the completeness declaration the
   gate requires for a new durable table — no ratchet/grant mechanics involved.
6. **Alembic migration 064 creates `delegation_grants` on PostgreSQL.** The
   runtime store's `ensure_delegation_schema` docstring already claimed
   "managed deployments also apply the Alembic revision", but no revision
   existed; the committed `pg_pool` fixture (and CI's coverage PostgreSQL
   producer) truncates a *migrated* database, so the runtime-only table broke
   every PG-leg suite at setup with `UndefinedTableError`. 064 carries the
   guarded DDL byte-identical to `POSTGRES_DELEGATION_SCHEMA` on parent 063
   (single head verified). Verified against a real pgvector:pg18 server:
   chain downgrade base -> upgrade head walks clean, `tests/migrations/`
   23 passed (chain test's `EXPECTED_TABLES` updated with #845's table),
   `test_delegation_durable.py` 6/6 including the PG restart contract, and
   the persistence + schema-parity suites 838 passed.

## Gate evidence (all run at the final tree)

- `ruff check .` / `ruff format --check .` — clean (only the uncommitted
  scratch file ever flagged; removed from the tree).
- `check-radon-baseline.py` with `RATCHET_BASE_REV=origin/develop` — exit 0,
  134 -> 134 C-or-worse blocks, 0 new/regressed (the earlier `_matches -> C (11)`
  finding was repaired in commit 6c4b9e2f0 by extracting `grant_matches`).
- `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0, 1326 reviewed identities.
- `check-suite-inventory.py` — ok, 21 suites match.
- `check-durable-table-inventory.py` — ok, 113 tables.
- `check-branch-independence`, `check-promotion-surface`,
  `check-reachability`, `check-security-inventory`,
  `check-workflow-inventory`, `check-ratchet-provenance`,
  `check-backlog-consistency` — all exit 0.
- Tests: maistro-core security + a2a + container wiring 1745 passed / 24
  skipped; hive legacy-DAG/graph-runner/authority/quota/cancel suites 99
  passed; against a real PostgreSQL (pgvector:pg18, migrated):
  delegation-durable + elevation-durable 12 passed, persistence +
  sqlite/alembic parity 838 passed, migration chain + head + revision
  metadata 23 passed.

## Known environment failure (not a regression; pre-existing on develop here)

`test_dag_execution_transport_parity.py` — 3 of 13 tests fail on this
workstation with `RuntimeError: bwrap: execvp
/home/dev/Git/wt/auto-845/.venv/bin/python: No such file or directory`.

Chain: the parity spine wires a sentinel-less container, so nodes classify to
the sandbox floor (identical on origin/develop, whose
`_host_execution_authority` yields `(None, None)` for the same spine) ->
`_run_node_subprocess` -> bubblewrap. `_RO_BINDS` in
`maistro/sandbox/backends/bubblewrap.py` covers only `/usr /bin /sbin /lib
/lib64 /etc/alternatives`; this machine's uv-managed venv python is a symlink
into `/home/dev/.local/share/uv/...`, invisible inside the bwrap mount
namespace, so the interpreter exec fails. The sandbox execution files are
byte-identical to develop (`git diff origin/develop HEAD -- hyperlight_executor.py
maistro/sandbox/` is empty), so this reproduces on develop at this machine and
is not introduced by this branch. Repairing it would require widening the
sandbox's bind surface (a security posture change, out of lane) or an
environment change (non-symlinked interpreter on a bound path).

## Acceptance summary (issue #845)

- Delegation consumes host grants only; manifests/config cannot grant
  (`test_agent_manifest_cannot_delegate_without_host_grant`, shared `decide()`
  binding principal/owner/target/goal/run/invocation/scope/action/artifact/
  expiry/provenance).
- Effective envelope is the intersection, never the advertised set
  (`test_host_grant_returns_only_the_explicit_action_subset`,
  `test_broker_host_authority_grant_carries_effective_subset`).
- Approval cannot be reused across actions/artifacts
  (`test_an_approval_for_another_artifact_cannot_be_reused`).
- Execution tiers resolve from host records; request `execution_tier` and
  `tier_approved_by` are metadata
  (`test_execution_mode_requires_a_cleared_host_tier`,
  `test_request_tiers_do_not_select_inline_execution`,
  `test_request_metadata_cannot_approve_an_untrusted_node`,
  `test_request_approval_string_cannot_clear_host_block`,
  `test_resolve_execution_mode_*`).
- Host grants survive restart (SQLite/PG durable authority
  `test_sqlite_delegation_grant_survives_a_new_authority_instance`,
  `test_postgres_delegation_grant_survives_a_new_authority` — PG legs run in
  the CI producer job; locally env-skipped without MAISTRO_TEST_PG_DSN).
