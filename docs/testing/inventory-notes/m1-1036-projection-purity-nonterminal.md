---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---
# m1-1036-projection-purity-nonterminal

#1036 projection purity for `DagRunStore` (#2364): six new node IDs, all in
`packages/hive-conductor/backend/tests`.

- `test_dag_run_store.py::test_finish_run_refuses_nonterminal_finished_at`
  (+5 — parametrized over created/queued/running/waiting/paused): a direct
  `finish_run` call with a known nonterminal canonical status must demote to
  `record_status` — `finished_at` stays null, the exact status is mirrored,
  and a later terminal write can still finish the open row.
- `test_dag_run_cancel_route.py::test_cancel_route_never_writes_projection_terminal_state`
  (+1): the public cancel route delegates to the #1169 canonical authority
  and writes no `finish_run`/`record_outcome`/`record_status` on the
  projection — spy-patched to fail on any call — while the inspection
  overlay still reports the spine's CANCELLED.
