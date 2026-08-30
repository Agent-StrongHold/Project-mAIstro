---
inventory-delta:
  tests/: +15
---
# claude-issue-685-grant-record-bookkeeping-c0c6

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

All 15 are added and nothing was removed, all in
`tests/test_ac_state_authorized_floor.py`, across three new classes covering
SPEC-082926-6f49 AC-10, AC-11 and AC-12.

**AC-10, five tests** — the candidate grants file is now read by the rule the
base reads it by. Four drive a record the base would refuse and the candidate
used to accept: emptied to `{}`, replaced by a scalar, a key whose value does
not parse, and a key naming a debt ceiling rather than a floor. The fifth is
the control that a well-formed file still reads, because validation that
refuses everything would pass the other four for the wrong reason.

**AC-11, eight tests** — a protected push cannot spend a grant and delete it.
Four are the decision (removal refused, retention allowed, a prune this push
does not rely on still allowed, a merge group not asked twice) and three cover
the paths the diff-coverage gate found bare: the no-grant early return, the
malformed-file refusal, and — the one that matters — that `main` turns the
check on only for a protected push. `_spent_grants_removed` being correct while
`main` never enables it is exactly the shape finding 2 *was*: the retention
check existed and this path never reached it. The last is parametrized over
push and merge_group, so it is two node IDs.

**AC-12, two tests** — pruning a spent grant while banking an improvement, which
#673 left impossible and #692 closed. The improving case fails against
`df7b5da` (pre-#692) with the unreachable "Bank it" remedy and passes here; the
non-improving one passes both ways, which is what #673 already allowed. The
joint property spans two changes, so nothing else states it.

Ten of the fifteen die when both gate scripts are reverted to `develop`'s.
The five survivors are the controls and the cases `develop` already handles: a
well-formed candidate file still reads, a merge group is unchanged, a push with
no grant in play is unasked, and both AC-12 cases — that pair passes on current
`develop` precisely because #692 has landed there, which is the point they
record.
