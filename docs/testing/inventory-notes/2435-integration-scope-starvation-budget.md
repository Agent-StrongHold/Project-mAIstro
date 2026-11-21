---
inventory-delta:
  packages/maistro-core/tests: +0
---

# 2435 CI-repair: integration-scope evidence window 120 → 240 minutes (+1 node test)

<!-- pytest inventory delta is +0: the added test lives in
     tests/ci/integration-scope.test.cjs, which ci.yml runs with
     `node --test` — it is not a pytest suite (same treatment as the
     issue-41 round-9 repair and the 2433 starvation-budget repair).
     The recorded 21-suite inventory matches. -->

CI-repair round for PR #2435's red `integration-scope` gate (run
44748408749, job 136329616539, candidate `4ef6e28b81ed`). Diagnosis from
the checks API evidence captured for the head SHA: the aggregator
resolved scope correctly — the candidate touches only
`.github/workflows/{fleet-images,release}.yml`, so the classifier requires
exactly `docker-build` — polled the correct head SHA, and expired its
240 × 30 s evidence budget at 16:28:05Z (123.9 minutes of job runtime)
with `timed out waiting for required specialized CI evidence` while the
sole required producer was merely still queued. docker-build had been
created at 14:32:45Z but received no runner until 16:46:22Z (~134 minutes
of queue starvation), ran 17.7 minutes, and concluded success at
17:04:02Z — 159.9 minutes after the aggregator started, 36 minutes after
the aggregator had already failed. Every specialized check on the
candidate SHA concluded success; the branch content (a two-line
docker/login-action bump) was never implicated. That is the #41/#869
failure mode again ("the window must cover queue starvation, not just
execution time"), at a scale the 120-minute widening never anticipated.

Repair, per the #41 precedent (60 → 120 minutes, run 36303867276): the
evidence window is widened to 480 × 30 s = 240 minutes inside a
245-minute job timeout. Nothing about the verdict semantics changed — a
non-success conclusion still fails immediately, the budget still fails
closed, and the required set is still the classifier's output. The change
makes the gate more likely to observe real evidence and fail on genuine
reds instead of timing out on green-but-starved producers.

The one added node test replays the observed starvation timeline through
the file's VM harness: 319 attempts of empty check listings, then a green
docker-build snapshot. It asserts (a) the observed starvation exceeds the
retired 240-attempt budget, (b) the shipped budget covers it and the
aggregator survives to success, and (c) the retired 240-attempt budget
still fails closed on the identical timeline. Against the pre-repair
workflow the same test fails (`attempts 240 < 320`), as does the updated
125/240 → 245/480 pin, so the widening cannot be silently reverted.
After the develop sync merge (567d584) the file runs 14 node tests: these
13 plus the PR #2433 starvation replay that develop ships independently
(run 44748382537). The merge resolution keeps both replays — each cites a
distinct real starvation run — and pins the shared 245/480 budget once.

Scope consequence (fail-closed by design, #1351): because this repair
edits `.github/workflows/integration-scope.yml` itself, the classifier's
`_GLOBAL` set makes the candidate require every specialized leg on the
next run — the PR that modifies the aggregator must prove the full
evidence suite. That is the documented policy for gate-adjacent changes,
not a weakening.
