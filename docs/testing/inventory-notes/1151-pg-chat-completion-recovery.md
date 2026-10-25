---
inventory-delta:
  packages/maistro-core/tests: +2
---
# #1151 PostgreSQL chat completion recording recovery

Adds `test_chat_completion_write_failure_recovers_from_committed_truth` in
`packages/maistro-core/tests/runs/test_pg_spine_crash_windows.py`, parameterized
as `rejected-write` and `lost-ack`.

Both drive the production `ChatAttemptExecutor` / `RunExecutionService` with a
counted provider callback and default finite canonical lease. The failure is
injected before the physical COMPLETED write or after the real PgRunStore write
commits. An independent PostgreSQL pool reads canonical Run/NodeRun/Attempt
facts, then the public Container recovery tick reconciles those facts.

Oracles:

- The adapter raises `ChatDispatchUnrecorded` with the original answer and the
  exact recording exception; one dispatch and one completion-write attempt.
- Before-commit failure leaves physical/logical RUNNING, refuses recovery while
  the persisted lease is live, then reclaims and parks at expiry without
  fabricating output or accepted success.
- After-commit acknowledgement failure leaves persisted COMPLETED evidence;
  recovery accepts that exact evidence and completes the logical records without
  rewriting the physical history, redispatching, or creating an Invocation.
- Repeated recovery is a complete persisted fixed point. Both legs preserve
  Attempt identity, ordinal and lease/fence; no Graph continuation is fabricated.

Existing fixtures use real PgRunStore instances on independent pools. These are
injected storage-boundary failures, not OS-process death or a network-level
uncertain COMMIT response. They exercise the chat adapter, not HTTP routing or
transcript persistence. The provider is stubbed; database writes and recovery
are real. PostgreSQL legs skip only when no test DSN is configured. This proof
does not resolve the parked Graph disposition or total scan-work policy blocks.

Execution and differential results are recorded in
`docs/testing/1151-repair-010688bc.md`.
