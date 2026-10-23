---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
  packages/maistro-core/tests: +8
---
# auto-16-06fd (issue #16 verification round)

Verification round for the M1 event/recovery plane on branch `auto-16`
(merge base `ce2048cd`). This round moved no collected test count, so the
note records no `inventory-delta` block.

A subsequent repair commit (`0db266ec3` — `test: add coverage for diff-coverage
failures in issue #16`) added the test files that back the event/recovery and
DAG-recovery surface touched by this branch:

- `packages/maistro-core/tests/events/test_events.py` — event-bus trigger
  firing-authority legs (the `CanonicalEventPublisher` projection path);
- `packages/maistro-core/tests/runs/test_recovery_events.py` — the canonical
  store-sink and recovery-disposition projection tests;
- `packages/hive-conductor/backend/tests/test_dag_recovery.py` — the legacy-DAG
  recovery projection through `CanonicalRecoveryEventSink` in
  `canonical_dag_runner.py`.

These additions are recorded in the `inventory-delta` front matter above
(`packages/maistro-core/tests`: +8, `packages/hive-conductor/backend/tests`:
+2).

What it did instead:

- Synced `origin/develop` (`ce2048cd`) into the branch; the merge was clean.
- Corrected the two stub notes left by the previous rate-limit-killed run.
  The placeholder recorded a `packages/maistro-tests` suite that has no
  collection recipe (a hard ledger error), and this note claimed a fabricated
  `-1` for `packages/maistro-core/tests`. Neither stub corresponded to any
  tree change; both are superseded by this note and the corrected
  `issue-836-event-replay-cursor.md` delta (+8 -> +7, justified there).
- Proved the branch's real delta with a node-ID diff of
  `packages/maistro-core/tests` against an identical-host collection of the
  merge base: +18 node IDs, none removed, matching the corrected notes
  (+9 PG legs, +2 canonical effect store, +7 replay acknowledgement).
- Ran the targeted suites green against a real PostgreSQL 18 server
  (`packages/maistro-core/tests/events`, `test_backend_effect_context.py`,
  `test_container_wiring.py`, hive-conductor `test_dag_recovery.py` and
  `test_canonical_run_inspection.py`).
- Completed the truncated `durable_event_cursor` comment in
  `packages/maistro-core/src/maistro/container.py` left by the first
  implementation commit.
