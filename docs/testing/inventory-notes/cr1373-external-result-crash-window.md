---
inventory-delta:
  packages/maistro-core/tests: +1
---

# CR1373 external-result crash-window regression

M1-E2 (#1373) recovery acceptance: `CanonicalDurableRunStore.submit_external_result`
commits the Graph continuation (QUEUED, carrying the answer evidence) and only
then mirrors the lifecycle onto the Run spine. A process death between the two
writes left a Run no shipped seam could ever reach: `recover_queued_graph_runs`
pages the spine, which still read WAITING, the due index excludes QUEUED
continuations, and no `reconcile_persistence` branch matched WAITING-spine +
QUEUED-continuation. The stranded Run held an accepted external result nobody
would ever resume.

- `packages/maistro-core/tests/graph/durable_runs/test_cross_store_crash_reconciliation.py`
  (+1): `test_an_external_result_mirror_lost_to_a_crash_is_requeued_after_restart`
  drives the real executor to a WAITING harness pause, injects the crash
  between the continuation commit and the spine mirror, reopens the SQLite
  file on a fresh connection (the restarted-process shape — recovery shares no
  connection or cached object with the interrupted writer), and proves the
  shipped seams repair and finish the Run: `reconcile_persistence` rebuilds
  the lost mirror from the committed answer evidence (1 repaired, then 0), and
  `recover_queued_graph_runs` re-enters the walker, which completes the Run
  with the delivered answer.

The repair itself widens `_reconcile_answered_hitl`/`_requeue_answered_nodes`
to both parked shapes (human PAUSED, machine WAITING); answer evidence in the
continuation is what proves no live claim or walker holds the Run, because the
due index never lists QUEUED continuations. The same commit restores develop's
harness-wait resume fencing in `agent_spawn_harness.py` (no test-count change:
the existing `test_stale_answer_body_loses_to_current_wait_ordinal` regression
case covers it).

Fail-before evidence: the new case fails at the pre-repair tree exactly at the
`reconcile_persistence() == 1` assertion (0 repaired — the stranded window);
it passes after the repair.
