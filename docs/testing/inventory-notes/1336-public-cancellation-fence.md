---
inventory-delta:
  packages/maistro-core/tests: +4
---

# Public cancellation fence (#1336)

## Scope

Test-only closeout of the public Runtime boundary. The current `_run_work`
already shields its child await, drains the child on cancellation, and
re-raises the outer cancellation. No additional cancellation flag, execution
lifecycle, production code change or #1335 store-level race repair is included.

Base: `045cfdfbe3eaa0c84493eb02754d7410b0c69378`.
Runtime source blob: `3c5c54ee7422b695bc7e1bbf9fd9dd3e31165736`.

## Four additive cases

`packages/maistro-core/tests/runtime/test_public_cancellation_fence.py` adds:

- Public cancel against an executor that catches cancellation and returns a
  value, both without a deadline and with an unexpired deadline. The call must
  still raise CancelledError, count cancellation exactly once, count no
  completion/failure/timeout, and release its slot and child task.
- A deterministic completed-child/pre-acceptance interleaving. Event-loop
  callbacks schedule the real public cancel before the shield wakes the
  Runtime to accept the value. The test observes that the child is finished
  and the outer execution is still active before calling cancel. It neither
  patches Runtime methods nor fabricates Task state.
- Cancellation after accepted completion must return False and preserve the
  completed result and metrics.

Events and callback ordering are the oracles. The timeout is a deadlock
backstop, not a wall-clock performance assertion. Existing tests are unchanged.

## Local preflight and limits

The exact runtime module was copied into a minimal isolated package and its
Git blob hash verified. On Python 3.13.5 the new pytest file passed all four
cases. Replacing only `await asyncio.shield(work_task)` with `await work_task`
made both swallowing-executor cases fail with `DID NOT RAISE CancelledError`:
2 failed, 2 deselected. Restoring the exact module yielded 4 passed again.
This is a local mutation, not a claim about a specific historical commit.

This module-level preflight does not execute the full repository or prove
Canvas/Attempt-store composition. Repository CI on Python 3.12 remains the
integration authority. Exact CI head and results are recorded on the PR.

Focused repository command:

```text
uv run pytest packages/maistro-core/tests/runtime/test_public_cancellation_fence.py packages/maistro-core/tests/runtime/test_execution.py -q
```
