# Repair notes — #845 round (job 9d1d8b32, branch auto-845 @ 89875a6e0)

## Round 4 (job b178eb75, @ merge-queue evaluation of cff50ff84): the coverage gate is the diff-coverage leg, not the floor or the suites

The merge-queue evaluation failed exactly one check: `Coverage gate
(publish-set floor + diff coverage)`. The job's own log (run 39854170068,
job 120095870394) shows every pytest producer green — server 618, turing 210,
turing-backend 102, design 622, registry 366, ext-harness 273, ext-sdk 147,
hive 3907, root tests 5692 — and the 87% publish-set floor passing (combine
finished 21:21:23). The step died at the final command:
`check-diff-coverage.py coverage.xml --base 774ae42f…` with three files below
the per-file floor:

- `maistro/a2a/broker.py`: 50% of 2 changed lines — the `await` narrowing of
  an async delegation decision inside `delegate()`;
- `maistro/security/sentinel/policy.py`: 75% of 4 changed lines — the same
  narrowing in `Sentinel.authorize_delegation`;
- `maistro/security/sentinel/delegation_durable.py`: 77.8% of 18 changed
  branch arcs — partial at 207/209/212 (the durable authority's non-agent,
  owner-mismatch and expired-row denials) and 233 (naive-expiry row
  normalization).

Root cause: the only tests driving the shipped durable authority called
`await authority.authorize(...)` directly, so the two production consumers —
broker and Sentinel — never executed their async branch in a measured run,
and the durable authority's degenerate denials had no tests at all (the
in-memory twin's denials were tested; the durable copy shipped unproven).
The `RuntimeError: Event loop is closed` lines in the same log are pytest
unraisable-exception warnings during the server producer, which passed
618/618 — they are not the failure.

Repair (test-only; no production or gate edit): seven core tests drive the
durable SQLite authority through the production seams — broker delegation
allowed + refused (2), `Sentinel.authorize_delegation` over a durable
decision (1) — and pin the authority's own fail-closed paths: non-agent
principal refused, owner mismatch refused, expiry re-checked after the store
read (a stale TTL row cannot authorize; a valid row behind it still
answers), and a naive stored expiry read back as UTC (4).
`docs/testing/inventory-notes/auto-845-diff-coverage-async-authority.md`
records the +7 core delta.

