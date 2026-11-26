---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

Covers the Hive tick's report of the winner the cursor never named (#1059), which the diff-coverage gate flagged: `services/scheduler.py` at 50% of 2 changed lines, uncovered 469.

`_evaluate_canonical` logs `admission.active_run_id` when the admitter resolves a live Run that `last_run_id` does not point at — a ticker that died before `record_fire`. That log is the only place an operator sees that overlap was judged against such a Run, and under CANCEL_OTHER which Run the admitter asked to cancel, so it is worth a test rather than a coverage waiver.

Parametrized over both arms deliberately. Covering only the reporting arm moved the gap rather than closing it: no other test in the suite reaches `_evaluate_canonical`, so the `if` was left executed along one outcome and the `465->475` branch arc went uncovered instead of line 469. The absent-winner case pins the other half — an ordinary tick that found no such Run stays silent rather than logging an absent winner.
