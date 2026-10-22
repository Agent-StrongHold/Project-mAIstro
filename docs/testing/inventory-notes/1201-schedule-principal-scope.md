---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-core/tests: +1
---
# Issue 1201 — Schedule principal and Workspace scope

Adds conformance cases covering owner-stamped schedule creation and CRUD/manual-fire
enumeration resistance across two principals and Workspaces, revoked automatic-fire
eligibility (both the standalone fallback tick and the production canonical
admission boundary), and separate manual requester versus scheduled actor provenance.

Repair round: added the live two-principal manual-fire HTTP case (an authorized
foreign principal's fire is the route's own enumeration-resistant 404; the owner's
fire stamps actor, requester, and scheduler service identity onto the Run), the
canonical-path Workspace-membership revocation case (`_canonical_scope` refuses an
actor whose membership is gone), and a PostgreSQL `PgScheduleStore` round-trip case
proving `workspace_id`, `project_id`, and `actor_principal_id` survive `put`/`get`,
the project-scoped listing, and a `record_fire` cursor advance. The PG case requires
`MAISTRO_TEST_PG_DSN` and skips like the existing `test_pg_admission.py` live suite.

Verifier-repair round (+1 backend test, two parametrized legs): the verify round proved the membership
revocation gate never executed on the production automatic-fire path — `_tick_due`
passed the locked definition as `loaded`, so `_evaluate_canonical` skipped
`_canonical_scope` entirely once a definition was persisted. The scheduler now
re-runs the scope resolution on the loaded branch (persistence is not an
authority grant), the revocation case was rewritten to drive `_tick_due` — the
only recurring path a configured Hive takes — instead of the unreachable-with-a-Container
`_evaluate_schedule` direct call, and a new full-Container end-to-end
case (`test_tick_stops_firing_when_the_actor_loses_membership`) proves over both
SQL backends that a tick stops admitting after the actor's membership is removed.
The same round fixed the due-suite's postgres-leg isolation: the fixture writes
canonical Workspaces/memberships per test (and the spine writes Runs) into the
module-scoped scratch database, but the per-test TRUNCATE listed only the
schedule/project/template tables, so under CI's `MAISTRO_REQUIRE_PG_LEGS=1` step
13 of 14 postgres cases died on `canonical_workspaces_pkey` duplicates; the
fixture now resets every public table of the scratch database it owns.

Rebuild-repair round (no count change): the lane rebuild commit had mangled 219
non-issue files (four to the point of syntax errors) and dropped three lane deltas
the issue tests depend on — the `SCHEDULE_REQUESTED_BY_KEY` definition in
`maistro/runs/sources.py`, the `requester_id` stub signature in
`test_schedule_workspace_scope.py`, and the workspace-membership fixture adaptation
in `test_scheduler_canonical_due.py`. Repair restored every non-issue file to the
develop base `9ef97945e`, re-applied those three deltas, seeded the monkeypatched
Container's own workspace store in the two `test_manual_fire_canonical.py` spine
cases (production has one Container; the route-facing fallback store and the
Container store are the same instance there, so the test mirrors both seams), and
made `test_schedule_scope.py`'s list assertion membership-based so ambient rows
left by other suites cannot fail it. No test was added or removed; the deltas above
are unchanged.
