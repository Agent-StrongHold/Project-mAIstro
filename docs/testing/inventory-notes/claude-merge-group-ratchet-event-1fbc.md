---
inventory-delta:
  tests/: +4
---
# claude-merge-group-ratchet-event-1fbc

One new file, three tests, nothing moved or deleted.

`tests/test_merge_group_event_isolation.py` holds the property that
`tests/conftest.py`'s neutral `GITHUB_EVENT_NAME` default is unconditional.
Two are cheap: the default reaches a module the old filename allowlist did not
name, and a test body can still opt into `merge_group` and win.

The other two are the ones that would have caught this. One parses the
fixture's syntax tree and fails if `setenv` is reached inside *any*
conditional — structural rather than textual, after Codex pointed out on the
PR that the first version only rejected the single spelling this change
removed, so an equivalent allowlist (`request.node.path.name in
RATCHET_TESTS`) would have sailed through it. The last asserts the AST search
actually finds both known ratchet suites, since a structural check over an
empty set passes vacuously.

No test was added for the two failures this fixes, because they already exist:
`test_ac_state_notes.py::test_an_improvement_passes_once_it_is_banked_in_the_branchs_own_note`
and `::test_banking_less_than_you_measured_is_slack_and_fails` were correct all
along and only failed under the event they inherited. They now pass under both.
