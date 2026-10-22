---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---
# 359 — RSI polling resilience

`packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts` adds eight
Playwright scenarios covering the RSI page's two poll loops (#359): the five
distinct render states (unreachable / server-error / unauthorized / empty /
not-installed, with "status unknown" for a poll that cannot answer at all),
an intermittent outage that keeps last known data and clears its banner on
recovery with zero uncaught page errors, a prolonged outage whose gaps double
under `page.clock` until the 60s cap floors the cadence, a success that resets
the failure ladder to fresh and re-arms the base interval, hidden-tab and
offline pauses with immediate re-kick, an unmount that rejects the in-flight
patch-feed fetch as AbortError and stops both loops, and a slow response that
never overlaps the next poll.

CI-repair round (#359 lane): a batch returned by `Promise.allSettled` in
`loadReviews` that straddles a run switch (or unmount) — one endpoint
fulfilled, the other rejected by the abort — is now dropped whole
(`if (signal.aborted) return null;`) instead of re-applying the old run's rows
over the new run's render-phase reset; the spec gained an `afterAll` that
closes the context so the loops and the 2.5s patch-feed delay cannot leak into
the next spec. Scenario count unchanged; verified live against a locally built
stack (`auto359-e2e` compose project): 8/8 rsi-polling-resilience and 3/3
agents-rsi-keyboard scenarios passed.

The count above does not move: `check-suite-inventory.py` collects this suite
with pytest, and pytest collects only its `test_*.py` files — `*.spec.ts`
files run in `ci.yml`'s `hive-conductor-e2e-ui` job instead (the
`e2e-tests` compose service runs every spec in the directory), so the Playwright
addition is invisible to the ledger by construction. The +0 block is recorded
so the change is legible in the ledger rather than silent.
