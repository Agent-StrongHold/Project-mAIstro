---
note: playwright-only change; no pytest-collected suite moved
---

# Issue #65 repair — Goal↔Run round trip proven at the UI layer

Prior verification found no frontend Goal/Run navigation test:
`packages/hive-conductor/backend/tests/test_goal_inspection.py` proves the
seam's projection, but nothing executed the navigation contract
`Goals.tsx`/`DagRuns.tsx` implement.

## Validation evidence

Run locally against a live `hive-conductor` (the CI `hive-conductor-e2e-ui`
harness: `docker compose -f docker-compose.test.yml --profile test run --rm
e2e-tests npx playwright test --config=tests/e2e/playwright.config.ts`):

- the new spec passes 7/7;
- the FULL Playwright suite passes **173/173** on this branch, including the
  rescaled `navigation-coverage.spec.ts` chunks that now walk the Goals row.

## What was added

`packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts` feeds the two
pages the exact response shapes `services.goal_inspection` /
`services.dag_run_inspection` serve (stubbed at the network edge, no shared
instance state) and walks the acceptance navigation:

- one Goal with two runs renders as ONE history with the run seam's exact ids
  and statuses (child-run lineage included);
- a completed run stays execution evidence while the banner reports the Goal
  outcome "not recorded";
- the selected Graph opens the canonical run that carried it;
- Goal → Run → Goal round trip with no id translation (the back-link carries
  `goal_id`, `goal_revision`, and the run's `workspace_id` as `?ws=`);
- waiting-human (paused blocker) renders distinct from plain failure;
- a run admitted outside any Goal relays no Goal link; a stale deep link
  degrades to "Select a goal", not an error;
- an empty Workspace renders the honest empty state.

Plus one `Goals` row in `tests/e2e/navigation-coverage.spec.ts`'s
`NAV_ENTRIES` and the matching `/goals` row in
`packages/hive-conductor/docs/route-inventory.md` (21 → 22 destinations), so
the shipped surface's reachability is asserted by the existing chrome contract
in both the desktop rail and the narrow drawer.

## Why no `inventory-delta` block

This suite's Playwright specs are executed by the
`hive-conductor-e2e-ui` CI job (`npx playwright test` in
`packages/hive-conductor/tests/e2e/`), not collected by pytest; the recorded
inventory count for `packages/hive-conductor/tests/e2e` (23) counts the
directory's pytest files and is unchanged by a `.spec.ts` addition. The
gate's own contract (ADR-082526-547c, `scripts/check-suite-inventory.py`)
records "no delta" by omitting the `inventory-delta:` key — a present-but-
empty block is a ledger error by design, so this note carries front matter
without the key instead.
