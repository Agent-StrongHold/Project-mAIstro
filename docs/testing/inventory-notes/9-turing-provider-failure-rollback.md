---
inventory-delta:
  packages/maistro-turing/tests: +2
---
# 9-turing-provider-failure-rollback

Two `maistro-turing` node IDs pin the turn-rollback contract in
`TuringChatSession.handle_message` for the exit path the existing coverage
did not reach: a provider that *raises*. `test_failed_turns_do_not_grow_the_stored_history`
exercised a failing classifier and `test_handle_message_blocks_model_result_before_history_or_memory`
a Warden-blocked result, but a crashing `acomplete` sat outside the rollback
`try`, so every provider outage left the unpaired user entry in the session's
stored history — repeated failures grew the stored state without bound and
injected never-answered turns into the next turn's model context.

- `test_provider_failure_rolls_back_the_turn`: a raising provider propagates
  its error, leaves `_history == []`, and persists no episodic capture of an
  answer that never happened.
- `test_repeated_provider_failures_do_not_grow_stored_history`: the
  `MAX_HISTORY_TURNS` bound holds across a whole failure streak, and a
  recovered turn is not modeled as answering any of the failed ones.

Both fail against the regression they name: with the rollback seam removed,
the first test retains the user entry and the second accumulates one entry
per failed turn. The delta was measured with
`check-suite-inventory.py --suite packages/maistro-turing/tests` (net +2);
the global gate was re-run over the repaired branch (develop content fully
restored) and passes — 21 suites, 34161 collected node IDs, including this
suite's 227 — so the delta rides the ordinary baseline-plus-delta contract
rather than a collection exception. This change touches only the turing
package and its tests.

Issue #9 is the M5 milestone; this change is the lane's bounded Turing
hardening slice, not a milestone exit-condition claim.
