---
inventory-delta:
  tests/: +10
---
# claude-issue-620-merge-group-slack-010e

`tests/test_check_ac_state_ratchet.py`: +5.
`tests/test_ac_state_merge_guard.py`: +5.

The original five pin review-time versus merge-group event semantics: pull
requests still bank exactly what they measured; merge groups may not demand a
future combined number; regressions in both the coverage floor and debt ceilings
remain failures; and the event name, not a queue-ref naming convention, decides
the mode.

The five merge-guard cases close the review finding that suppressing synthetic
slack alone would let that slack be spent later. Merge groups and protected
branch pushes now compare against the **actual measured base revision**, so an
improvement that exists only after two reviewed changes combine becomes the
next base measurement automatically. Tests prove that an actual-base coverage
floor cannot be lost back to a stale note, debt improvements are preserved the
same way, further improvement passes, merge-group runs select the guard, and
protected pushes use it while feature pushes keep ordinary review semantics.

`tests/conftest.py` also gives ordinary ratchet unit tests an explicit
`pull_request` event default. Merge-group-specific cases opt in inside the test,
so root pytest under a real `merge_group` job no longer changes unrelated test
semantics through ambient CI environment.
