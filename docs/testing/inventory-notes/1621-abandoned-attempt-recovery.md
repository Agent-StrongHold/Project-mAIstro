---
inventory-delta:
  packages/maistro-core/tests: +7
  packages/maistro-server/tests: +5
---

# 1621 abandoned-Attempt recovery activation

Activates the two dormant halves of the canonical recovery story on the
shipped server process and fences parent completion behind settled children
(#1621, refs #232/#42/#47/#147).

maistro-server (+5): a new process-lifetime cadence ticks
`Container.recover_abandoned_attempts` every 10s — the task worker's
`TaskAttemptExecutor` now constructs its lease with `DEFAULT_TASK_LEASE_TTL`,
so a lease is only written when this process also collects it. Four tests pin
the cadence in isolation (one tick calls the container sweep with the default
limit; a store failure is swallowed and returns 0 so the next tick retries; a
non-awaitable recover is ignored; start is idempotent and stop joins without
further ticks), and the lifespan suite proves `_runtime_lifespan` starts the
sweep with the app container and awaits its stop during shutdown.

maistro-core (+7): `refuse_completion_while_children_open` makes a parent Run's
`COMPLETED` transition refuse while any child Run is non-terminal — failure,
cancellation and timeout stay legal. The spine conformance suite gains the
refusal and the eventual-completion case on every backend (2 tests × 3
backends = +6), and the delegation suite proves a delegate_remote child keeps
its delegating parent un-completable while the child is in flight (+1).
Existing chat-admission, retention and forced-delete cases now settle their
child Runs first, so they exercise deletion/purge of parents whose children
reached a terminal state rather than relying on the previously unguarded
sequence.
