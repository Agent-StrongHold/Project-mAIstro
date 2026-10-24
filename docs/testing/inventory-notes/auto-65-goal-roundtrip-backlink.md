---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue #65 repair — Goal↔Run round trip on the seam, and HITL provenance

Repair round for #65 (`auto-65`). Two residuals from verification:

1. The Goal→Run link was one-directional: `Goals.tsx` navigates to the run
   surface, but the run detail carried no recorded Goal identity, so "and
   back" existed only as browser history. The repair relays the #458 Goal
   context a readable canonical Run records — `goal_context`
   (`goal_id`/`goal_revision`, verbatim, absent when unrecorded) — from
   `services.dag_run_inspection._overlay`, the same scoped one-door read the
   status overlay already performs, and `DagRuns.tsx` links back to
   `/goals?goal=<goal_id>` with those exact strings. No id translation, no
   second read, no new authority: status and control stay the seam's own.
2. HITL provenance visibility rode the generic verbatim-passthrough path with
   no dedicated assertion.

Two new tests in `packages/hive-conductor/backend/tests/test_goal_inspection.py`,
none removed or moved:

- `test_the_seam_relays_the_recorded_goal_context`: a goal-driven Run's
  `visible_run_detail` carries exactly the recorded `goal_id`/`goal_revision`;
  the Goal view groups the same run under those same strings; a run whose
  provenance names no Goal relays no `goal_context` key at all. Negative
  control: with `_goal_context_identity` returning None the test fails
  (KeyError), so it pins the relay rather than the fixture.
- `test_hitl_pause_provenance_stays_visible`: a run parked at the HITL fence
  (PAUSED) reads `waiting_human`, keeps the seam's exact id and status, and
  its recorded pause context rides through `provenance` verbatim — the pause
  is traceable execution evidence, never reclassified by the Goal view.

Two backend tests added, none removed; no other suite moved. The frontend
change adds no backend schema (the run-detail response is untyped), so the
committed `types.gen.ts` regenerates byte-identical apart from the /v1/goals
operations `openapi.json` already carries.

Frontend shape note: the link's Goal identity is typed as an inline member of
`RunDetail` (`goal_context?: { goal_id; goal_revision }`), not a page-local
`interface`. The frontend typed-client ratchet banks this page's four
hand-typed declarations by line (`EventType`/`DagEvent`/`RunSummary`/
`RunDetail`), so the repair adds no new banked row and moves none —
`scripts/check-frontend-typed-client.py` exits 0 with "136 hand-typed
tolerated, none new" against the unchanged ledger.
