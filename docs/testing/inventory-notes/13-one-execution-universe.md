---
---

# Issue 13 — one execution universe (develop reconciliation, revalidated 2026-10-20)

The 2026-09-11 closeout commit (c4fa327b) implemented the epic's three
Core-review requirements (#1194 node retry/idempotency, #1193 synth-DAG
mandatory dependencies, #1199 canonical scheduler tick) ahead of develop.
Develop has since landed canonical implementations of the same acceptance that
supersede that branch-local variant:

- #1194 — `ReplaySemantics`/`logical_effect_key` executable replay contract in
  `maistro/graph/durable_runs/{executor,attempt_executor}.py` with
  `test_attempt_executor.py` regression coverage
  (`test_non_retryable_contract_overrides_a_graph_retry_budget`,
  `test_resume_never_reexecutes_a_non_retryable_nodes_ambiguous_effect`).
- #1193 — `agent.synth_dag` without the canonical run store now raises
  `NodeCompositionError` (missing `graph_run_store`/`run_store`) instead of
  returning a success-shaped no-op, plus canonical child admission
  (`_admit_child`) before the first checkpoint.
- #1199 — the configured tick enumerates candidates from
  `ScheduleStore.due()` (`_tick_due`), re-reads canonical truth under
  `definition_lock`, persists cursors through the canonical store, and the
  bounded consumer executes admitted Runs
  (`packages/hive-conductor/backend/tests/test_scheduler_canonical_admission.py`).

The merge into develop (ab8b3737) therefore takes develop's side for every
overlapping hunk and removes the branch-local test variants
(`_UnsafeFlakyStep`, `test_tick_reads_due_schedules_from_canonical_store`);
they duplicated develop's canonical coverage and no longer compiled against
the `ReplaySemantics` contract. This note records that reconciliation so the
ledger does not count tests this branch no longer adds.

## Revalidation on the fad17a87c sync (2026-10-20)

The branch was re-synced to `origin/develop` at fad17a87c (merge 552658ace;
clean, no conflicts — the only branch-local file is this note). The three
requirements were rechecked against reachable production behavior rather than
assuming the earlier note's claims:

- #1194 — `ReplaySemantics` present in `executor.py` (contract field,
  `_may_revisit_after` gate) and `attempt_executor.py` (`_node_replay_semantics`,
  `_replay_refused`); the two regression tests pass.
- #1193 — `NodeCompositionError` raised at `agent_synth_dag.py` composition
  when the durable run store is absent; `test_agent_synth_dag.py` asserts
  `error_code == "NodeCompositionError"` (32 tests pass).
- #1199 — `scheduler.py` canonical tick wired (`_tick_due`,
  `definition_lock`, `schedule_store` cursors);
  `test_scheduler_canonical_admission.py` passes (16 tests).

Focused suites on the synced tree: `graph/durable_runs` 710 passed,
`graph/nodes` 601 passed, conductor scheduling 185 passed, `runs` 1320
passed, `scheduling` 274 passed; `ruff check` and `ruff format --check` clean.

No test count moves on this change, so no `inventory-delta` is recorded. The
epic's remaining open items are owned elsewhere: direct children #41, #42,
#44, #46, #47, #48, open nested items #251 and #1082, sub-issue #1612
(GraphExecutionState load/fork at event sequence N), and #1192 (hierarchy-
owned by M1-E #62). This note intentionally does not close them.

## Revalidation on the e20e9f52 sync (2026-10-20)

The branch was re-synced to `origin/develop` at e20e9f52 (merge 616e513b3;
clean, no conflicts — the only branch-local files are this note and `uv.lock`).
The three requirements were rechecked against reachable production behavior on the
synced tree rather than assuming the earlier note's claims:

- #1194 — `ReplaySemantics` present in `executor.py` (`replay_semantics` field,
  `_may_revisit_after` gate) and `attempt_executor.py` (`_node_replay_semantics`,
  `_replay_refused`); `test_attempt_executor.py` passes.
- #1193 — `NodeCompositionError` raised at `agent_synth_dag.py:484` composition
  when the durable run store is absent; `test_agent_synth_dag.py` passes.
- #1199 — `services/scheduler.py` canonical tick wired (`_tick_due`,
  `definition_lock`, `schedule_store` cursors);
  `test_scheduler_canonical_admission.py` passes (16 tests).

Focused files on the synced tree: `test_attempt_executor.py`,
`test_agent_synth_dag.py`, `test_root_admission_identity.py` (new from develop)
125 passed; `test_scheduler_canonical_admission.py` 16 passed.

