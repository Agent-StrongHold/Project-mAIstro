---
inventory-delta:
  packages/maistro-core/tests: +55
---
# Conditional chat admission compensation (#338)

Partial salvage of #1367 on develop `31d891a561dffd6db1312ea4a85c4835c8048440`.

## Implemented boundary

- A failed admission invocation can compensate RUNNING as well as CREATED/QUEUED
  when its write committed before raising. It never dispatches after that
  failure; HTTP 503 refusal, capacity 429, sanitized `admission_incomplete`,
  and cancellation propagation retain their existing contracts.
- `RunStore.cancel_unstarted_chat_run` atomically compares chat source, status
  and updated_at against the caller's snapshot, checks zero NodeRuns, then
  applies the canonical CANCELLED transition. It makes no death inference.
- Memory performs the decision without an await. PostgreSQL takes the same Run
  row lock as node creation. SQLite reserves `BEGIN IMMEDIATE` before the
  cancellation check, lifecycle writer and node creator's parent reads,
  protecting independent connections as well as calls sharing one store instance.
- Existing recovery pagination, repair limit and five-minute age eligibility
  are unchanged. No server cadence or new admission receipt lease is activated.

## Tests

The existing container suite gains five nodes: QUEUED/RUNNING post-commit
response failure, each with Exception/CancelledError, and the final
read-to-cancel NodeRun race. Two RUNNING cases and the race failed against the
unchanged baseline; the QUEUED cases were existing-behavior controls.

The conformance suite gains 50 nodes: three admission states, idempotent
repetition, changed status/time, foreign source, NodeRun/no-Attempt exclusion,
missing Run, competing cancellers, both independent SQLite/PG transaction
race orders, SQLite reopen, SQL write rollback, and BEGIN-response-loss cleanup
for all three SQLite operations. The extra lifecycle-writer
transaction prevents a stale QUEUED-to-RUNNING write from resurrecting a
cancelled admission; all six added interleaving/rollback cases fail without it.
Another six cases
prove a failed or cancelled queued BEGIN cannot roll back a sibling store
transaction on the shared SQLite connection; cleanup observes the actual BEGIN
outcome before deciding whether it owns a transaction. Twelve nodes require
PostgreSQL. The existing PostgreSQL coverage producer runs the entire runs
suite, so these are on its supported path rather than added as disconnected
proof.

Three existing fault-injection fixtures now intercept the conditional store
operation instead of the retired check-then-transition sequence. Their
assertions still cover newer lifecycle state, terminal-race error handling,
and a disappeared Run allowing a later candidate to progress.

## Explicitly outstanding

This does not close #338. A process dying after NodeRun insertion and before
its first Attempt still needs coordinated canonical admission/dispatch
ownership and a reviewed disposition for historical residue. Age alone does
not prove a slow admitting process died. The proposed CREATED-reservation /
exclusive-launch change under #232/#1151/#544 remains held; this repair neither
implements that proposal nor adds a second lease authority. Server recovery
activation stays with #232/#1621.

## Execution evidence

Focused container and new conformance suite: 85 passed, 12 skipped (no local
PostgreSQL server or MAISTRO_TEST_PG_DSN). Existing server chat gate suite:
37 passed; complete server suite: 493 passed, 9 skipped. Exact repository
package-set mypy: 797 source files clean. Independent review reproduced the
race and cancellation failures and verified their repairs, including repeated
task cancellation while the SQLite worker holds a queued BEGIN.

The broad core run retains 32 outbound/DNS-dependent failures, independently
reproduced on the unchanged base in this cloud environment; no network policy
was bypassed. The environment needed the optional socksio client dependency
to use its configured proxy. No repository dependency or lockfile was changed.
These are source/fault-injection and SQLite transaction/reopen tests, not
process-kill or PostgreSQL execution evidence. Full-suite, independent review
and exact-head CI results are recorded in the PR when available.
