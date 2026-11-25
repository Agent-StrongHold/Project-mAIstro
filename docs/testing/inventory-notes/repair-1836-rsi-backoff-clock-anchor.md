---
inventory-delta:
  tests/: +0
---

# Repair round: rsi-polling-resilience clock anchoring (L1836, issue #1836)

Repairs the single red check at head `f7b5129e21119921f1cfe4f6c3014989515e7645`:
`hive-conductor-e2e-ui` (the sole non-success check run; `integration-scope`
fails only through it). The gate did not fail on build or on a product
regression: the compose images built green, 245/246 Playwright specs passed,
and exactly one spec failed both of its attempts —
`tests/e2e/rsi-polling-resilience.spec.ts:459`, a fake-clock backoff spec that
is byte-identical between this branch and `origin/develop`.

## Evidence (CI logs, read-only)

- Merge-queue job 133440583445 (this head) and develop run 40413388558 job
  121889644078 failed with **bit-identical values**:
  - `first backoff step = interval·2¹ at pinned jitter, from the rearm
    instant` — Expected ≤ 10, **Received 1000**;
  - `the cap floors the cadence at ~45s` — Expected ≤ 45010, **Received
    45015**.
  Identical wrong values across two environments three weeks apart = a
  deterministic harness-assumption failure, not runner jitter and not product
  behavior.
- The spec assumed (a) the abort rejection settles with the clock frozen at
  the end of a single `clock.runFor(10_000)` chunk, and (b) ≤10ms absorbs the
  5ms fire nudge. Measured reality: the rejection can settle **mid-advance**
  (rearm 1000 virtual-ms before the assumed chunk end) and the fire-chunk
  stack can reach 15ms (45015 = 45_000 + 3×5ms).

## Change (test-only, `packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts`)

1. First-step anchor rebuilt on a race-free measured anchor: advance to 5ms
   short of the KNOWN steady deadline (`lastStamp + 3_750`, pinned jitter),
   cross it in 5ms chunks with real gaps, wait for the rejection itself via
   `__rsiFails`, then read the frozen `Date.now()` as the exact rearm
   instant; assert the step within ±30ms of 7_500 (fire-chunk stack measured
   at 15ms). The exact-doubling contract remains pinned by the unchanged
   `near(gaps[0], 15_000)` / `near(gaps[1], 30_000)` assertions.
2. Cap bound 45_010 → 45_030 (absorbs the measured 45_015; still fails hard
   on a wrong cap: uncapped → ≥90_000, jitter bug → 60_000).

No product code changed; no pytest suite changed → `inventory-delta: +0`
(`scripts/check-suite-inventory.py`: 21/21 suites match, rc 0).

## Acceptance executed at this round

- CI-exact gate command, locally: `docker compose -f docker-compose.test.yml
  --profile test up --build --abort-on-container-exit --exit-code-from
  e2e-tests e2e-tests` → **rc 0; 244 passed, 2 flaky (passed on retry), 0
  failed, 6.8m**; the previously failing spec passed its first attempt.
- Stability: the repaired spec's suite re-run 3/3 times in the same
  containers (`npx playwright test rsi-polling-resilience`) → 8 passed each.
- `uv run ruff check .` rc 0; `uv run ruff format --check .` rc 0;
  `uv sync --locked --extra dev` rc 0.
- Vulture CI-exact (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1238 == 1238, rc 0 — **no ledger amendment** (spec
  files are outside the scanned surface).

## Residual risk

The other 245 specs are untouched; the 2 flaky-then-passing specs in the local
full run (`app-shell-loading`, `workspace-capabilities-shell`) are pre-existing
retry-absorbed flakes unrelated to this repair.
