---
inventory-delta:
  packages/hive-conductor/backend/tests: +15
  packages/maistro-core/tests: +1
---

# #1332 Chat-launched DAG runs are cancellable: correlation at canonical admission

`_tool_run_workflow` opened its Recent Runs projection under a fresh execution
id and never recorded the canonical `run_id`, so `POST /v1/dag-runs/{id}/cancel`
sent the projection id to the canonical store and answered 404 while the DAG
kept running. The fix adds an `on_admitted` admission seam to
`canonical_dag_runner.execute_dag` (fired after `create_run`, before any
physical node work), a `DagRunStore.record_canonical_run` write (first link
wins, persisted), and a producer-side cancellation path that follows the
canonical cancel fence without mistaking a chat-disconnect teardown for a DAG
cancellation.

+15 collected node IDs on `packages/hive-conductor/backend/tests`
(`test_chat_launched_dag_cancel.py`):

- the production-path regression: a real chat-launched DAG held in flight after
  canonical admission, listed, and cancelled **by its projection id** with no
  test-seeded mapping — the parked provider unwinds, Run/NodeRun/Attempt settle
  CANCELLED, a non-member's cancel is 404-refused before any canonical
  mutation, and the row follows canonical cancellation;
- the mapping survives a store reopen (durable `records` round-trip) and the
  shipped read route resolves it;
- missing admission (no canonical Container) and failed admission (refusing
  `create_run`) both leave a row with an empty correlation that the cancel
  route refuses — no falsely cancellable success record;
- the admission sink itself: exactly one call with the admitted id while the
  Run is still QUEUED, never invoked without a canonical store, and a raising
  sink never fails an execution the spine already admitted;
- `record_canonical_run` unit behavior: persisted, reopen-stable, missing-row
  and empty-id refusals, idempotent same-id, first-link-wins;
- the cancellation answer's honesty paths: a spine without a run store never
  mirrors a cancellation, a correlated row whose canonical Run the spine never
  fenced CANCELLED re-raises (the chat-disconnect teardown, row left running),
  and a history write failing during the cancelled stamp does not mask the
  spine's truth — the turn still follows the canonical fence.

The main regression was shown to fail against the pre-fix producer (the
projection write suppressed): it times out on "chat-launched row never
recorded its canonical admission" instead of passing.

## Repair-round evidence (2026-10-07, head `49e6ed376`)

Independently re-executed at this head, not carried over from the earlier
round:

- regression-fails-pre-fix proof re-run via a `record_canonical_run` neutered
to the pre-fix no-write behavior: the main regression fails with exactly
"chat-launched row never recorded its canonical admission";
- `test_chat_launched_dag_cancel.py` 15 passed; adjacent suites (cancel route,
durability, store, scope, canonical runner, chat admission) 156 passed;
full `packages/hive-conductor/backend/tests` 3428 passed, 6 skipped;
- `ruff check` / `ruff format --check` clean;
- `scripts/check-diff-coverage.py coverage.xml --base 0df275362` (CI's script,
merge-base): ok, 3 changed source files >=90% lines / 80% branch arcs, test
file exempt as evidence;
- `scripts/check-suite-inventory.py`: ok, 17 suites match the recorded
inventory (hive-conductor 3434 collected = 3428 + 6 skipped);
- branch-side delta vs merge-base touches no route, scope, or maistro-core
  file, and `execute_dag`'s `on_admitted` defaults to `None`, so direct-DAG
  admission behavior is untouched.

## Repair-round evidence (2026-10-07, merge of develop `1df433bf5`)

