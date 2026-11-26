---
inventory-delta:
  packages/maistro-core/tests: +1
---
# 1572 Goal status closed vocabulary

Adds `test_goal_status_is_a_closed_five_state_vocabulary` to
`packages/maistro-core/tests/goals/test_goal_model.py` (#1572).

`GoalStatus` is a plain class of string constants (deliberately not an enum:
the execution-lifecycles gate scopes discovery to enum/Literal state machines,
and the Goal lifecycle is domain desired-state, not execution state), so the
`Goal` model validator is the only guard on the `status` field. The new test
pins that guard from both sides:

- each of the five named states (`active`, `satisfied`, `cancelled`,
  `failed`, `superseded`) constructs and reads back equal, and the default is
  the one mutable state (`active`);
- execution vocabulary a Goal must never carry (`running`, `queued`,
  `completed`), a case variant (`ACTIVE`), and empty/whitespace/trailing-space
  strings are all rejected with `Invalid status`.
