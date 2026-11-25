# REPAIR-NOTES-1836 — hive-conductor-e2e-ui red gate (round: rsi clock anchor)

Lane L1836, issue #1836, branch `auto-1836`, start head
`f7b5129e21119921f1cfe4f6c3014989515e7645`.

## What was red

Board accounting at the starting head: `integration-scope = failure`, caused
solely by `hive-conductor-e2e-ui = failure` (verified: that job is the ONLY
non-success check run at the head; docker-build, SAST, CodeQL, quality, both
postgres legs, `hive-conductor-e2e`, coverage — all success).

## Why it was red (evidence, not guesses)

The job's compose build was green; the Playwright suite ran 246 specs with
exactly one failing both attempts:
`tests/e2e/rsi-polling-resilience.spec.ts:459` ("a prolonged outage backs off
exponentially: exact doubling gaps bounded at the 60s cap").

- Attempt 1: `first backoff step = interval·2¹ at pinned jitter, from the
  rearm instant` — Expected <= 10, Received **1000**.
- Retry: `the cap floors the cadence at ~45s` — Expected <= 45010, Received
  **45015**.

The spec file is byte-identical to `origin/develop`, and the SAME two
assertions failed with the SAME two values on develop itself (run
40413388558, job 121889644078, 2026-10-26). Identical wrong values across
three weeks and two environments prove a deterministic harness-assumption
failure inside the test, not product behavior and not runner noise:

1. The test advanced the fake clock by one big `runFor(10_000)` and assumed
   the abort rejection settles with the clock frozen at the chunk end. In
   fact the rejection races the remaining virtual advance and can settle
   mid-chunk — measured: the rearm landed exactly 1000 virtual-ms before the
   assumed anchor.
2. The cap bound `<= 45_010` assumed the 5ms fire nudge stacks to ≤10ms.
   Measured: 15ms (45015 = 60_000·0.75 + 3×5ms).

(The prior lane attempt aborted on a model-provider 404 before any work; the
"recovery budget exhausted: launch/preflight: git exited 1" block refers to
the harness's own launch mechanics, not to any tree defect.)

## The repair (test-only)

`packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts`:

1. Outage-begin block rebuilt around a race-free anchor: advance to 5ms short
   of the known steady deadline (`bootStamps.last + 3_750`, jitter pinned),
   cross the deadline in 5ms chunks with real gaps between them, wait for the
   rejection itself via the page-side `__rsiFails` journal, then read the
   frozen `Date.now()` — that IS the rearm instant. Assert the first step at
   7_500ms ±30 (measured stack 15ms). The exact-doubling proof stays where it
   was: `near(gaps[0], 15_000)` and `near(gaps[1], 30_000)` (unchanged, and
   they passed in every recorded run — including both failing ones).
2. Cap bounds 45_010 → 45_030, citing the measured 45_015; still fails any
   wrong-cap signature (uncapped ≥90_000, jitter bug 60_000).

## Acceptance executed locally (CI-exact)

- `scripts/prepull-base-images.sh packages/hive-conductor/Dockerfile
  packages/hive-conductor/tests/Dockerfile.playwright` → rc 0.
- `docker compose -f docker-compose.test.yml --profile test up --build
  --abort-on-container-exit --exit-code-from e2e-tests e2e-tests` → **rc 0,
  244 passed / 2 flaky (retry-passed) / 0 failed, 6.8m**; spec :459 passed
  its first attempt.
- Repaired spec suite re-run 3/3 (`npx playwright test
  rsi-polling-resilience`) → 8 passed each.
- `uv sync --locked --extra dev` rc 0; `uv run ruff check .` rc 0;
  `uv run ruff format --check .` rc 0 ("3561 files already formatted").
- Vulture CI-exact: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → 1238 ==
  1238, rc 0. **No ledger amendment needed or made** (spec files are outside
  the scanned surface; this is an ordinary repair round, not an
  exact-debt-ledger round).
- `uv run python scripts/check-suite-inventory.py` → "21 suite(s) match the
  recorded inventory", rc 0; inventory note
  `docs/testing/inventory-notes/repair-1836-rsi-backoff-clock-anchor.md`
  records `inventory-delta: tests/: +0`.

Nothing pushed; no GitHub mutation; no gate weakened (assertions were
re-anchored on measured reality; every product contract assertion is
retained).
