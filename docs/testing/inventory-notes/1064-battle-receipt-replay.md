---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
---
# #1064: losing battle replicas consume committed receipts

Adds 15 collected cases in `test_evolution_restart_replay.py`: three
backends (memory, SQLite, PostgreSQL) times one committed-score/provenance
replay case and four incompatible-identity cases (Run/pair mismatch, with
and without the battle already mirrored locally).

The replay case deliberately reverses the losing worker's scores with the
same frozen membership, and requires its complete tournament signature,
including Elo/counters and publishing Attempt, to match the winner. Replaying
twice must leave exactly one unchanged durable receipt. The incompatible
cases require explicit recovery refusal with no local or durable mutation.
PostgreSQL cases skip only when `MAISTRO_TEST_PG_DSN` is absent.

This is focused evidence for the production battle conflict path, not proof
of complete killed-process Run recovery or finalize/paid-effect fencing.
Canonical Run/NodeRun/Attempt remain execution authority (ADR-081226-69ee,
ADR-081626-f383); the domain receipt only reconstructs an already published
effect. No lease, scheduler, Goal store, or authorization path is added.

## Executed validation

- Before the production fix, the new cases failed on memory and SQLite:
  10 failed, 5 PostgreSQL cases skipped without a DSN. Failures showed both
  differing Elo/Attempt provenance and missing incompatible-identity refusal.
- With the fix and the assigned migrated PostgreSQL 18 service: replay,
  PostgreSQL replay, domain-store and retention suites: **32 passed**,
  including all 15 new cases.
- Full Hive backend: **4383 passed, 56 skipped** (no PostgreSQL DSN in that
  invocation); Evolve package: **1005 passed, 12 skipped**; core Run suite:
  **1661 passed, 404 skipped**. The core suite emitted six existing-style
  aiosqlite worker/event-loop shutdown warnings; Hive emitted serializer and
  cookie deprecation warnings. Neither suite failed.
- Strict `evolve_required_scenario` / `evolve_has_canonical` parity selection:
  **2 passed**, with `evolve-cycle-to-conductor` reporting executed/PASSED
  through the durable SQLite scenario.
- Root Ruff lint/format, scoped suite inventory (**4439 collected**), durable
  table inventory, cross-package imports, execution-lifecycle gate, and the
  exact CI Vulture scan passed. Vulture found **1221 reviewed identities**;
  no ledger change was warranted. Initial Ruff failures in the new test
  (regex literal and formatting) were corrected before these final checks.

## Remaining issue-level evidence gaps

This focused repair is **not #1064 closure evidence**. The existing restart
suites raise `_ProcessKilled(BaseException)` in the same interpreter and
reopen pools; their passing results do not establish a killed OS process
resuming the full Run. The seeds are pre-evaluated, so durable evaluation
publication/recovery is not proven. A faulted/in-progress finalize marker
still requires reconciliation rather than transparent resume (the existing
faulted-finalize test explicitly proves refusal). Exhaustive cull/breed/
migrate/self-improve boundary equivalence, immutable lineage equivalence,
and stale canonical-fence/paid-effect exclusion remain unverified. The
finalize read-then-upsert path has not been proven safe against competing
recoverers. Missing-prerequisite permanently-QUEUED behavior also remains
unverified. No claim is made about remote exact-head CI, persistence-design
approval, or #947 review disposition; no remote mutations were performed.

## Follow-up verification at `10c7c6122bdf`

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -x -q` -> **16 passed, 10 skipped**. The PostgreSQL legs skipped because this run had no `MAISTRO_TEST_PG_DSN`; this does not satisfy the real-PostgreSQL acceptance criteria.
- `uv run ruff check . && uv run ruff format --check .` -> passed.
- CI-exact Vulture scan (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) -> 1221 reviewed identities, no unbanked identities.
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f` -> **failed**: design coverage 39.7781% below the base floor 44.4608%. This is not authorized to be banked in this repair, so remains a blocking acceptance failure.

The tests still do not launch a new OS process for resumed Run-level recovery or
exercise each finalize mutation boundary; these remain unresolved and are not
promoted to acceptance evidence by the passing same-process suite.

## Independent verification at `acaad60dab3b`

- Scoped Evolve restart/store suites: **40 passed, 13 skipped**. The skipped
  PostgreSQL legs require `MAISTRO_TEST_PG_DSN`; it is unset in this run.
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- CI-exact acceptance-state ratchet with mandate `88ca7a1ccb5c`: **failed**;
  design coverage is `39.7781%`, below the base floor `44.4608%`. This repair
  cannot authorize or bank that fall.
- The unresolved close-only gaps remain: no distinct-OS-process Run recovery
  test, no production-harness parity proof, incomplete finalize-boundary
  coverage, and no verified real-PostgreSQL run. The accepted canonical
  execution/recovery ADRs require the Run/NodeRun/Attempt + Graph-continuation
  authority to remain canonical; Evolve persistence must remain domain evidence,
  not a parallel execution lifecycle.
