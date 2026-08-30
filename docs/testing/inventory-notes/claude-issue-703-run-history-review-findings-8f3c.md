---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
---
# claude-issue-703-run-history-review-findings-8f3c

All 17 in `tests/test_dag_run_history_durability.py`; nothing deleted or moved.
Two review rounds, and the whole of this branch's delta is recorded here.

**This note is new, and it should have been.** The first round bumped
`claude-issue-697-durable-dag-run-history-20b1.md` from `+14` to `+18` instead —
that note belongs to #701, which has merged, and it describes what #701 added.
Editing it to carry a later branch's tests makes the merged change's ledger say
something it did not do, which is the exact drift these per-change notes exist
to prevent (#208). It is restored to `+14` and the 12 are here.

## Round one, +4 — the five findings from the #701 review

`reload()` made public and its freshness limit stated; `load()` deleting the
records that fell outside the bound; `finish_run` on the chat producer's
success and failure paths; the success-path `finish_run` in the run route
suppressed so a history-write failure cannot report a completed execution as
failed; and `MAX_RESULT_CHARS` truncating node responses.

## Round two, +8 — three more, all real

- **AC-1, +2** — `reload()` did not read through. `JsonStore.values()` returns
  `_data`, filled from persistence once by `initialize()`, so a `reload()` that
  only re-walked `values()` re-processed *this* replica's cache and could never
  see another replica's write — while the docstring called it "the seam a stale
  replica needs". It calls `initialize()` first now.

  **The round-one test passed against that.** Its reader and writer shared one
  `FakeRecords`, so they shared a cache, which is not what two replicas have.
  The new `CachingRecords` keeps the rows in a `SharedPersistence` outside the
  store and fills `_data` only in `initialize()`, exactly as `JsonStore` does —
  and the second case covers a records object with no `initialize` at all,
  which the in-process default is.

- **AC-5, +3** — a total budget across node results. `MAX_RESULT_CHARS` bounds
  one node; `UpdateDAGBody.nodes` is unconstrained, so a 500-node DAG still
  wrote a multi-megabyte record and the "bounded record" the store documents
  was not bounded in the dimension that actually grows. Every node stays
  present and is truncated, because which nodes ran is the shape a reader
  wants.

- **AC-2, +3** — a bookkeeping failure is not an execution failure. The `try`
  in `_tool_run_workflow` covers the event and history writes after the graph
  has returned, so a failing `append_event` marked a completed DAG `failed`.
  An `executed` flag set immediately after `execute_dag` decides the status;
  the caller gets `completed` with a warning that the history is incomplete,
  and the operator gets `dag_run_bookkeeping_failed` in the log. Asserted on
  the ordering (`execute_dag` → flag → first `append_event`) as well as on the
  branch, because the flag set in the wrong place is the same bug.

## Round two, +5 more — driving the producer instead of reading it

The three source assertions above check that the branch is *written*; the
diff-coverage gate then reported `chat_completion.py` at 14.3% of its changed
lines, which is the same observation from the other side: nothing in the suite
*ran* `_tool_run_workflow` at all. Five cases now drive it with the run store,
the graph runner and the eval judge replaced — a clean run, a run whose event
write fails, a run whose execution fails, an unknown dag id, and a failing
scorer. The scorer case matters for the same reason as the event one: a judge
is commentary on a run, not part of it, so its failure must not change the
verdict either.

## Mutations run

Five in round two, all killed: `reload()` back to not refreshing; the room
calculation back to the per-node cap alone; the budget dropping nodes instead
of truncating them; the failure branch calling everything failed again; and the
`executed` flag set after the events rather than before (2 fail).
