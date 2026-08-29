---
inventory-delta:
  tests/: +3
---
# claude-merge-group-ratchet-event-1fbc

One new file, three tests, nothing moved or deleted.

`tests/test_merge_group_event_isolation.py` holds the property that
`tests/conftest.py`'s neutral `GITHUB_EVENT_NAME` default is unconditional.
Two of the three are cheap: the default reaches a module the old filename
allowlist did not name, and a test body can still opt into `merge_group` and
win. The third is the one that would have caught this — it walks every module
under `tests/` that calls `ratchet` or `in_merge_group` and fails if the
default ever becomes conditional again.

No test was added for the two failures this fixes, because they already exist:
`test_ac_state_notes.py::test_an_improvement_passes_once_it_is_banked_in_the_branchs_own_note`
and `::test_banking_less_than_you_measured_is_slack_and_fails` were correct all
along and only failed under the event they inherited. They now pass under both.
