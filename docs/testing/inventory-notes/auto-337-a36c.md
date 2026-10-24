---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# auto-337-a36c

Repair-round additions for the merge-queue evaluation at e32a2068: the
diff-coverage gate scored changed lines and arcs in `routes/feedback.py`,
`routes/metrics.py` and `services/node_metrics_store.py` below the per-file
floor, and the acceptance-state criteria declared in SPEC-083026-2642
(AC-6..AC-10) needed their own proving tests at the seams they name. All
eight are new tests; none replaced or renamed an existing one.

Store mechanics the durability contract leans on
(`test_durable_node_metrics.py`, +5):

- a non-positive `max_observations` is refused at construction instead of
  evicting every row as it is written;
- a records store without the `initialize` seam still refreshes (the durable
  contract may not require a richer protocol than a plain mapping);
- a record whose `recorded_at` is already a native datetime loads, beside the
  ISO-string round-trip;
- load-time retention trims the records themselves to the bound, not just the
  in-memory buffer;
- `clear()` on a durable store drops the durable rows, and the emptiness
  survives a restart.

Feedback execution-identity refusals (`test_feedback_route.py`, +2): the
`_execution_identity` helper's own door — an invisible run is a 404 and a
configured-away canonical spine is a 503 — exercised directly, since
`_record_feedback` refuses earlier and no route-level test reached these
branches.

The `/v1/dag-metrics/retention` endpoint
(`test_node_metrics.py`, +1): a deployment reports `durable: false`, the
observation bound and its no-ad-hoc-delete policy instead of leaving the
route unmeasured.
