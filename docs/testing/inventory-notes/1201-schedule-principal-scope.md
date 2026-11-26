---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
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

Second verifier-repair round (+4 backend node IDs = three tests, one of them
dual-leg): the verify round left three findings. (1) The archived-Workspace
automatic-fire refusal (`_canonical_scope` refusing while the presentation is
inactive) had no proving test — coverage showed the raise uncovered in both lane
producers. `test_tick_stops_firing_when_the_workspace_is_archived` now drives the
production `_tick` over both SQL backends: the schedule fires while the Workspace
presentation is active, `update_presentation(active=False)` archives it, and the
next due tick refuses with the cursor left alone (the owed occurrence stays owed,
so re-activation resumes the schedule). (2) The standalone manual-fire branch
(`fire_now` with no embedded Container) never rechecked the schedule ACTOR's
membership before minting a Run in the actor's name — a salvaged lane commit
(102134fdf) adds that gate and its revocation/re-eligibility regression test;
this round fixed that commit's lint/format violations (duplicate import, line
length) so it passes the Quality gates it had never been run against. (3) The
membership-revocation/admission TOCTOU: the eligibility check and `create_run`
are separated by several awaits and revocation holds no definition lock, so a
removal could land inside the window and still be followed by a Run admitted
under the revoked principal. All four fire paths (canonical tick, canonical
manual fire, standalone tick, standalone manual fire) now hold the existing
`hold_hitl_membership_mutation` serialization point from the eligibility check
through Run admission, and
`test_revocation_serializes_with_an_in_flight_admission` pauses the tick inside
admission and proves a concurrent `remove_member` cannot complete there — with
an in-repo counterfactual check that, with the serialization removed, the
revocation does land inside the window. Admission holds the lock only through
Run creation; consumption stays outside it.

Container-gate repair (no test-count change): the named CI failure this round
was "Container scan + SBOM + cosign". Reproduced locally with the gate's own
invocation (`trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed
--ignorefile .trivyignore.yaml`) on an image built from this branch: the finding
is CVE-2026-111943 (crypto/x509 MITM via untrusted intermediates, HIGH) in the
Go stdlib of the `golang:1.27.2-alpine` toolchain that the Dockerfiles compile
the `age`/`age-keygen` and static `docker` CLI binaries with — a fix exists
(1.27.3), so `--ignore-unfixed` cannot suppress it and no ignore entry is
warranted. Fixed at the cause: the three affected toolchain pins
(`packages/hive-conductor/Dockerfile`, root `Dockerfile`, `Dockerfile.research`)
move to `golang:1.27.3-alpine@sha256:b8c9b82a…` and `quality/image-pins.json`
records the new digest (check-image-pins + check-image-inventory green).
Rebuilt all three images locally and re-scanned: trivy exits 0 with zero
HIGH/CRITICAL findings on each, and grype `--fail-on high --only-fixed` exits 0
(two Medium CPython-base findings below the gate's threshold). `.trivyignore.yaml`
is untouched — nothing was suppressed; the vulnerable toolchain is gone.
SBOM/cosign steps are CI-keyed and content-mechanical; they consume the same
now-clean images. The pip-audit advisories named in earlier rounds
(gitpython/graphql-core, root lock) are a different job this round's brief does
not list; the branch still touches no lockfile, so develop parity there is
unchanged.

Develop-sync round (no test-count change): merging `774ae42fc` (develop) into
this branch brought #1152's `_provision_configured_workspace`, which provisions
the configured Workspace at composition time. The three #1201 fixtures that
created that Workspace themselves then hit `ValueError: Workspace '…' already
exists` (admission.py:397) or `UNIQUE constraint failed: canonical_workspaces`
(due.py:112) — the lane's own regression, reproduced by the merge and caught
before it could reach CI. Each fixture now treats the row as
create-or-grant-membership: an absent row is created with the actor as owner, an
already-present row gets the actor's `CONTRIBUTOR` membership via
`set_membership` (which grants rather than duplicates). No test was added or
removed; the `inventory-delta` above is unchanged, and the full backend suite
still collects 3959 node IDs. Executed in this round: `pytest
packages/hive-conductor/backend/tests` -> 3958 passed, 1 skipped (pg legs via
`MAISTRO_TEST_PG_DSN`); the six lane suites pass 149/149 with both store legs;
`packages/maistro-core/tests/scheduling` 314/314; ruff check/format, mypy
(canonical seven-package command), suite inventory, vulture, radon,
promotion-surface, reachability, image-pins and image-inventory gates all green
at candidate 85f242595155 + this fixture repair; a post-merge rebuild of the
hive-conductor image trivy-scans 0 HIGH/CRITICAL at the security.yml gate
arguments (golang 1.27.3 + #1152's refreshed python base, both pins
byte-identical to develop).
