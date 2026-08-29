---
inventory-delta:
  tests/: +1
---
# claude-564-queue-admission-drops-admissibility-5970

One test added to `tests/tools/test_enqueue_merge_queue.py`:
`test_a_red_admissibility_check_does_not_refuse_admission`. It pins the
behaviour this branch changes — a red `autonomous-merge-admissibility` no
longer refuses queue admission — so the freeze cannot return by someone
restoring the condition without a failing test. It asserts both directions,
the check absent and the check red.

No test was removed. `test_admissible_requires_both_exact_head_signals` was
renamed to `test_admission_turns_on_gates_ran_for_this_exact_head` and lost
the single assertion that required the admissibility check; that is the
behaviour being changed rather than coverage being dropped, and the new test
above carries the replacement contract. `test_latest_signal_wins` keeps its
`gates-ran` half unchanged and now asserts that a later *admissibility*
conclusion does not change the verdict, which is the same property stated
from the other side.
