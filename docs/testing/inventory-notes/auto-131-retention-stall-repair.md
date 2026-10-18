---
inventory-delta:
  packages/maistro-core/tests: +4
---

# Issue 131 repair — the window can no longer be stalled open

The verifier's finding: `ChatRunAdmitter._sweep` skipped every non-terminal
Run, so the purported retention bound grew without limit under stalled turns
(reproduced through `Container._admit_chat_turn` with `max_retained=2`:
retained=3, stored=3, all `running`). The bound must hold exactly when the
process is misbehaving, because that is when nothing else will prune.

## What changed in the code

- `packages/maistro-core/src/maistro/runs/chat_admission.py`: the window now
  forgets the oldest Runs past `max_retained` whether or not they terminalized.
  A non-terminal Run is skipped only while something could still be living in
  it: dispatch-pending (seam mark), still CREATED/QUEUED (mid-admission), or
  holding an Attempt inside its lease (`lease_is_expired` — the same signal
  `recover_abandoned_attempts` reclaims on). Stalls — stranded admissions,
  lapsed leases, finished Attempts under an open Run — are evicted
  (`delete_run(force=True)`, the store contract for established abandonment).
- `packages/maistro-core/src/maistro/container.py`: `route_request` marks its
  Run dispatch-pending between the QUEUED and RUNNING transitions (no
  observable RUNNING/Attempt-less/unmarked moment) and releases on every exit
  (closure, refusal, cancellation, dispatch-unrecorded).
  `_admit_chat_turn` grew `dispatch_pending: bool = False`: admission-only
  callers never mark, so their abandoned Runs stay evictable.
- `packages/maistro-server/src/maistro_server/api/chat_completions.py`: the
  streaming door admits before dispatch, so it marks (`dispatch_pending=True`)
  and releases in `_close_if_open`, which bypasses `_close_chat_run`.
- `docs/adr/ADR-082326-c126-chat-turn-run-granularity-and-retention.md`:
  dated amendment recording the policy change and its two named costs.

## Test delta (+4, packages/maistro-core/tests)

`test_chat_admission.py` — one test replaced, three added:

- replaced `test_a_live_run_is_never_swept` (which pinned the defective
  status-only shield) with `test_an_executing_turn_is_never_swept`: a Run with
  an Attempt inside its 30s lease survives an 8-turn overflow burst;
- `test_stalled_turns_cannot_grow_the_store_past_the_window`: three turns left
  RUNNING with nothing under them over a window of two — the oldest goes, the
  bound holds;
- `test_an_attempt_whose_lease_lapsed_no_longer_shields_its_run`: a 1µs lease
  is a stall, evicted at the next admission;
- `test_a_finished_attempt_under_an_open_run_does_not_shield_it`: a COMPLETED
  Attempt under a RUNNING Run does not block the sweep.

`test_container_chat_runs.py` — one added:

- `test_stalled_admissions_cannot_grow_the_store_past_the_window`: the
  verifier's repro in-suite — three `_admit_chat_turn` calls that never reach
  an executor, window of two, store ends at the two newest.

## Evidence

- Focused suite (4 files: core chat admission, container chat runs, server
  chat completions, gate): 123 passed.
- `packages/maistro-core/tests/runs/` + container chat runs: 920 passed,
  209 skipped.
- Out-of-tree driver through `Container._admit_chat_turn`, `max_retained=2`,
  three sequential never-executed turns: retained=2, stored=2 (was 3/3).
