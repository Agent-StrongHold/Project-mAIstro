---
inventory-delta:
  added: []
  removed: []
  notes: no test inventory change this round; the develop merge unioned tests
    that already carried notes (issue-131-repair.md, auto-131-0f5f.md)
---

# auto-131 repair round: develop merge resolution (2cf218fd)

The lane's worktree was found mid-merge with develop (ba2f1f07) and conflicts
in the two files this issue owns. Resolution, recorded so the reconciliation
is explicit rather than implied:

- `packages/maistro-core/src/maistro/runs/chat_admission.py` auto-merged to
  exactly the wanted union: develop's `WorkspaceRetentionScope`-scoped sweeper
  and `EXECUTION_NEVER_STARTED` compensation vocabulary, plus this lane's
  retention repair (`RunIntegrityError` caught in `_sweep` so a protected
  terminal parent cannot abort the sweep or the admission around it) and the
  public `sweep()` hook the container's post-terminalize trim calls.
- `packages/maistro-server/src/maistro_server/api/chat_completions.py`
  `_close_if_open`: took develop's canonical cancellation
  (`RunExecutionService.cancel_run`, idempotent, fenced) over this lane's raw
  `transition_run`, and kept this lane's trailing `_sweep_chat_runs()` — the
  abandoned-stream burst bound. Dropping either half reopens a defect: without
  the sweep, `test_abandoned_stream_cleanup_enforces_the_retention_bound`
  fails; without the service seam, cancellation bypasses the canonical model.
- `packages/maistro-core/tests/test_container_chat_runs.py`: union of both
  sides' imports and tests (develop's #338 stranded-admission suite plus this
  lane's `request_id` provenance assertion and
  `test_terminalized_concurrent_chat_burst_is_swept`).

Evidence this round (all executed in the worktree):

- Negative control: with the `RunIntegrityError` catch removed,
  `test_retention_walks_past_a_terminal_parent_with_a_child` fails at
  `store.py:1079 RunIntegrityError` — the prior finding's exact signature.
  Restored; 30/30 in `test_chat_admission.py` again.
- Lane battery: 101 passed across `test_chat_admission.py`,
  `test_container_chat_runs.py`, `test_chat_completions.py`,
  `test_chat_completions_gate.py`.
- Scoped suites: `packages/maistro-core/tests/runs/` 838 passed / 196
  skipped; `packages/maistro-server/tests/api/` 352 passed; container wiring
  79 passed / 10 skipped.
- Gates: `ruff check .`, `ruff format --check .`,
  `check-suite-inventory.py` (core + server) and
  `check-execution-lifecycles.py` all OK.

Environment oddity, recorded and bypassed: ad-hoc python scripts under /tmp
intermittently fail `import maestro` in this sandbox even with the src path
injected; worktree-resident pytest runs are reliable and were used for all
evidence above.
