---
inventory-delta:
  packages/maistro-core/tests: +11
---
# claude-m1-548-node-retry-attempts

**`tests/graph/durable_runs/test_node_retry_attempts.py` (+11)** — a failed node
with budget left is tried again, as its next visit (#548):

- a node that fails twice and then succeeds produces three NodeRuns for the
  one graph node, each with one completed Attempt: the Run's history says it
  was tried three times and what happened each time;
- the budget bounds the tries and the Run still reaches FAILED, because a
  budget is a bound and not a promise;
- a node with no policy gets exactly one try, so today's behaviour is
  unchanged for every graph that says nothing about retries;
- a pause is not a failure to retry — repeating it would ask the same question
  again while the first is still outstanding;
- an unusable budget (zero, negative, or non-numeric) is one try rather than
  none, because a typo in a policy must not silently skip work, and a budget
  above the ceiling is capped rather than honoured — a graph asking for a
  thousand tries has a bug. Both are asserted with a node that *fails*: a node
  that succeeded would report one call whatever the policy said, which is the
  assertion passing for a reason unrelated to the thing under test;
- and the second walk in `durable_runs.executor`, reached by importing it
  directly rather than through the package, returns the same verdict and the
  same visit count. Its fold asks the same `first_exhausted_failure` rather
  than carrying its own copy of the rule; a divergence there would be
  invisible, because both walks would keep passing their own suites.

The retry is a **new NodeRun**, not a second Attempt under the completed one.
`AttemptExecutionService` refuses to redispatch a completed Attempt and that
guard is right: completion means the physical work ran, side effects and all.
Transport failures never reach this decision — a 429 or a 5xx is the call not
landing rather than the work failing, and `maistro.resilience.classifier`
already treats those as transient beneath the Attempt.
