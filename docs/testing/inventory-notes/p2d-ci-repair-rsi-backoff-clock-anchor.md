---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# P2d CI repair: the RSI backoff spec's fake-clock anchors are now measured, not assumed (#2370)

CI failed exactly one required job at this branch's head `a0c032ef3d38`:
`hive-conductor-e2e-ui` (and therefore the `integration-scope` aggregate), on
`rsi-polling-resilience.spec.ts` "a prolonged outage backs off exponentially".
The same spec failed with the same assertions on pure-develop merge-queue
content (`ad44d8d6`, run 44373141093) and on an unrelated PR branch (run
44377551669) — the PR touches no frontend/RSI code, and the flake fires on
develop tip, so this is a harness defect, not a P2d regression.

## Root cause (probe-verified against the pinned Playwright 1.64.1 image)

Playwright 1.64's `clock.runFor` fires timers AT their exact deadlines (now
jumps to each deadline, then continues to the chunk end) — the spec's old
"Playwright anchors timer deadlines at the CHUNK END" comment described a
different behavior. Under a paused clock, a fired poll's four aborted fetches
settle IN REAL TIME, and `RSI.tsx`'s `finally` arms the next backoff timer at
whatever frozen virtual instant the last settle lands at. That instant depends
on abort IPC latency, which CI load varies freely:

- the old `+1000ms` first-step overshoot: the settle landed at a mid-chunk
  instant, so the rearm (and every later deadline) anchored late;
- the `+15ms` cap-gap overshoot: same race, three safety nudges in.

Both shapes were deterministic-looking (`Received: 1000` repeatedly) because
the boot sequence under the paused clock is itself deterministic — the race
window sat at the same virtual geometry on every machine.

## Change (test-only; no production code touched)

`packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts`, the clock
test only:

- the page-side journal now records every `/v1/rsi/` settlement instant
  (`__rsiSettles`, added in `stubPageEnv`);
- the patch-feed loop is unmounted for this test (`ctl.runs = []`; nothing
  auto-selects, `enabled: selectedRun !== null`) so its timers stop landing
  inside the measured chunks;
- the first outage poll is reached with 250ms chunks (a chunk can never
  traverse the 7.5s minimum backoff, so exactly one poll lands per chunk),
  each followed by a page-settle sync;
- every rearm ANCHOR is read from the settle journal after the sync, and each
  step advances from that measured anchor to its computed deadline instead of
  assuming the anchor sits at a chunk boundary. The asserted quantity is now
  the app's actual contract — the rearm delay from `RSI.tsx`'s
  `setTimeout(run, backoffDelayMs())` armed at settle time — so gap
  assertions stay at ±10ms while the IPC race is structurally absorbed.

Assertions and coverage are unchanged in kind: first step 7.5s, doubling
15s/30s, 45s cap, ≤8 polls over five virtual minutes, zero unhandled
rejections. Suite node-ID count unchanged (28 collected for
`packages/hive-conductor/tests/e2e`).

## Evidence

- Playwright clock semantics probed in the digest-pinned
  `mcr.microsoft.com/playwright:v1.64.1-noble@sha256:7852dc5a…` image: timers
  fire at exact deadlines; post-fire chunk completion is ~2ms real; arming
  mid-chunk anchors at the mid-chunk instant.
- Failed shapes reproduced locally via `docker-compose.test.yml` (the same
  spec, attempt 1 failed / retry passed, while another lane's stack ran
  concurrently), then driven green: 6/6 clean runs and 3/3 runs under four
  added CPU burners (host load average 9.4) of the isolated spec.
- The full CI gate command — `docker compose -f docker-compose.test.yml
  --profile test up --build --abort-on-container-exit --exit-code-from
  e2e-tests e2e-tests` — exits 0 with **248 passed (4.0m)**, i.e. the
  `hive-conductor-e2e-ui` job content this PR is blocked on.
- The intermediate version of this fix that assumed the loop starts from the
  first step's anchor produced `Received: 7500` on the 15s gap — the
  assertions still bind; the ladder math is not silently passing.
