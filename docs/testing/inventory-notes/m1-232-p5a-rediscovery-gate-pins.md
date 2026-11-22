---
inventory-delta:
  packages/maistro-core/tests: +6
---
# m1-232-p5a-rediscovery-gate-pins

#2427 repair round: pin the two behaviors the P5a rediscovery fix
(`d4de14bdb8`, "catch RecoveredDispositionRefused on terminal rediscovery")
shipped without tests for — both in
`packages/maistro-core/tests/runs/test_interrupted_reclaim_rediscovery.py`,
each spine-parametrized (memory / sqlite / postgres → 3 node IDs per test):

- `test_rediscovery_leaves_queued_prelaunch_leaves_to_the_refusal_table`
  (**+3**) — a stranded typed RECOVERED Attempt under a never-launched QUEUED
  NodeRun is the reclaim half's refusal-table row (#232 P4a D.1), not
  rediscovery scope: the RUNNING-only selector gate
  (`container.py` `_replayable_terminal_attempt`'s
  `allow_stranded_recovered=node_run.status is RunStatus.RUNNING`) must skip it
  without so much as a refusal warning, while a stranded RUNNING sibling on the
  same Run still parks and the QUEUED leaf keeps the parent Run up.
- `test_a_disposition_refusal_from_rediscovery_does_not_abort_the_tick`
  (**+3**) — forcing the selector past the RUNNING gate (the gateless shape)
  lands the QUEUED leaf in the planner's refusal table; the replay loop must
  absorb the `RecoveredDispositionRefused` (warning with `exc_info`), keep the
  leaf's physical reclaim intact, and still park the sibling — the tick does
  not die mid-sweep.

Both tests assert persisted state (statuses, attempt rows, caplog records with
typed `exc_info`), not wall-clock timing; the fixed-point second tick asserts
idempotence.
