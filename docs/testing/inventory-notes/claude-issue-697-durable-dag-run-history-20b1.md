---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
---
# claude-issue-697-durable-dag-run-history-20b1

All 14 are added; nothing was removed, so the net is the gross. The existing
`test_dag_run_store.py` is untouched — its assertions are about the in-memory
behaviour, which is still the behaviour when no records store is configured.

`test_dag_run_history_durability.py`, four classes:

**`TestARunSurvivesTheProcess` (3)** — a run and its events come back from a
store rebuilt on the same records; a second reader that only ever reads sees
the same history (the multi-replica half); and without a records store history
stays process-local, with `is_durable` reporting that rather than implying
otherwise.

**`TestACompletedRunSaysSo` (4)** — a new run is `running`, a completed one
reports `completed` with a finish time, a failed one reports `failed` with one
too. The fourth asserts `status` and `result` are in
`DagRun.__dataclass_fields__`: the route used to assign them to a dataclass
declaring neither, so Python attached them and `to_summary` read neither. That
is the defect in one assertion — the assignment succeeded, which is why nothing
failed.

**`TestTheBoundIsStatedAndEnforced` (5)** — an evicted run leaves the records
too (a surviving row would return on the next load and re-expand past the
bound); a reload keeps the newest and drops the oldest; the retention endpoint
reports durability and both bounds; and `/retention` is not swallowed by
`/{run_id}`, asserted on the status code rather than the body because it is
about FastAPI's definition-order matching.

**`TestSubscribersAreNotHistory` (1)** — the stored record's exact key set. A
subscriber is an `asyncio.Queue` for one open connection; a future attempt to
persist one fails here rather than at the first `json.dumps` in production.

**`TestTheCanonicalIdentityHasSomewhereToGo` (2)** — a run carries a canonical
Run id when given one, and reports an empty one when not. The second is the
point: `POST /v1/dags/{id}/run` mints no canonical Run (that is #53), and
filling the field with the DAG-run id would make the record look correlated to
a Run that does not exist.

The records double round-trips through `json` rather than holding the dict,
because the real `JsonStore` serialises — a record carrying something
unserialisable would pass against a plain dict and fail in production.

**Mutation-checked**, four mutations:

| mutation | kills |
|---|---|
| never write a record | 5, including both restart cases |
| keep the row after eviction | `test_an_evicted_run_leaves_the_records_too` |
| `finish_run` stops recording the outcome | 3, including the failed-run case |
| rebuild without sorting by `started_at` | `test_a_reload_keeps_the_newest_and_drops_the_oldest` |

The last matters more than it looks: a bounded deque rebuilt in an arbitrary
order evicts an arbitrary run on the next append, which is worse than the bound.
