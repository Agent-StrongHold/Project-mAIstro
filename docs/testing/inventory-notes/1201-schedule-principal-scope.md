---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-core/tests: +3
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

Coverage-repair round (+2 core tests): the merge-queue coverage gate failed on
diff coverage — `maistro/scheduling/admission.py` measured 83.3% of 6 changed
lines, uncovered line 1461: the `provenance[SCHEDULE_REQUESTED_BY_KEY] =
requested_by` stamp. The key's only assertions lived in hive-conductor backend
tests, which CI measures under `--source=packages/hive-conductor/backend`, so no
producer scoring `packages/maistro-core/src/maistro` ever executed the stamp.
Two core cases in `TestManualFire` now carry the semantics themselves: a manual
fire with `requested_by` stamps the requesting principal beside (not instead of)
the schedule actor plus the distinct `scheduler_service_id`, and a nominal
tick fire carries no requester key at all — absence must keep meaning "no
requester". Verified locally against the gate's own arithmetic:
`coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
packages/maistro-core/tests/scheduling` combined with
`--source=packages/hive-conductor/backend -m pytest
packages/hive-conductor/backend/tests`, then `scripts/check-diff-coverage.py
coverage.xml --base a9fdec4cb` → "ok: every measured file this change touches
is at or above 90% lines / 80% branch arcs". The other three merge-queue
failures are dependency/base-image advisories outside this lane: pip-audit
(`gitpython==3.1.62 CVE-2026-114145`, `graphql-core==3.2.11 CVE-2026-75507/75508`)
and trivy HIGH `CVE-2026-111943` in the `age`/`age-keygen` gobinary of the
pre-built hive-conductor image — the branch's diff touches no lockfile, no
pyproject, no Dockerfile, and no `.trivyignore.yaml` (verified byte-identical
to the develop base), so develop fails those gates identically and the repair
belongs to a dependency round, not this issue.
