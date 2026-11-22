---
inventory-delta:
  packages/maistro-core/tests: +1
---

# m1-232-p5a-restore-local-recovered-happy-path

Repair of the develop-sync merge on this branch: the merge resolution for
`packages/maistro-core/tests/graph/durable_runs/test_canonical_execution_store.py`
took the branch's copy of the container block but develop's P4b squash
(`ceecc6457c`, landed as `33ac30c5f1`) had added one more test inside it —
`test_local_recovered_disposition_happy_path_parks_record` — and the resolution
dropped it (a repo-wide base-vs-HEAD sweep of `def test_` names across
`packages/*/tests` confirms it was the only casualty).

The test is restored byte-for-byte from `33ac30c5f1`. Every API it uses exists
unchanged at HEAD (`create_attempt` with lease kwargs, `transition_attempt`
with a fencing token, `reclaim_expired_attempts`,
`apply_recovered_attempt_disposition`); its bound-store twin
(`test_bound_recovered_disposition_mirrors_canonical_parking`) survives the
merge and uses the identical call pattern on the wired path.

Coverage it restores: `DurableRunExecutionStore._apply_local_recovered_disposition`
(`execution_store.py`) parks NodeRun+Run WAITING in-record when no canonical
RunStore is wired. Sensitivity was proven by mutation: with the local park
write reduced to a no-op, the restored test fails (`parked_node.status` stays
RUNNING) while the bound twin still passes — the local no-RunStore dispatch
(`apply_recovered_attempt_disposition` → `_apply_local_recovered_disposition`
when `self._run_store is None`) is a path no other test in the file reaches.
Without this test the happy-park local path was covered only by the two
refusal arms (`AttemptNotFound` / `RunIntegrityError`).
