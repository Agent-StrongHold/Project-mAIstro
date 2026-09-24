---
inventory-delta:
  packages/maistro-core/tests: +31
  packages/hive-conductor/backend/tests: +12
---

# #1120: manual schedule fire through the canonical admission spine

Adds five occurrence-identity cases to `test_spine_conformance.py`, each run
against all three Run stores (memory, SQLite, PostgreSQL — hence +15), plus a
legacy SQLite schema-upgrade case in `test_sqlite_store.py`: a
retried manual fire is one occurrence even across different wall-clock
instants (`schedule_fire_id` is the identity, not `datetime.now()`); a manual
token never consumes a nominal `(schedule_id, scheduled_for)` claim (the
`manual:` prefix keeps the identity spaces disjoint); the loser of a manual
race resolves the winner's Run via the new `find_occurrence_run` read half of
the claim; an unclaimed fire has no Run to reconcile; and nominal claims
resolve through the same lookup. Supporting changes: `occurrence_key`
understands manual fires, the SQLite/PostgreSQL claim indexes become
`COALESCE('manual:' || fire_id, scheduled_for)` (migration 042 — renumbered
after each develop collision: 034→039→042, finally re-parented onto
develop's `036_audit_log_org_scope` tip), and recurring admissions now
stamp `schedule_trigger: "recurring"` (asserted in `test_admission.py`, no
new collected cases).

Adds ten cases in the Hive suite's `test_manual_fire_canonical.py`: canonical
Workspace/Project/Run provenance for a manual fire with the legacy
`run_registered_dag` path forbidden; concurrent double submit with one
`fire_id` reconciling to one Run; retry after completion returning the same
receipt without spending a second `max_runs` unit; distinct tokens as
distinct deliberate firings; the recurring enumeration cursor
(`last_fired_at`/`next_due_at`) untouched by a hand fire; template resolution
from the canonical GraphTemplate store with the process-local registry
forbidden; failure before admission recording nothing; exhaustion enforced on
the manual path with the schedule disabled; a real-route, real-Container E2E
driving `POST /v1/schedules/{id}/run` twice with one `Idempotency-Key` and
asserting one Run consumed to a completed NodeRun and Attempt; and the
standalone no-Container fallback still reachable only through the same
`_canonical_admitter` gate the recurring loop uses.

## Merge reconciliation with develop's #1119 spine (2026-09-12)

Merging `origin/develop` (which shipped its own canonical manual-fire
implementation via `admit_due(manual=True)`) onto this branch reconciled the
two designs: develop's admitter spine (atomic `reserve_fire`/`settle_fire`
quota, fail-closed `ScheduleAdmissionUnavailable`, request correlation,
consumer-tick execution) kept as the authority, with this branch's occurrence
identity ported into it — `admit_due(..., manual=True, fire_id=...)` claims
`(schedule_id, 'manual:' + fire_id)`, and a duplicate claim returns
`ScheduleAdmission.reconciled_run_id` (the winner's receipt) instead of a
bare refusal. No test-count changes from the reconciliation itself; two
existing develop assertions were updated to the reconciled contract:
`test_admission.py::test_a_claimed_occurrence_is_reported_not_recreated` now
races on one `fire_id` token (the instant was never the identity #1120
required) and asserts the reconciliation, and
`test_schedule_manual_fire_canonical.py`'s route E2E asserts the Run is
consumed to `COMPLETED` by the manual fire's prompt consumer tick rather than
left `QUEUED` for the 30s recurring tick.

## Second repair pass: the claim answers before any refusal (2026-09-23)

Two edges surfaced by re-validating the merged head against reachable
behavior, both reproduced before repair. First, a retry carrying the same
`fire_id` after the winner's fire spent the last `max_runs` unit was refused
("has used all 1 of its runs") instead of reconciling — telling a retried
caller the fire failed when its Run demonstrably exists. `admit_due(manual=True)`
now probes the occurrence claim *before* any refusal (exhaustion snapshot,
`reserve_fire`, template resolution), so a caller-stable token whose Run
exists always reconciles; `_fire_manual_canonical`'s own `exhausted`
pre-check was removed as a stale-ordered duplicate of the admitter's, and its
reconciliation branch reads the durable row for the disable so a retry's
Hive-row projection cannot report a schedule the store has already disabled.
Second, the `Idempotency-Key` header — the route's documented retry identity —
bypassed the body's `fire_id` contract: a 5,000-character header flowed
verbatim into durable Run provenance (reproduced). The header is now held to
the same stripped/bounded contract (`_check_fire_id`), with a blank header
behaving as an absent one. Coverage: `test_admission.py` gains the
retry-after-exhaustion and retry-after-template-deletion reconciliations
(+2); the Hive suite gains the service-level retry-after-exhaustion receipt
and the route-level idempotency-key contract test (stripped keys reconcile
to one Run; an over-long key is a 422 before any durable write) (+2).

## Third repair pass: merge with develop 84d937add (2026-09-23)

Develop's #1531/#1079/#1395 took the alembic ids this branch had claimed
(`039`, then the `040` parent, then the `036_audit_log_org_scope` tip), so the
manual-fire occurrence migration renumbered 039→041→042 and re-parented onto
develop's chain tip `036_audit_log_org_scope` — the same reconciliation that
revision's own docstring records. `tests/migrations/test_audit_scope_migration.py::test_audit_scope_migration_is_the_single_head`
pinned the audit migration AS the tip; it now asserts the same contract the
way it survives any later migration: exactly one head, with the audit scope
migration on that head's chain. No collected-test counts changed this pass
(96 migration tests, 1322 core runs+scheduling on PG legs, 2577 Hive backend
— the deltas over the prior pass are develop's own new suites).
## Sixth pass: the crash window holds, it does not spend (2026-09-23)

The finding this pass repairs: `reserve_fire` durably counted the run and
disabled on exhaustion *before* any Run existed, so a process that died
between the reservation and the Run insert left the durable row claiming a
firing that never happened — reproduced on a fresh SQLite store (restart
preserved `runs_so_far=1`, `enabled=False`, `last_run_id=None`): a
`max_runs=1` schedule was bricked, no Run, no retry possible. The claim is
now a durable `PendingFire` marker naming the fire's token: it holds the
slot (every exhaustion check counts held markers, so the #1119 last-run race
stays closed) but spends nothing — `runs_so_far`, `enabled`, and the cursors
move only in `settle_pending_fire`, the one write that also removes the
marker and links the Run. A holder that dies mid-window leaves the marker
for recovery (`_reconcile_pending_fires`, lease-gated by
`_PENDING_FIRE_LEASE` so a live fire is never touched): a Run for its token
confirms the spend, no Run releases the slot. The in-memory
`FireReservation` type is gone; `reserve_fire`/`settle_pending_fire` are the
two store methods, both implementations (in-memory, PostgreSQL) share
`_reserve`/`_settle_pending` so they cannot drift.

Coverage (+13 `packages/maistro-core/tests`): `test_store.py` rewrites the
reservation cases to the hold/settle contract — a hold does not spend, the
held slot counts until settled, a release leaves no trace, a confirmation
spends and disables on exhaustion, settling without a marker answers None,
the marker survives the payload round trip (+9 across the three store
backends), plus an executed fresh-SQLite crash-window reproduction: kill
between reserve and Run, restart, nothing spent (+1). `test_admission.py`
gains the crash window end to end — a crashed fire leaves no firing and its
retry fires, the recurring tick releases a stale marker before firing what
is owed, and a fresh (in-lease) marker is untouchable by tick and rival fire
alike (+3); the failure-after-Run case is rewritten to assert the row stays
unspent until recovery confirms it from the Run itself. Hive-side behavior
is unchanged by this pass (its suite still collects 2578): the admitter's
contract shift is invisible to the route and service, which keep reading
`ScheduleAdmission`.

Also in this pass: `scheduler.py`'s committed text had picked up CRLF line
terminators (the merge at `d60bc7fd6`) and the handoff note a trailing
space — normalized back to LF; no content change.

## Independent verification pass at 5e75e7e9 (2026-09-23)

Re-executed at the exact head. Driver checks all pass (uv sync, ruff
check/format, core 421 passed/147 skipped, Hive 100 passed, both suite
inventories). Independently re-run: radon gate EXIT=0 (70/70 blocks — the
prior un-baselined `_admit_manual` C-block is gone via decomposition);
convergence-matrix checker EXIT=0; ruff check clean. The vulture gate still
exits 1 (1430 findings vs 1415 reviewed), reproduced on a git-archive scratch
tree of base 8bb344e32 with a byte-identical findings multiset after
line-number normalization (1430=1430, no added/removed identities) — the
failure is the upstream ledger's staleness, not branch debt. PG legs re-run
on a fresh disposable pg18 container (`MAISTRO_TEST_PG_DSN`) after
`alembic upgrade head` through the full chain ending at single head 042:
544 core runs/scheduling tests and 29 migration tests pass; migration tests
and core suites also pass without a DSN (PG params skip). Adjacent Hive
route-consumer suites (scheduler-canonical-admission, scope-coverage,
registered-dag-recovery, evolution-service, platform) 127 passed. Acceptance
re-derived from the issue: configured `fire_now` admits through
`ScheduleRunAdmitter.admit_due(manual=True, fire_id=...)` (canonical
Workspace/Project via `_canonical_scope`, fail-closed
`ScheduleAdmissionUnavailable` instead of the compatibility path, which now
requires no Container at all); occurrence identity is
`(schedule_id, 'manual:' + fire_id)` with the `manual:` prefix keeping
identity spaces disjoint; route double submit on one `Idempotency-Key`
reconciles to one Run (E2E asserts canonical scope, `schedule_trigger` manual
vs recurring provenance, durable template, prompt consumption to a completed
NodeRun+Attempt, one count against `max_runs`); pending-fire markers hold
without spending so a pre-Run crash claims nothing and a post-admission crash
recovers via `_reconcile_pending_fires`. No premature closure keywords in the
PR body or commit messages (references only). No issues remain open on this
verifier's list.

## Independent re-verification pass at 87d783f7e (2026-09-23)

Docs-only delta from 5e75e7e9, so the code surface is identical; every claim
above was re-derived and re-executed rather than trusted. Gates: ruff check
and format clean; radon EXIT=0 (70/70); convergence-matrix checker EXIT=0;
mypy clean across all six packages (712 files); both touched suite
inventories match. The vulture gate still exits 1 (1430 vs 1415 reviewed);
this pass compared the **raw vulture scans** (not just the checker's summary)
of head 87d783f7e and a git-archive tree of base 8bb344e32 — 1430 = 1430
line-normalized findings, `diff` empty — proving upstream ledger staleness.
PG legs on a fresh disposable pg18 container after `alembic upgrade head`
through the full chain to single head 042: core scheduling + runs dirs
1361 passed / 3 skipped, and the **entire** Hive backend suite 2668 passed /
1 skipped — including the real-route E2E `test_the_manual_fire_route_runs_
the_canonical_spine_end_to_end` (one Idempotency-Key, two POSTs, one Run,
canonical Workspace/Project, manual provenance, completed NodeRun + Attempt,
`runs_so_far == 1`), the loser-race reconciliation
`test_a_loser_that_missed_the_probe_reconciles_to_the_winner`, and the
crash-window cases (`test_a_crashed_fire_leaves_no_firing_and_a_retry_fires`,
`test_a_crash_between_reserve_and_run_leaves_no_firing_behind`). Without a
DSN the same core suites pass 516/150 skipped and the four focused Hive
manual-fire suites 100 passed. No defects found; no tree changes made by
verification itself beyond this note.

## Ninth-pass independent verification @ 6b7ccb9beff7 (2026-09-24)

Re-derived from the issue text, not trusted from prior passes. Same head as
the eighth pass (6b7ccb9beff7); all results re-executed fresh:

- ruff check EXIT=0 ("All checks passed!"), ruff format clean (2535 files).
- radon gate EXIT=0 (70/70 baselined, 0 new/regressed/stale).
- vulture gate EXIT=1 still (1430 findings vs 1415 reviewed) — re-proven
  upstream, not branch-caused: raw `vulture packages tests` scans of HEAD and
  a git-archive tree of merge base 1dea30dfe give **identical identity
  multisets (1255 unique, 0 added / 0 removed)**; quality/ ledgers are
  byte-identical base..HEAD. Remedy remains a reviewed grant, out of lane.
- Core scheduling + runs + tests/migrations/test_audit_scope_migration.py:
  1124 passed / 243 skipped without a DSN; **with a fresh pg18 container**
  (dedicated `auto-1120-verify2-pg`, port 47331) after `DATABASE_URL=…
  alembic upgrade head` running the full chain to single head 042:
  **1361 passed / 3 skipped** — spine conformance green on memory, SQLite,
  **and PostgreSQL** legs, including the five manual-fire occurrence-identity
  cases and the migration-042 index rewrite.
- Focused Hive suites (test_manual_fire_canonical,
  test_schedule_manual_fire_canonical, test_schedule_workspace_scope,
  test_scheduler): 100 passed. Entire Hive backend suite: **2675 passed /
  1 skipped**.
- mypy packages/maistro-core/src: 5 errors, all `import-not-found` for
  `maistro_bootstrap.*` inside untouched `maistro/cli/_builders_tui.py` /
  `_install.py` (bootstrap extras not synced in this scratch); a git-archive
  base tree shows the same environmental class (31 similar stub errors), and
  **no error touches the branch's changed files**.
- Doc gates: check-convergence-matrix.py EXIT=0 (52 subsystems / 1117
  modules), check-doc-links.py EXIT=0.
- Closure-keyword audit: 0 matches for `fixes/closes/resolves #N` across all
  commit messages base..HEAD; PR #1315 body says "Refs #1120" only (draft).
- Code re-read (not just tests): `fire_now` fails closed with
  `ScheduleAdmissionUnavailable` for a configured-but-unwired Container;
  `run_registered_dag` is reachable only from the no-Container compat branches
  (scheduler.py `_fire_schedule` callers :127/:722); occurrence identity is
  `(schedule_id, "manual:" + fire_id)` (sources.py `occurrence_key`),
  provenance stamps `schedule_trigger` manual|recurring + `schedule_fire_id`
  (admission.py `_admit_one`); reserve→settle `PendingFire` ordering with
  `_reconcile_pending_fires` lease recovery; cursor untouched by manual fire.

No new defects. No tree edits beyond this note.

## Tenth-pass independent verification @ c82ee9bc02d9 (2026-09-24)

Repair-phase re-validation at the same code state as the ninth pass (HEAD is
the ninth pass's note commit; zero code deltas since 6b7ccb9beff7). No
check-*.log existed in this job's directory, so every check was re-executed
fresh and no prior claim was trusted:

- ruff check EXIT=0 ("All checks passed!"), ruff format --check clean (2535
  files already formatted).
- radon gate EXIT=0 (70 reviewed C-or-worse blocks -> 70; 0 new / 0
  regressed / 0 stale; baseline base 1dea30dfe30c, candidate c82ee9bc02d9).
- vulture gate EXIT=1 still (1430 findings vs 1415 reviewed) — upstream
  staleness re-proven cheap but exact: `git diff 1dea30dfe HEAD -- quality/`
  is **empty** (vulture-baseline, ratchet-authorizations, radon-baseline all
  byte-identical to the merged develop tip), so the branch banks nothing new;
  the remedy stays a reviewed grant, out of lane by hard prohibition.
- Focused Hive suites (test_manual_fire_canonical,
  test_schedule_manual_fire_canonical, test_schedule_workspace_scope,
  test_scheduler), bare .venv python per SUITE-INVENTORY: **100 passed**.
- Five key E2Es re-run individually, all PASSED:
  test_the_manual_fire_route_runs_the_canonical_spine_end_to_end (real POST
  /v1/schedules/{id}/run + Idempotency-Key double submit -> one Run in
  canonical Workspace/Project scope, provenance schedule_trigger=manual +
  schedule_fire_id, prompt consumption to completed NodeRun + Attempt),
  test_a_double_submit_reconciles_to_one_run,
  test_an_idempotency_key_meets_the_fire_id_contract,
  test_the_standalone_fallback_is_gated_to_no_container,
  test_a_retry_after_exhaustation_returns_the_winners_receipt.
- maistro-core tests/scheduling: 247 passed / 34 skipped (PG legs
  capability-gated; PG parity 1361 passed on a fresh pg18 container in the
  ninth pass at this same code state).
- runs/test_spine_conformance.py manual subset: 8 passed / 4 skipped
  (SQLite legs); runs/test_sqlite_store.py: 24 passed;
  tests/migrations/test_audit_scope_migration.py: 3 passed.
- Doc gates: check-convergence-matrix.py EXIT=0, check-doc-links.py EXIT=0,
  check-suite-inventory.py EXIT=0.
- Code re-read confirming each criterion's production path: fire_now gates
  on _canonical_admitter -> _fire_manual_canonical (scheduler.py:92-103);
  ScheduleAdmissionUnavailable fail-closed for an unwired Container;
  hive:schedule:{sid} + run_registered_dag only in the no-Container compat
  branch (_as_definition :229-230, _fire_schedule :834/:847); occurrence
  identity (schedule_id, "manual:" + fire_id) via occurrence_key
  (sources.py:94-107); provenance stamping schedule_trigger
  manual|recurring + schedule_fire_id (admission.py:1334-1346);
  reserve->settle PendingFire with _reconcile_pending_fires recovery;
  reconciliation hands the winner's receipt
  (_fire_manual_canonical reconciled_run_id branch); CONVERGENCE-MATRIX row
  128 + summary 181 name recurring+manual canonical admission with
  run_registered_dag as the no-Container fallback only.

No new defects. No tree edits beyond this note.

