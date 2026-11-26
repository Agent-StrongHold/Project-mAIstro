---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 29: coverage evidence refreshed

No production or test code changed in this CI-repair round. The supplied job
logs all pass; this round independently reran the relevant coverage commands
at `b34fb554265406a3861793e5fd7f45a50ac8af8e` against merge base
`cfb6c3b647145dfcd3ad9b7a1c38f4713d949103`.

The publish-set producer (core, canvas, evolve, RSI, bootstrap) passed its
87% floor at 92%. The widened diff-coverage producer passed server (499 passed,
8 skipped), Turing source (210 passed), Turing backend (90 passed), design
(540 passed, 1 skipped), registry (257 passed), Hive (3,328 passed, 6 skipped),
and root gate tests (4,058 passed, 90 skipped). Its generated report named all
12 measured changed files and `check-diff-coverage.py` passed the 90% line / 80%
branch thresholds. The exact vulture baseline command also passed with 1,342
reviewed identities.

The local PostgreSQL coverage producer could not be recreated from the existing
`auto41-coverage-pg` container because its bridge-only `172.17.0.2:5432` was not
reachable from this WSL worktree; `uv run alembic upgrade head` timed out before
it changed a database. This is not treated as PG proof. The CI-shaped
non-PostgreSQL coverage and diff checks above nevertheless pass on the current
head, so there is no observed coverage regression to repair.

This does not close #41. The admitted task Run is still written before the
separate idempotency completion (`packages/maistro-core/src/maistro/tasks/queue.py:705-768`).
The snapshot assigns joint PostgreSQL Run+binding commit, recovery/process-kill
and multi-replica proof, legacy disposition, and scope owner choices to #1845's
coordinated #1325/#1855 lane; this note neither chooses those options nor adds a
parallel admission authority.
