---
inventory-delta:
  tests/: +2
---
# fix-gates-ran-cancelled-shadowing-executed

Two new tests in `test_check_gates_ran.py` for a bug the quality.yml/
security.yml concurrency fix (#1229) exposed in `evaluate()`: when two check
runs share one name for one commit (a `push`- and `pull_request`-triggered
run of the same workflow landing in the same concurrency group, where the
loser reports `cancelled`), the old unconditional `latest[name] = run` loop
picked whichever run the check-runs API happened to return last -- in
production that was the cancelled one, so `gates-ran` reported a check that
had genuinely executed as "not executed."

- a cancelled duplicate never shadows a sibling that executed, in either list
  order;
- when neither attempt executed, list order still decides which one is
  reported (there is no executed sibling to prefer).

The existing `test_a_rerun_is_judged_by_its_latest_attempt` still passes
unchanged: an `action_required` attempt followed by a `success` attempt
resolves to `success` either way, since preferring the executed run and
falling back to list order agree on that case. No tests removed or renamed.