Evidence (all at the round's final tree):

- CI's exact gate invocation, rebuilt from CI's own producer commands:
  `coverage xml` then `check-diff-coverage.py coverage.xml --base
  774ae42fc1204acaa651cc0e5a4cca688139ade4` → exit 0, `6 changed file(s)
  measured`, every file ≥90% lines / ≥80% branch arcs (the PG legs of
  `delegation_durable.py` measured against a real pg18 database after
  `alembic upgrade head` through the branch's 067 — chain applies cleanly).
- Publish-set floor: all five coverage-unit producers plus the core suite
  green locally; `coverage report --fail-under=87` → exit 0 (93% on the
  local subset, a lower bound of CI's union).
- Focused suites: `test_delegation_durable.py` + `test_delegation_authority.py`
  + `test_broker.py` → 46 passed, 2 PG-environment skips; full core suite
  16269 passed / 1180 skipped under `coverage run --branch`.
- `ruff check .` clean; `ruff format --check .` clean (3456 files);
  `check-suite-inventory.py` → ok, 21 suites match (core 17456 = 17449 + 7).

## Round 3 (job 736c5d8f, @ merge-queue evaluation of 8b35f5193): CI ledger repair

The merge-queue evaluation failed five jobs. Three were this branch's own
ledger gaps; two were environment-shaped. All fixed or bounded locally:

1. **`delegation_grants` joined the Run purge inventory**
   (`maistro/runs/retention_scope.py`). The table carries a `run_id` column
   (a grant binds the Run whose execution it authorizes), so
   `test_every_run_id_table_is_in_the_purge_inventory` correctly refused it
   as unaccounted-for. Added to `RUN_REFERENCING_TABLES` + docstring row with
   the Preserve policy — authorization provenance, TTL-filtered at read time,
   expiry-sweep owner decision #72 — the same class as `capability_approvals`.
2. **Retired the unread `Container.delegation_authority` field.**
   `check-wiring-reads.py` flags a field no production module reads, and its
   own failure text prescribes the repair: "give the field a reader, or retire
   it" — banking is structurally unavailable to the introducing branch
   (authorizations load from the merge base). The field was a second reference
   to the instance Sentinel already holds, with no production or test consumer
   (every `delegation_authority=` kwarg in the tree constructs a `Sentinel` or
   a user model, never a Container). Removed the field declaration and the
   `Container(...)` kwarg; the canonical authority path is untouched:
   `_wire_delegation_authority` -> `Sentinel(delegation_authority=...)` (the
   one delegated-authority service, per the issue's stop condition). This is
   the ADR-082426-6201 posture: wiring with no reader is the defect
   check-wiring-reads.py exists for (#133 `archive_store`, #225 `a2a_broker`).
3. **Synced the accepted CI obligation inventory**
   (`tests/fixtures/ci_quality_obligations.json`): the branch's one-line
   quality.yml change (running `test_delegation_durable.py` in the
   coverage-postgres producer) changed that job's accepted digest; the
   fixture pins exactly what CI runs, and the established maintenance pattern
   (29fbf8678, bb5f165c2) updates the digest with the legitimate change.
   Recomputed: only `coverage-postgres` drifted.
4. **pip-audit (Supply chain)**: reproduced CI's exact recipe locally
   (`uv sync --locked --all-extras` -> `uv pip freeze --exclude-editable` ->
   `pip-audit --strict --format=json -r` -> `pip_audit_gate.py`): exit 0 —
   the only advisory in the locked set is `ecdsa PYSEC-2026-1325`, triaged in
   ALLOWED. The CI failure's own log shows the registry-outage retry text
   ("produced no usable report after 3 attempts"), an infrastructure
   transient; the gate passes on this tree's dependency set.
5. **Container scan + SBOM + cosign**: the branch's container inputs are
   byte-identical to develop (`git diff 774ae42..HEAD -- Dockerfile*
   packages/hive-conductor/Dockerfile uv.lock .trivyignore.yaml
   quality/image-inventory.json` is empty), so the job's outcome cannot be
   branch-caused. Bounded local reproduction: built `hive-conductor:pr-845-local`
   and `maistro-engine:pr-845-local`, ran CI's identity-contract verification
   inside the image (pass), and Trivy HIGH/CRITICAL `--ignore-unfixed` against
   `.trivyignore.yaml` — both images scan clean (exit 0).

Round-3 evidence (all at the final tree): ruff check/format clean;
`check-wiring-reads.py` with `RATCHET_BASE_REV=origin/develop` exit 0 (11 ->
11 unread); `tests/test_check_wiring_reads.py` + `tests/test_ci_quality_split.py`
132 passed; `test_retention_reference_inventory.py` 13 passed (+ retention
conformance/scope/policy suites 102 passed, 28 PG-env skips); vulture with
ci.yml's exact args exit 0 (1314 identities, no ledger amendment);
pip-audit gate exit 0; durable-table inventory 115 tables ok; suite inventory
21 suites ok (no test added or removed this round, so no inventory-note);
promotion-surface, reachability, security-inventory, workflow-inventory,
ratchet-provenance, backlog-consistency, radon (RATCHET_BASE_REV=origin/develop,
128 -> 128) all exit 0; maistro-core security + a2a 1722 passed / 24 skipped;
container wiring suites 143 passed; hive legacy-DAG + graph-execution-authority
+ graph-runner 87 passed.

## Round 2 (job cd6e7f37, @ 9ecb0fc6e): collision re-repair — delegation grants
renumbered 066 -> 067

The develop sync (merge a9fdec4cb into auto-845) reintroduced the exact
collision 8b8f6a5 had repaired one number earlier: develop's landed
`066_durable_delivery_receipts` (#1060) arrived while this branch still held
`066_delegation_grants`, so two revisions claimed id `066` on `down_revision
065` and `alembic upgrade head` died with two heads. Per the chain convention
the tests narrate (a landed trunk migration never moves; the branch revision
renumbers past it), the salvage rename to 067 was completed:

- `067_delegation_grants.py`: `revision = "067"`, `down_revision = "066"`
  (linear 063 -> 064 -> 065 -> 066 -> 067, single head).
- Head-pinning tests updated with the same narration style:
  `test_capability_invocation_effect_index_migration.py` (heads == ["067"],
  067 parents on 066), `test_goal_installed_base_upgrade.py` (CHAIN_HEAD =
  "067", 067 parents on 066), `test_migration_chain.py` comment (067).
- `quality/durable-table-retention.json`: "created by alembic 067".

Evidence: fresh pg18 DB (maistro-coverage-pg:5433/verify845_migration) —
`alembic heads` -> `067 (head)`; `uv run pytest tests/migrations -q` -> 170
passed (was: FAILED exit 1); delegation/elevation durable PG legs 12 passed
against the migrated DB (067's DDL satisfies the store); delegation authority
+ a2a broker + container wiring 309 passed; execution-tier host-authority
(test_legacy_dag_node.py) green; ruff clean; durable-table and suite
inventories ok; vulture with CI's exact args exit 0 (1314 identities, no
ledger amendment needed).

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
