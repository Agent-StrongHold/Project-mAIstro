---
inventory-delta:
  packages/maistro-core/tests: +13
---

# #1335 attempt-level TOCTOU in the cancellation fence (+13)

The cancellation race from the #1320 review: `_settle_provider_success`
(`packages/maistro-core/src/maistro/runs/execution.py`) reads the durable Run
as its cancellation fence, then writes the Attempt — two awaits a
cancellation can walk between. At the base commit the interleaving is
reproducible deterministically: the Attempt lands COMPLETED under a Run that
is durably CANCELLED (`transition_attempt` validated only the Attempt
lifecycle and the fencing token, never the parent Run status).

Production change: each Run store (`InMemoryRunStore`, `SqliteRunStore`,
`PgRunStore`) now re-validates the parent Run status inside the same write
lock / transaction that writes the Attempt and refuses a COMPLETED target
with `InvalidLifecycleTransition` (`refuse_completion_under_terminal_run` in
`runs/lifecycle.py`), mirroring the atomicity `transition_run` already gives
its own cascade (ADR-082426-a47f). Only COMPLETED is refused: CANCELLED is
how a run-level cancel and crash reclamation settle the Attempts they find,
and FAILED/TIMED_OUT record physical outcomes that stay true after the Run
terminalized. The pg guard locks parent-first (Run `FOR SHARE` before the
Attempt row), the order `transition_run` and `repair_attempt_result` already
use (#1888), so no new wait cycle is introduced.

## Thirteen node IDs

`packages/maistro-core/tests/runs/test_execution.py` (+1):

- `test_cancellation_landing_between_the_fence_read_and_the_write_is_refused`
  — a store proxy commits the Run cancellation between the fence read and
  the COMPLETED write, deterministically reproducing the interleaving inside
  one event loop. Asserts the executor unwinds with the store's refusal AND
  that no COMPLETED Attempt exists under the CANCELLED Run (the Attempt is
  left RUNNING — the honest "disposition unknown" record — while the NodeRun
  stays settled CANCELLED by the cancel cascade).

`packages/maistro-core/tests/runs/test_spine_conformance.py` (+12, on the
three-backend `spine` fixture — memory, sqlite, postgres; the postgres legs
skip where `MAISTRO_TEST_PG_DSN` is unset, so the cross-store claim rides on
CI's postgres legs exactly like the rest of the spine):

- `test_a_completed_attempt_is_refused_under_a_terminal_run`
  parametrized over CANCELLED/FAILED/TIMED_OUT Runs ×3 backends (9). On the
  same record it pins both sides of the rule: the COMPLETED write raises and
  leaves the Attempt RUNNING with no result, while the CANCELLED edge stays
  open under the terminal Run — the contract the run-level cancel path
  depends on.
- `test_a_completed_attempt_still_writes_under_a_live_run` ×3 backends (3) —
  the guard refuses stale success, not success.

## Regression proof (local, base `9ad158230f19f35f84b2285bd128aff54ef69a2f`)

The two test files were copied onto a throwaway worktree at the base commit:
the executor test fails with `DID NOT RAISE InvalidLifecycleTransition`, and
an inline harness printed the issue verbatim —
`attempt status = completed | run status = cancelled`. All six refusal
parametrizations that run locally fail at the base and pass with the fix.
`test_a_completed_attempt_still_writes_under_a_live_run` passes on both
sides, as it should. The base checkout was a detached throwaway worktree;
this branch's tree was never reverted.

Focused command:

```text
uv run pytest packages/maistro-core/tests/runs -q
```

## Local PostgreSQL leg (executed, not skipped)

The store-level guard's pg branch was proven against a real server, not only
by reasoning about the transaction: native PostgreSQL 18.6 on
`127.0.0.1:5432`, fresh database `maistro_1335_test`, `alembic upgrade head`,
`MAISTRO_TEST_PG_DSN` set:

```text
uv run pytest packages/maistro-core/tests/runs/test_spine_conformance.py -q
  -> 380 passed (0 skipped; postgres legs live)
uv run pytest packages/maistro-core/tests/runs -q
  -> 1386 passed, 3 skipped
```

All nine refusal parametrizations and the live-run control report PASSED per
backend, `[postgres-cancelled]` / `[postgres-failed]` /
`[postgres-timed_out]` included — the `FOR SHARE` parent-first lock and the
refusal path execute inside a real asyncpg transaction.

