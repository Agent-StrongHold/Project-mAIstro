---
inventory-delta:
  packages/maistro-core/tests: +0
---

# 2433 CI-repair: integration-scope evidence window 120 → 240 minutes (+1 node test)

<!-- pytest inventory delta is +0: the added test lives in
     tests/ci/integration-scope.test.cjs, which ci.yml runs with
     `node --test` — it is not a pytest suite (same treatment as the
     issue-41 round-9 repair). The recorded 21-suite inventory matches. -->

CI-repair round for PR #2433's red `integration-scope` gate (run
44748382537, job 136329528687, candidate `51e7f1157704`). Diagnosis from
the run's own logs and the checks API: the aggregator resolved scope
correctly (touching `ci.yml` requires all nine specialized producers),
polled the correct head SHA with the correct names, and expired its
240 × 30 s budget at 16:22:43Z with `timed out waiting for required
specialized CI evidence` — while every required producer was merely still
queued. All nine had been created at 13:54:02Z but none received a runner
until 16:39–16:48Z (strike-ladder first, 16:41:11Z), and all nine
concluded success by 17:00:32Z. The green evidence existed; it arrived 19
minutes after the budget died, ~161 minutes after the aggregator began
waiting. That is the #41/#869 failure mode again ("the window must cover
queue starvation, not just execution time") at a scale the 120-minute
widening never anticipated.

Repair, per the #41 precedent (60 → 120 minutes, run 36303867276): the
evidence window is widened to 480 × 30 s = 240 minutes inside a
245-minute job timeout. Nothing about the verdict semantics changed — a
non-success conclusion still fails immediately, the budget still fails
closed, and the required set is still the classifier's output. The
change makes the gate *more* likely to observe real evidence and fail on
genuine reds instead of timing out on green-but-starved producers.

The one added node test replays the observed starvation timeline through
the file's VM harness: ~322 attempts of empty listings, then a green
snapshot. It asserts (a) the observed starvation exceeds the retired
240-attempt budget, (b) the shipped budget covers it and the aggregator
survives to success, and (c) the retired 240-attempt budget still fails
closed on the identical timeline. Against the pre-repair workflow the
same test fails (`attempts 240 < 322`), as does the updated
125/240 → 245/480 pin, so the widening cannot be silently reverted.
All 13 node tests pass in-tree.