Security revalidation (this round's CI gate): `scripts/check-dependency-namespaces.py`
exit 0 ("no unreviewed top-level namespaces"), and `scripts/pip_audit_gate.py`
exit 0 on the frozen `--extra dev` environment with `aiohttp 3.14.5` /
`yarl 1.25.1`; the only advisory is the reviewed `ecdsa PYSEC-2026-1325`
allowlist entry. `ruff check` / `ruff format --check` clean; vulture ratchet
1326/1326 identities match (base e20e9f52).

No test count moves on this change, so no `inventory-delta` is recorded.

## CI-repair round on 9d8d7e96f (2026-10-20)

This round was asked to repair the failing CI gates on this branch. Two
distinct problems were found, and only one of them belongs to this branch.

### Repaired here — `durable-events` (and therefore `integration-scope`)

`integration-scope` requires the `durable-events` check, and that check was the
only failing one in its set. Its failure is a real production defect, not a
scanner artifact: `PgAuditLog.ensure_schema()` only ever *altered* `audit_log`,
while `container.py:_wire_audit_log` has called it unconditionally on a
PostgreSQL pool since #2198 (`d32ddff76`). A container wired against a
database that has not run the migration chain therefore died on startup with
`relation "audit_log" does not exist` — all five PostgreSQL legs of
`packages/maistro-core/tests/events` failed.

The repair, the regression tests and the evidence are recorded in
[`13-audit-log-schema-bootstrap.md`](13-audit-log-schema-bootstrap.md).

### Not repaired here — the reachability floor (owner-held, two merges)

`exact-debt-ledger`, `Quality / Reachability`, the root `test` job, the
aggregating `Quality gate (Pillars 1–4, 7, 8)` and `Coverage gate` all fail
for one reason, and it is a develop-level omission rather than anything this
branch changed:

- `packages/maistro-core/src/maistro/runs/admission_identity.py` (520 lines)
  reached `develop` through PR #1936 (`auto-1851`) with no importer, and
  `quality/reachability-baseline.json` was never extended for it. It is
  documented as an "inactive contract leaf": a later, separately reviewed
  integration lands its runtime consumer.
- `uv run python scripts/check-reachability.py` → 1417 modules, 169
  unreachable, the one new one being `maistro.runs.admission_identity`.
- `uv run python scripts/check-reachability-provenance.py` → the module is
  absent from the trusted base (`e20e9f52ea94`) and no prior
  reachability authorization covers it.

The gate cannot be satisfied from this branch: `ratchet_provenance.
load_authorizations` reads `quality/ratchet-authorizations.json` **from the
merge base**, so a grant that lands in this same change cannot authorize
itself ("Authorizing a floor-raise is now two merges -- the grant, then the
regression it permits", `scripts/ratchet_provenance.py:616`). Banking the
module in this branch's baseline without a landed grant is exactly the
"banking is not authorizing" case, and it would leave the candidate ledger
carrying an unauthorized floor raise. The alternatives — a fake caller, a
keep-alive import, a suppression, a rename, or a baseline/allowlist/grants
edit in this PR — are all excluded by the lane's own constraints and by
`.cursor/context/repair-1851-9ddea59d.md`.

The owner-held sequence is therefore: land a reachability authorization for
`maistro.runs.admission_identity` on `develop`, then land the baseline row
(with its disposition group and its `docs/architecture/CONVERGENCE-MATRIX.md`
row) in the change that needs it. This branch keeps the tree free of a
self-approved floor raise and records the blocker instead.

### Round evidence

- `uv run pytest packages/maistro-core/tests/events` with
  `MAISTRO_TEST_DATABASE_URL` pointing at an unmigrated PostgreSQL 17 and
  `MAISTRO_REQUIRE_PG_LEGS=1` → `385 passed` (5 failed before the repair).
- `uv run pytest tests/ --ignore=tests/tools/registry -q --timeout=60
  -p no:randomly` → `3 failed, 5393 passed, 138 skipped`; the three failures
  are the reachability-baseline self-checks
  (`tests/test_check_reachability.py`, `tests/test_reachability_baseline_identity.py`)
  and all three name `maistro.runs.admission_identity`.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → 1326 identities /
  1326 findings, exit 0.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.

This round adds three tests to `packages/maistro-core/tests`; the delta is
recorded in [`13-audit-log-schema-bootstrap.md`](13-audit-log-schema-bootstrap.md),
not here, so this note keeps describing the reconciliation it was written for.

## Second CI-repair round at `e5767cd3b` (2026-10-20, job `5939f970`)

`exact-debt-ledger` was re-run, not assumed. It still fails at its first step
(`check-ratchet-provenance.py`, the reachability ratchet on develop's
`maistro.runs.admission_identity`); its vulture and shipped-surface steps are
green, so the lane's vulture-ledger remedy has nothing to amend. Full
re-derivation, including the base-worktree measurement:
[`../13-repair-20261020-exact-debt-ledger-inherited.md`](../13-repair-20261020-exact-debt-ledger-inherited.md).

The repair that *was* available belongs to the branch's own production change:
the `audit_log` bootstrap created the table without the indexes the migration
chain (005, 062) and the SQLite sibling give it, which left every cursor-page
and filtered audit read unindexed on a bootstrapped database. Fixed and proved
on a real PostgreSQL 17 in
[`13-audit-log-schema-bootstrap.md`](13-audit-log-schema-bootstrap.md#second-repair-round--the-bootstraps-index-shape-2026-10-20-job-5939f970).
No node IDs were added, so no `inventory-delta` is recorded for this round.

## Third CI-repair round at `6808fca72` (2026-10-20)

The two attempts immediately before this one (`dd7f252b`, `c9102f21`) died to
provider rate limits after their checks had already passed; no new evidence was
produced. This round re-executed everything first-hand at `6808fca72` instead
of inheriting any prior claim:

### The named gate, all three steps at CI's exact argv

- `check-ratchet-provenance.py` → **rc=1**, sole finding unchanged:
  `maistro.runs.admission_identity` NEW unreachable / missing from candidate
  baseline, then `ratchet provenance inventory is incomplete` off that one
  failure. Every other ratchet in the inventory is green
  (adr-status-language, citation-status, promotion-surface 272/74,
  reachability-dispositions 168→168, shell-execution 3→3, contract-markers
  358→358, enumerations 1→1, lifecycle 0→0).
- `check-shipped-surface-truth.py` → **rc=0**.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → **rc=0**, 1326 reviewed identities → 1326 findings,
  `unclassified: 0`, `never_allowlist: 0`. The lane brief's vulture-ledger
  remedy still has nothing to amend.

### The inheritance, proven from the base tree again

`~/Git/worktrees/base-e20e` is a clean worktree at the assigned base
`e20e9f52ea94`; its `check-reachability.py` reports **1417 production
modules, 169 unreachable, 1 NEWLY UNREACHABLE:
`maistro.runs.admission_identity`**, rc=1. The module exists at the base
(landed for #1851 by `c8c8adbff`/`9efe89caa`, docstring: *inactive contract
leaf*), and is absent from the base `quality/reachability-baseline.json` and
base `quality/ratchet-authorizations.json`; this branch still carries zero
`quality/` diffs vs `origin/develop` (`git diff --numstat origin/develop HEAD
-- quality/` empty). `origin/develop` has not moved off the base, so the
two-merge sequence (grant on develop, then the baseline row) remains unstarted
and unstartable from here — `scripts/ratchet_provenance.py:600-625` states the
two-merge rule and `scripts/check-reachability-provenance.py:80` reads grants
from `trusted_ref.base_sha`.

The root `test` job's three failures were reproduced
(`tests/test_reachability_baseline_identity.py`, `tests/test_check_reachability.py`:
3 failed / 36 passed, `::error title=New unreachable
modules::maistro.runs.admission_identity`), and the `Coverage gate` inheritance
is now pinned to its mechanism: its producer runs `pytest tests/`
(`.github/workflows/quality.yml:714`), so it fails on the same three tests
before any floor or diff-coverage evaluation.

### The branch's own repair, proved on real PostgreSQL both ways

- **Bootstrapped path** — fresh database on the `auto-13-pg17` container that
  never ran migrations, `MAISTRO_TEST_DATABASE_URL` +
  `MAISTRO_REQUIRE_PG_LEGS=1`: `pytest packages/maistro-core/tests/events -q`
  → **385 passed**, including the two audit tests and their `pg_indexes`
  assertions (pkey, scope, timestamp, user, agent, all `AUDIT_PAGE_INDEXES`).
- **Migrated path** — fresh `pgvector/pgvector:pg18` database,
  `alembic upgrade head` → head `063`, then `MAISTRO_TEST_PG_DSN`:
  `pytest packages/maistro-core/tests/persistence/test_pg_audit.py
  packages/maistro-core/tests/test_container_wiring.py -q` → **66 passed**
  (org_id nullable per the chain, `ix_audit_log_scope` on `(org_id,
  "timestamp")`, two-org scope predicate).
- **Before/after on one fresh database** — the base tree's `ensure_schema`
  (`~/Git/worktrees/base-e20e` module loaded directly) raises
  `asyncpg.exceptions.UndefinedTableError: relation "audit_log" does not
  exist`; the branch's `ensure_schema` then creates the table (15 columns)
  with all 13 indexes. The regression the new tests name is real, not a
  fixture artifact.

### Epic acceptance re-verified at this head

- #1194 — `ReplaySemantics` executable contract at
  `graph/durable_runs/executor.py:80` and `attempt_executor.py:389,692`; the
  two named regressions run (`test_attempt_executor.py`: 448, 619) — **14
  passed**.
- #1193 — `NodeCompositionError(missing=("graph_run_store", "run_store"))` at
  `graph/nodes/agent_synth_dag.py:484` — `test_agent_synth_dag.py` **32
  passed**.
- #1199 — canonical tick `_tick_due` at
  `hive-conductor/backend/services/scheduler.py:443`, enumerating
  `container.schedule_store.due(now=now)` at :457 —
  `test_scheduler_canonical_admission.py` **16 passed**.

No test counts move in this round, so no `inventory-delta` is recorded. The
blocker and the owner-held unblock sequence are unchanged from the previous
round and recorded in
[`../13-repair-20261020-exact-debt-ledger-inherited.md`](../13-repair-20261020-exact-debt-ledger-inherited.md).
