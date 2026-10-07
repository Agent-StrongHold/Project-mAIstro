---
inventory-delta:
  packages/maistro-core/tests: +51
---
# Conditional chat admission compensation (#338)

Partial salvage of #1367, refreshed on develop
`e1b13dcd15dedd637404c38dfe1900921aba2b8c` for PR #1953.
Refs #338 and #544 for the remaining admission/dispatch ownership work.

## Implemented boundary

- A failed admission invocation can compensate RUNNING as well as CREATED/QUEUED
  when its write committed before raising. It never dispatches after that
  failure; HTTP 503 refusal, capacity 429, sanitized `admission_incomplete`,
  and cancellation propagation retain their existing contracts.
- `RunStore.cancel_unstarted_chat_run` compares chat source, status and updated_at
  against the caller's snapshot, checks zero NodeRuns, and conditionally applies
  the canonical CANCELLED transition. It makes no death inference.
- Memory performs the decision without an await. PostgreSQL takes the same Run
  row lock as node creation. SQLite performs the comparison and NodeRun-absence
  check at the physical SQL UPDATE, using the exact persisted payload bytes.
  SQLite node creation and Run transitions also compare the parent snapshot at
  their physical writes, so a cancellation winner cannot be overwritten by a
  stale insert or QUEUED-to-RUNNING transition. A lifecycle CAS loser raises
  `InvalidLifecycleTransition`, preserving the cancellation service's existing
  winner-reconciliation contract.
- Exact persisted bytes come from the same read as model hydration. Historical
  payloads with omitted defaults or different JSON formatting still work.
- Existing recovery pagination, repair limit and five-minute age eligibility
  are unchanged. No server cadence, new admission lease, migration, quality
  exemption, or canonical dispatch ownership redesign is introduced.

## Current-base review repairs

The originally published SQLite BEGIN/rollback approach was not safe on the
container's shared connection. Independent review reproduced a public
`SqliteConsumerCursorStore.claim` committing between the reads and the final
Run write. A peer RunStore could then win node creation or cancellation while
our stale write still succeeded. The new rollback also erased a sibling cursor
claim on a validation refusal, although that sibling subsequently reported
success. All seven deterministic shared-cursor cases failed on the pre-repair
current-base merge.

The refresh removes that new BEGIN/rollback machinery. Physical-statement
predicates enforce this bounded compensation rule under independent Run-store
connections and real shared-cursor commits. A zero-match statement is committed
before its refusal so it does not leave an implicit write reservation behind.
Pure validation refusals never commit or roll back the sibling's pending write.

This is not a general SQLite shared-connection transaction-isolation repair.
Existing multi-statement cascades and unrelated stores retain their prior
connection conventions. Exclusive transaction coordination or a dedicated
connection would be a separate change; this slice introduces neither.

## Tests and falsification

The existing container suite gains six nodes: QUEUED/RUNNING post-commit
response failure, each with Exception/CancelledError; the final read-to-cancel
NodeRun race; and no retention sweep when compensation loses that race.
Both RUNNING cases and the final NodeRun race fail against current develop;
the two QUEUED cases pass as existing-behavior controls.

The conformance file adds 45 nodes, including 12 PostgreSQL legs. It covers
snapshot/state/source/child eligibility, missing Runs, idempotence, competing
cancellers, both PostgreSQL lock orders, PostgreSQL rollback, eight SQLite
physical-write race cases, three sibling-claim preservation cases, three
historical-payload cases, and cancellation-service reconciliation after a CAS
loss. SQLite checks use real connections and durable reopen. The service test
also fails when the lifecycle CAS exception is mutated to `RunIntegrityError`.

The earlier SQLite transaction/BEGIN tests have been replaced by these
production-composition checks; they no longer support a whole-transaction
ownership claim. The existing PostgreSQL coverage producer runs this entire
file and must freshly execute all 12 PG legs on the published head.

## Explicitly outstanding

Historical NodeRun-without-Attempt disposition, durable admission liveness,
coordinated admission/dispatch ownership, and server recovery activation remain
open. Age alone does not prove a slow admitting process died. The proposed
CREATED-reservation/exclusive-launch decision under #232/#1151/#544 remains
separate. No separate admission receipt lease or competing recovery policy is
introduced. Server recovery activation stays with #232/#1621.

These are source/fault-injection and durable reopen checks, not process-kill
proof. Current-head CI and PostgreSQL execution results are recorded in the PR.
