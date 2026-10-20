---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
---
# Issue #65 — align Goal/Run browser fixtures with the production projection

Corrected existing Playwright fixtures in
`packages/hive-conductor/tests/e2e/goal-run-roundtrip.spec.ts`: a Goal with a
failed child Run now reports the production `blocked` disposition and failure
blocker; a paused human-waiting Run reports `waiting_human` without a failure
blocker. These are fixture corrections, not new tests. The Playwright suite is not part
of the pytest-collected inventory; the registered Conductor backend suite has
no count delta.

## Follow-up (CI-repair round): the assertion caught up with the fixture

The fixture correction above left one assertion behind: `waiting-human is
distinguishable from plain failure` still expected
`Blocker: run run-ccc33333 finished as paused` for a Goal the fixture had just
been changed to give `blocker: null`. Production never produces that text —
`services/goal_inspection.py:154-164` builds a blocker only from
`failed`/`timed_out` Runs — so the spec failed the required
`hive-conductor-e2e-ui` job on exactly that line.

Repair: the assertion now tests the distinction instead of one spelling of it.
A `waiting_human` Goal renders **no** `Blocker:` badge and shows the paused
Run's own recorded error (`waiting on approval`), while the parent Goal's
failed child Run *does* render `Blocker: run … finished as failed`. Neither
side was changed: the fixture, the seam and `Goals.tsx` all already told the
truth; only the expectation did not.

Executed evidence (live harness, `docker compose -f docker-compose.test.yml
--profile test up --build --abort-on-container-exit --exit-code-from e2e-tests
e2e-tests`, `CI=1`):

- before: `1 failed, 5 did not run, 176 passed (4.2m)` —
  `goal-run-roundtrip.spec.ts:307` timed out on `getByText(/Blocker: run .+
  finished as paused/)`;
- after: `182 passed (4.2m)`, exit 0.

Assertion-only change: no test was added or removed, so the Playwright
collection stays at 182 and the registered pytest suites are unchanged
(`check-suite-inventory.py` with no arguments: 21 suites match, including
`packages/hive-conductor/tests/e2e: 23`).
