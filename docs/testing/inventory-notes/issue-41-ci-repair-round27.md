---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 27: coverage reproduced; admission residual remains

The supplied job log does not identify a source-level coverage failure:
`/home/dev/maistro/jobs/49ae21f8fc294d039514dc3de6e1cf2b/check-1.log` says
`All checks passed!`. No speculative production or test edit was made.

At `00e0b6e09d7b781fefe38d824e3ec318fea1fbdd`, the CI-shaped non-service
publish-set producer passed at the exact 87% floor (91%). Its component suites
reported: core `11747 passed, 785 skipped, 1 xfailed`; canvas `464 passed, 75
skipped`; evolve `987 passed, 6 skipped`; RSI `867 passed`; and bootstrap `237
passed, 1 skipped`. The post-floor maistro-server and Hive producers passed
(`499 passed, 8 skipped` and `3311 passed, 6 skipped`). The resulting
`coverage.xml`, checked against the assigned base
`c0441cf94b9a8e58517da0f4159070b97ea6a706`, measured 12 changed production
files and passed the per-file 90% line / 80% branch gate.

The exact vulture baseline command passed with 1,345 reviewed identities and
no unbanked findings. A real PostgreSQL 17 service on the local Docker socket
was migrated to `head`; `test_idempotency_durable.py` then passed all 28 tests.

This does not make #41 merge-ready. `TaskQueue._admit_claimed` creates the Run
before its separate `store.complete` call (`queue.py:705-768`), while
`PgRunStore.create_run` and `PgTaskIdempotencyStore.complete` acquire their
own PostgreSQL transaction scopes (`pg_store.py:255-259` and
`idempotency.py:1238`). Consequently the required joint durable Run+binding
commit and process-kill/multi-replica recovery evidence remain unproven. In
addition, `idempotency.py:119` still declares the v2 scope domain, contrary to
the reviewed residual's unchanged-v1 direction. Per the issue snapshot,
#1845/#1325 own that atomicity and migration decision; this coverage lane does
not select an owner choice or introduce a competing admission path.