Merging develop (`#1334`, "route same-status evidence through the canonical
NodeRun transition") broke the production-path regression at this head:
`test_chat_launched_run_is_cancelled_by_projection_id_while_in_flight` failed
with `RunIntegrityError: cannot transition NodeRun ...: Run ... is terminal
(cancelled)` out of `POST /v1/dag-runs/{id}/cancel`.

Root cause (reproduced at the adapter level, not inferred): the route fences
the Run through the raw canonical store while the durable walk's registered
executor holds the `DurableRunExecutionStore` adapter -- the production wiring
(`get_engine().run_store` is `container.run_store`; the walk builds its own
adapter). The canonical cascade therefore settles the NodeRun with the
cascade's own error narrative while the durable projection still reads
running; `_cancel_settled_node_runs` then replays the cancellation through the
adapter with the caller's error text. `#1334`'s `error` clause in
`_supplies_new_evidence` routed that same-status call to the canonical store,
which can never accept it: `RUN_TRANSITIONS` has no same-status edges and
`_refuse_under_terminal_run` freezes a closed Run's history. The replay raised
AFTER the fence, aborting `cancel_run` -- on develop, for any durable-backed
in-flight cancellation.

Fix: `_supplies_new_evidence`
(`packages/maistro-core/src/maistro/graph/durable_runs/execution_store.py`)
now considers only an accepted outcome the row lacks -- the one same-status
call the store can adjudicate (the legacy-completed migration `#1334` exists
for). A differing `result`/`error` text is no longer routed; the replay
converges the projection to canonical truth instead. All three `#1334`-pinned
behaviors still hold (attaching legacy evidence reaches the store; a
same-facts replay stays a no-op; conflicting evidence still raises from the
migration validator).

Independently executed at this head:

- the new adapter regression
  (`test_a_cancellation_replay_over_the_cascade_settled_row_converges`,
  `packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py`)
  was shown to FAIL against the restored defect (routing the differing error
  text) with exactly the production `RunIntegrityError`, and to pass with the
  fix;
- `test_chat_launched_dag_cancel.py` 15 passed (was 14 passed + 1 failed
  before the fix); `test_canonical_execution_store.py` 24 passed;
- full `packages/maistro-core/tests` under CI's coverage producer: 13719
  passed, 940 skipped, 1 xfailed; full
  `packages/hive-conductor/backend/tests` under CI's producer: 3428 passed,
  6 skipped;
- `scripts/check-diff-coverage.py coverage.xml --base 1df433bf5` (CI's
  script, develop merge-base, both producers combined): ok, changed source
  files >=90% lines / 80% branch arcs, test files exempt as evidence.

## Validation round (2026-10-07, head `1fcceb71c`)

Independent re-execution of every proof at this head (no claim carried over),
plus the two defect-restoration demonstrations, each applied via a reversible
patch and reversed immediately (worktree verified clean after each):

- #1332 pre-fix proof: `record_canonical_run` neutered to the pre-fix no-write
  behavior — the production-path regression fails with exactly "chat-launched
  row never recorded its canonical admission" (`test_chat_launched_dag_cancel.py:242`);
- #1334 defect proof: `_supplies_new_evidence` restored to route differing
  result/error text — `test_a_cancellation_replay_over_the_cascade_settled_row_converges`
  fails with exactly the production `RunIntegrityError: cannot transition
  NodeRun ...: Run ... is terminal (cancelled)`; with the fix, the adapter
  suite passes 24/24;
- `test_chat_launched_dag_cancel.py` 15 passed; adjacent suites (cancel route,
  durability, store) 48 passed;
- full `packages/maistro-core/tests` under CI's coverage producer: 13719
  passed, 940 skipped, 1 xfailed; full
  `packages/hive-conductor/backend/tests` under CI's producer: 3428 passed,
  6 skipped;
- `scripts/check-diff-coverage.py coverage.xml --base 1df433bf5` (CI's script,
  merge-base, both producers combined): ok;
- `scripts/check-suite-inventory.py`: ok, 17 suites match the recorded
  inventory;
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (vulture-ratchet.yml's exact invocation): exit 0;
- `ruff check` clean, `ruff format --check` clean (3102 files).

develop's only branch-new commit (`b0912ce59`, #1707 BACKLOG migration) shares
no file with this branch's diff, so the queued merge-queue integration has no
conflict surface.
