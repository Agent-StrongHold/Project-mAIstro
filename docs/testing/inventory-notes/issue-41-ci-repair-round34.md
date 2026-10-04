---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue #41 CI-repair round 34: coverage and admission-boundary revalidation

At `b809690476d60d6b46eedef117a899531f8fd821`, against the assigned merge base
`e067b7b0aca01b578f0bf2446dc0864fc4d88d15`, the supplied driver logs contained
no coverage failure detail (`check-1.log` says only `All checks passed`). This
round therefore re-ran the failing gate's relevant producers instead of making
an ungrounded coverage change.

- The exact five publish-set producers (core, canvas, evolve, RSI, bootstrap)
  ran under branch coverage. `coverage report --fail-under=87` passed at 92%.
- The post-floor maistro-server and Hive producers then passed (499 passed / 8
  skipped and 3328 passed / 6 skipped respectively). Their combined XML passed
  `python scripts/check-diff-coverage.py coverage.xml --base e067b7...`: all
  12 changed measured files met the 90% line and 80% branch floors.
- Focused canonical task/chat coverage passed: 352 passed / 118 skipped across
  the spine, idempotency, durable replay, task HTTP, and chat HTTP suites.
- The CI-scoped vulture exact-debt ledger passed unchanged: 1,342 reviewed
  identities, zero unclassified, zero never-allowlisted.

No test or production source change is justified by this evidence. The parent
is still not closeable: `TaskQueue._admit_claimed` mints the canonical Run at
`packages/maistro-core/src/maistro/tasks/queue.py:741` and only then separately
writes idempotency completion at `:766`. The required joint PostgreSQL
Run/binding commit and real process-kill/multi-replica proof remain #1845's
explicit ownership; this round neither changes the accepted v1 scope domain nor
introduces a parallel admission design.
