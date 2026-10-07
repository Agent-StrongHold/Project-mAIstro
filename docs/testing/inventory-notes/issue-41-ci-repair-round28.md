---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 28: coverage gate reproduced; atomic admission remains external

No source or test changed. The supplied current job logs all pass and identify no
coverage source line to repair; the earlier failed `check-1.log` was instead an
already-resolved merge-conflict syntax error in `pg_store.py`, `sqlite_store.py`,
and `store.py`. A speculative coverage edit would not address either result.

At `33e773351a7d3960d6d84b81ca0f5b91586e586b`, the local CI-shaped
publish-set coverage producer (core, canvas, evolve, RSI, and bootstrap) passed
the exact 87% aggregate floor at **92%**. Appending the full server and Hive
producers passed (`499 passed, 8 skipped` and `3319 passed, 6 skipped`), and
`python scripts/check-diff-coverage.py coverage.xml --base
95553db80303a11c6745069d5246761dc1cb2f47` reported 12 changed measured
production files, all above the 90% line and 80% branch thresholds. The precise
vulture baseline command passed with 1,342 reviewed identities. `ruff check .`
and `ruff format --check .` passed.

Focused production-seam evidence also passed: `175 passed, 5 skipped` across
container chat admission/execution, SQLite completion-write fault recovery, and
both OpenAI-compatible chat endpoint suites. Those tests prove that chat turns
return a resolving Run ID with session/request provenance and a NodeRun/Attempt,
and that the SQLite recreation retry reuses the committed task Run.

This is not a closeout of #41. `TaskQueue._admit_claimed` mints the Run before
its separate `store.complete` write (`packages/maistro-core/src/maistro/tasks/queue.py:705-768`), and
`IDEMPOTENCY_SCOPE_DOMAIN` is still v2 (`packages/maistro-core/src/maistro/tasks/idempotency.py:119`).
The issue snapshot explicitly assigns the joint PostgreSQL Run+binding commit,
unchanged-v1 scope decision, and process-kill/multi-replica evidence to
#1845/#1325; this coverage repair does not select an owner choice or create a
parallel admission authority.
