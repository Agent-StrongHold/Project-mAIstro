# issue-1199-canonical-scheduler

This branch first carried a parallel implementation of #1199 (tick from
canonical `ScheduleStore.due()`, persist every computed `next_due_at`,
serialized SQLite `record_fire`) with its own focused tests. Before this sync,
`origin/develop` landed the same convergence through reviewed PRs — #1304
(record the due cursor on every evaluation; serialize SQLite `record_fire`),
#1603 (canonical `ScheduleStore` as the write authority for `/v1/schedules`
definitions), #1625/#1666 (per-occurrence canonical Run admission and claims) —
with strictly broader coverage: the concurrency test runs against every store
implementation, the tick/restart tests drive a real wired Container, and the
due-cursor tests cover the future-not-due defect at admission level.

The develop sync therefore resolves every conflict in favor of the develop
implementation and retires this branch's superseded parallel code and tests.
No suite count moves relative to the synced base, so no `inventory-delta` is
recorded. Acceptance coverage on the merged tree:

- the live tick enumerates candidates from `ScheduleStore.due()`
  (`services/scheduler.py` `_tick_due`; the legacy `stores.schedules` dict is a
  response projection and an unwired-fallback only);
- every evaluation persists the computed `next_due_at`, including evaluations
  that fire nothing (`test_admission.py::TestTheDueCursorIsRecordedWithoutAFire`);
- overlapping SQLite `record_fire` callers cannot lose cursor updates
  (`test_store.py::test_concurrent_record_fire_on_one_store_does_not_lose_an_increment`,
  parametrized over all store implementations);
- a restart resumes from durable canonical state without re-firing
  (`test_scheduler_canonical_admission.py::test_restart_executes_the_queued_run_once`,
  `test_restart_after_a_cursor_crash_keeps_the_same_run`);
- a stale Hive row cannot force a schedule that is not due
  (`test_hive_row_cannot_force_a_schedule_that_is_not_due`);
- occurrence uniqueness stays owned by the Run store's `(schedule_id,
  scheduled_for)` claim (#850/#220), not the tick: two concurrent tick
  evaluations of one schedule produce one Run and one counted fire
  (`test_scheduler_canonical_admission.py::test_two_live_runners_claim_one_occurrence`);
- the real tick runs on both supported SQL backends
  (`test_scheduler_canonical_due.py`, parametrized over `SqliteScheduleStore`
  and `PgScheduleStore` on the real alembic schema).

First-party re-validation at the pre-sync head cd4fdd4d7 (pgvector:pg18
container, real alembic chain to head): the core scheduling suite passes with
the PostgreSQL legs live (311 passed, 0 skipped),
`test_scheduler_canonical_due.py` passes 28/28 against PostgreSQL, and
`test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` passes
across the memory, SQLite, and PostgreSQL parametrizations. At that head the
repo-wide suite-inventory gate reported `DRIFT tests/: expected 5260,
collected 5261`; collecting `tests/` at the then-synced base commit (2f56be40)
in the same environment also yielded 5261, so the one-test drift was inherited
from that base, not introduced by this branch (whose diff is this note and the
ADR status update only).

CI at cd4fdd4d7's successor e552fca6c reded on exactly that drift (the `test`
job's inventory step) and on the coverage gate's base-inherited publish-set
floor. The sync merge to origin/develop (1a2e12656) resolves both: develop
reconciled the inventory, and the merged head collects `tests/: 5504` with the
gate reporting `ok: 17 suite(s) match the recorded inventory`. The diff leg of
the coverage gate passes on this head by construction — `git diff
1a2e12656...HEAD` is this note and the ADR status update, zero measured Python
files — and the 87% publish-set floor is content-determined by the merged
develop base, which this branch's docs-only diff cannot move.

Merged-head (cbcaa5c28) re-validation, all commands run first-party:

- core scheduling with the PG legs live (pgvector:pg18, `alembic upgrade head`
  to 063): `packages/maistro-core/tests/scheduling/` 311 passed, 0 skipped;
- `test_scheduler_canonical_due.py` 28/28 (14 sqlite + 14 postgres legs on the
  real alembic schema); the canonical admission/due/manual-fire/definition
  suites together 92 passed;
- `test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` across
  the memory, SQLite, and PostgreSQL parametrizations;
- the `test` job's Python steps at this tree, CI environment (REQUIRE_AUTH=
  false, MAISTRO_DRY_RUN=1, no services): root `tests/` 5276 passed / 135
  skipped; hive-conductor backend 3654 passed / 20 skipped; server, turing
  (both suites), design, ext-harness, ext-sdk 1857 passed / 9 skipped; the
  one-process cross-suite leakage proof 9595 passed / 156 skipped;
- gates: `check-suite-inventory.py` ok, `check-test-duplicates.py` ok,
  `check-diff-coverage.py --base 1a2e12656` ok (0 changed files measured),
  ruff check and format clean.

CI repair at the merged head (49e60c36), first-party: the merge-queue
coverage (no services) job red on
`test_cross_process_peer_injection_refused_by_canonical_warden` — the
`_PEER_SERVER` child made the port file visible before the port bytes were
flushed and a parent poll read `''` (`int('')` ValueError), taking
down `coverage-gate` and `gates-ran` with it. See
[issue-1199-coverage-port-file-race.md](issue-1199-coverage-port-file-race.md)
for the CI-log-derived root cause, the atomic-publish + tolerant-poll fix, and
the regression proof (new test reproduces the exact CI error against the
unfixed helper, then passes; a2a directory 281 passed).

Queue-clear re-validation at 0edfccf9b (first-party, pgvector:pg18 at
127.0.0.1:18999, fresh database migrated `alembic upgrade head` to 063): core
scheduling 311 passed / 0 skipped with the PG legs live;
`test_scheduler_canonical_due.py` 28/28 on both SQL backends; canonical
admission, manual-fire, definitions, and scheduler suites together 101 passed;
`test_concurrent_record_fire_on_one_store_does_not_lose_an_increment` across
memory, SQLite, and PostgreSQL; the named AC tests — restart
(`test_restart_executes_the_queued_run_once`,
`test_restart_after_a_cursor_crash_keeps_the_same_run`), two-runner occurrence
claim (`test_two_live_runners_claim_one_occurrence`), stale-Hive-row
(`test_hive_row_cannot_force_a_schedule_that_is_not_due`), and the port-file
regression (`test_base_url_tolerates_a_transiently_empty_port_file`) — all
pass, the full a2a directory 281 passed. `check-suite-inventory.py` reports
`ok: 17 suite(s) match the recorded inventory`, `check-test-duplicates.py`
ok, the vulture gate exits 0 (1322/1322 banked), and ruff check/format are
clean. This branch's file content is now identical to origin/develop for every
path it touched (the merge queue landed it); the runs above are the head-level
evidence the lane brief asked to re-confirm after the GH006 queue block
cleared. No suite count moves, so no inventory delta is recorded.

The #2467 reactivation (canonical write authority across restart) is a later,
separate round on this lane: its implementation and evidence live in
[issue-1199-projection-authority.md](issue-1199-projection-authority.md)
(startup and read-path projection repair from canonical, durable tombstones,
degraded projection-failure semantics) with its own inventory delta.

## Re-validation at the #46-reactivation head 4dd5c94af8 (2026-11-22)

First-party re-run of the acceptance-relevant suites at this exact head
(`auto-46` = 4dd5c94af835b86e71325da7ffac0a261f7d0623, base 33ac30c5):

- `uv run ruff check .` and `uv run ruff format --check .`: clean.
- `uv run mypy` over the seven documented package srcs: no issues in 905 files.
- `scripts/check-suite-inventory.py`: ok, 21 suites match;
  `scripts/check-test-duplicates.py`: ok, no byte-identical test files.
- Core scheduling with the PostgreSQL legs live (dedicated pgvector:pg18
  container on the real `alembic upgrade head` chain, 063 at this head):
  `packages/maistro-core/tests/scheduling/` 311 passed, 0 skipped
  (`MAISTRO_TEST_PG_DSN`); without the DSN the same suite is 274 passed,
  37 skipped — every skip is a PostgreSQL leg, and every one goes green live.
- Hive-conductor scheduler/definition/scope suites
  (`test_scheduler*.py`, `test_schedule_*.py`, `test_manual_fire_canonical.py`,
  `test_schedule_manual_fire_canonical.py`): 181 passed / 14 skipped without
  PG; 195 passed / 0 skipped with the same live DSN.

Re-validation at the exact assigned head b27d0accab (2026-11-22, verifier
round): every number above was re-run first-party in a detached clean
worktree at b27d0accab (the assigned worktree carries uncommitted other-lane
residue, so the committed tree was validated in isolation):

- `uv run ruff check .`: all checks passed; `uv run ruff format --check .`:
  3360 files already formatted.
- `uv run mypy` over the seven documented package srcs: no issues in 905
  source files.
- `scripts/check-suite-inventory.py`: ok, 21 suites match;
  `scripts/check-test-duplicates.py`: ok; `scripts/check-doc-links.py`: ok.
- Core scheduling with `MAISTRO_TEST_PG_DSN` (dedicated pgvector:pg18
  container, the suites' own `alembic upgrade head` scratch databases):
  `packages/maistro-core/tests/scheduling/` 311 passed, 0 skipped (13.1s).
- Hive-conductor scheduler/definition/scope/manual-fire suites
  (`test_scheduler.py`, `test_scheduler_bounded_tick.py`,
  `test_scheduler_canonical_admission.py`, `test_scheduler_canonical_due.py`,
  `test_schedule_canonical_definitions.py`, `test_schedule_frequency_floor.py`,
  `test_schedule_manual_fire_canonical.py`, `test_manual_fire_canonical.py`,
  `test_schedule_workspace_scope.py`) with the same live DSN: 195 passed,
  0 skipped (22.5s).
- Strict-#459 scenario re-check: `REAL_SCHEDULE_CONDUCTOR_SCENARIO`
  (`tests/cross_product_parity/harness.py:230`) is still a
  permanently-evidenced blocker — its `REAL_SCENARIO_EVIDENCE:
  schedule-conductor` token exists nowhere outside the parity harness —
  consistent with the reactivated issue reserving the real
  app-lifespan/crash-between-writes scenario for the reopened #1199/#2467
  lanes.
- At this head the branch's scheduling code is byte-identical to its
  develop merge parent fad17a87c3; the branch's only unique delta is this
  note, so nothing here can regress the develop base's scheduler behavior.
  The assigned worktree additionally holds an uncommitted, partial develop
  sync of the scheduling subtree (nine modified/untracked scheduling files
  verified byte-identical to develop base ae1cb3b); it is left untouched for
  the integration develop-sync step and was excluded from this validation.

No suite count moves (docs-only addendum), so no `inventory-delta` is
recorded.

Reactivated-#46 status at this head: the #2467 projection-authority defect is
still present — `services/scheduler.py::run` calls
`backfill_canonical_definitions()` unconditionally on every startup (line 363)
and `_backfill_one` puts a Hive-row-derived definition whenever the canonical
row is missing or drifted (lines 332–344), while `routes/schedules.py`
commits canonical writes before the Hive projection (update: lines 402→406;
delete: lines 425–426). A crash between those writes is therefore "repaired"
at next startup by the stale projection overwriting or resurrecting canonical
state. The one-time/tombstone-aware migration and projection-repair work for
that defect is owned by the reopened #1199 and #2467 lanes (heads
1326ca7eb4 / c486fc806f, not ancestors of this branch); no test count moves
here, so no `inventory-delta` is recorded for this addendum.

## Develop-sync resolution and re-validation at 86adf48103 (2026-11-22)

The lane's previous attempt (job c60c01cbb64b484cbf463e111c18a1d6) blocked
mid develop-sync: it left a develop-content overlay in the working tree that
blocked any `origin/develop` merge (1091 of 1096 untracked paths exist in
develop; the driver salvage commit 3a9e9fc8d0 captured only the 588 tracked
modifications). This round completed the sync as the lane brief directs:

- every one of the 1109 untracked files (1091 files plus the 18 files inside
  the 5 untracked directories) was verified byte-identical to
  `origin/develop` blobs before staging, then committed as the overlay
  commit e14ea64f3e — no unique local work is contained in it;
- `git merge origin/develop` (ae1cb3b17e) predicted 20 content conflicts;
  all 20 were verified to be salvage-overlay paths (each file's ours-side
  came from the develop-content overlay, never unique lane work), so the
  merge resolved them to develop's side, plus one modify/delete
  (`test_registry.py`) resolved to develop's version; merge commit
  538b1d5bc0;
- the 3-way merge had also stitched stale overlay entries (browser-use,
  google-api-*, ollama, openai, …) into `uv.lock`; because the merged
  pyproject files are byte-identical to `origin/develop`'s, the lock was
  reconciled to develop's wholesale in 86adf48103 (the stitched lock stays
  reachable at 538b1d5bc0), and `uv sync --locked --extra dev` rebuilt the
  environment from it;
- post-sync tree check: `git diff origin/develop HEAD --name-only` is
  exactly this note — every scheduling file (scheduler.py,
  routes/schedules.py, scheduling/{store,admission,pg_store,model}.py) is
  byte-identical to `origin/develop`.

First-party re-validation at 86adf48103 (pgvector:pg18 container
`auto-46-pg`, DSN on 127.0.0.1:16432):

- `uv run ruff check .`: all checks passed; `uv run ruff format --check .`:
  3619 files already formatted.
- `uv run mypy` over the seven documented package srcs: no issues in 959
  source files.
- `scripts/check-suite-inventory.py` (uv run): ok, 21 suites match the
  recorded inventory; `scripts/check-test-duplicates.py`: ok;
  `scripts/check-doc-links.py`: ok.
- Core scheduling with the PostgreSQL legs live
  (`MAISTRO_TEST_PG_DSN=postgresql://maistro:auto46@127.0.0.1:16432/maistro`):
  `packages/maistro-core/tests/scheduling/` 327 passed, 0 skipped (16s).
- Hive-conductor scheduler/definition/scope/manual-fire suites
  (`test_scheduler.py`, `test_scheduler_bounded_tick.py`,
  `test_scheduler_canonical_admission.py`, `test_scheduler_canonical_due.py`,
  `test_schedule_canonical_definitions.py`, `test_schedule_frequency_floor.py`,
  `test_schedule_manual_fire_canonical.py`, `test_manual_fire_canonical.py`,
  `test_schedule_workspace_scope.py`) with the same live DSN: 204 passed,
  0 skipped (30s). (Suite counts grew vs the pre-sync 311/195 because the
  merge brought develop's newer scheduling tests and inventory baseline,
  which the suite-inventory gate confirms as matching.)

Reactivated-#46 status at 86adf48103 (unchanged by this sync, now with
develop-exact line numbers):

- the #2467 authority-inversion defect is still present and is now byte-
  identical to `origin/develop`: `_ScheduleRunner.run` still calls
  `backfill_canonical_definitions()` unconditionally on startup
  (`services/scheduler.py:451`), and `_backfill_one`
  (`services/scheduler.py:420`) puts a Hive-row-derived definition over the
  canonical row whenever `_definition_drifted` disagrees — including
  `enabled`, `name`, `cron`, `timezone`, `workspace_id`, `project_id`
  (`services/scheduler.py:407-418`) — with no tombstone awareness
  (`services/scheduler.py:442` put), while the routes still commit the
  canonical write before the Hive projection (`routes/schedules.py:214`,
  delete canonical at `routes/schedules.py:425` then projection). A crash
  between those writes is still "repaired" at next startup by the stale
  projection overwriting or resurrecting canonical state.
- the strict-#459 scenario token `REAL_SCENARIO_EVIDENCE: schedule-conductor`
  is still produced nowhere outside the parity harness
  (`tests/cross_product_parity/harness.py:245`), so
  `REAL_SCHEDULE_CONDUCTOR_SCENARIO` (`harness.py:233`) remains a
  permanently-evidenced blocker for the real app-lifespan /
  crash-between-writes criterion.
- the reopened #1199/#2467 repair heads (1326ca7eb4 "repair the Hive
  projection from canonical authority", c486fc806f "run the
  projection-authority scenarios against the production PgScheduleStore")
  remain NOT ancestors of this branch or of `origin/develop` — the repair
  itself has not landed anywhere reachable from this lane.

No suite count moves from this round's own delta (the merged tree's counts
are develop's own, confirmed by the 21-suite inventory gate), so no
`inventory-delta` is recorded for this addendum either.

## SAST/Gitleaks repair at 83fb36e049 (2026-11-22)

CI at this head failed `SAST / Gitleaks` (the `sast` aggregate job red via
`check_ci_job_results`). First-party reproduction with the CI-exact range
(`gitleaks git --log-opts="9c02cfd7..83fb36e049"`, gitleaks 8.30.1) found
exactly one leak: `generic-api-key` at line 261 of
`docs/adr/ADR-101826-c3f1-webauthn-verification-adapter-py-webauthn.md`,
introduced to this branch's scan range by the develop-sync overlay commit
e14ea64f3e.

Root cause: the file's blob is byte-identical to `origin/develop`
(f3587e1829). The existing `.gitleaksignore` entry covers the fixture at
line 258 of the *older* blob (introduced by rebuild commit 2a46c7e008), but
PR #2268's review round re-recorded the ceremony against webauthn==3.0.1,
lengthened the JSON fixture line, and moved the detection to line 261 of
blob f3587e1829 — a fingerprint (`465d8fd8fd8e:...:generic-api-key:261`, the
#2268 squash on develop) that no ignore entry covered. The overlay commit
then carried that blob into this branch's range, where gitleaks scans each
commit's own patch, so the range scan saw it as a fresh introduction.

Fix (`.gitleaksignore` only, same specimen rationale as the existing #1837
block): two commit-scoped fingerprints for the new line — develop's own
introducer `465d8fd8fd8e:...:261` (keeps post-merge full-history scans green)
and this branch's range introducer `e14ea64f3e...:...:261`. The comment
block is updated and paraphrased so it cannot trip the rule itself (the
auto-115 self-trip precedent).

Proof, first-party at the post-fix tree:

- CI-exact range scan `9c02cfd7..83fb36e049`: `no leaks found` (was 1);
- full-history `--all`: findings drop 10 → 8 with both ADR-101826 rows gone;
  the 8 remaining are unreachable from this branch's scan range — 7 belong
  to local worktree branches outside both `origin/develop` and this branch
  (including stale-SHA rebuild artifacts), and 1 (`de8266eff9a8`,
  `test_goal_reconciliation.py:835`) is a pre-existing develop-history
  finding that no range scan of this branch can see, reported here for the
  develop lane rather than silently ignored in this one;
- the vulture gate with CI-exact args: 1221 reviewed identities, all banked,
  0 unbanked — no ledger amendment needed this round;
- `ruff check` / `ruff format --check` clean, `check-suite-inventory.py` ok
  (21 suites), `check-doc-links.py` ok.

Acceptance re-validation at the post-fix tree, first-party (dedicated
pgvector:pgvector:pg18 container, `alembic upgrade head` to 068, DSN on
127.0.0.1:16432):

- `packages/maistro-core/tests/scheduling/` 327 passed, 0 skipped (was 327
  at 86adf48103; 289 passed / 38 PG-leg skips without the DSN);
- the hive-conductor scheduler/definition/scope/manual-fire suites 204
  passed, 0 skipped — identical to the 86adf48103 numbers, confirming the
  base merge (9c02cfd7) moved no scheduling behavior.

No suite count moves (config/docs-only delta), so no `inventory-delta` is
recorded for this repair either.

## Develop-sync completion and re-validation at 939363f33c (2026-11-22)

The salvage round for this lane found the previous attempt's `origin/develop`
sync left mid-resolution: an in-progress merge of 433a9660bc (develop's "M1-B6
— Make every schedule firing create a canonical Run (#2478)") with one
unmerged path, `issue-1199-canonical-scheduler.md` — both branches had
appended independent evidence sections at the same spot. This round completed
the sync as the lane brief directs:

- merge ce150065cd resolved the note conflict by keeping both sides (this
  branch's sections first, develop's second, leaving the file tail identical
  to develop so future appends merge cleanly) and took develop's
  `.gitleaksignore` #2268/overlay webauthn fingerprints verbatim;
- merge 939363f33c then brought origin/develop e0fd6f9f98 (the two
  uv.lock-only dep bumps regex #2481 and pylint #2480 on top of 433a9660bc);
  `uv sync --locked --extra dev` rebuilt the environment (regex
  2026.9.29 → 2026.11.19);
- 433a9660bc carries no production or test code (`.gitleaksignore` + this
  note only) and the two dep bumps touch `uv.lock` only, so the branch's
  scheduling behavior is unchanged from the previously validated head
  8dbce87911 — the post-merge delta vs origin/develop is exactly the lane's
  projection-authority work, its tests, migration 069, and evidence notes.

First-party re-validation at 939363f33c (dedicated pgvector:pg18 container
`auto-1199-pg`, DSN on 127.0.0.1:19432, `DATABASE_URL` pointed at the scratch
database and `uv run alembic upgrade head` applied the full chain to 069,
including this branch's 069_schedule_deletions):

- `uv run ruff check .`: all checks passed; `uv run ruff format --check .`:
  3630 files already formatted.
- `uv run mypy` over the seven documented package srcs: no issues in 960
  source files.
- `scripts/check-suite-inventory.py`: ok, 21 suites match the recorded
  inventory; `scripts/check-test-duplicates.py`: ok;
  `scripts/check-doc-links.py`: ok; `scripts/check-backlog-consistency.py`:
  ok; `scripts/check-durable-table-inventory.py`: ok (125 tables).
- vulture with CI-exact arguments (`packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`): exit 0, 1221 reviewed identities banked
  (base e0fd6f9f98, candidate 939363f33c).
- Core scheduling with the PostgreSQL legs live:
  `packages/maistro-core/tests/scheduling/` 327 passed, 0 skipped (10.6s).
- Hive-conductor scheduler/definition/scope/manual-fire plus both
  projection-authority suites (test_scheduler.py, test_scheduler_bounded_tick.py,
  test_scheduler_canonical_admission.py, test_scheduler_canonical_due.py,
  test_schedule_canonical_definitions.py, test_schedule_frequency_floor.py,
  test_schedule_manual_fire_canonical.py, test_manual_fire_canonical.py,
  test_schedule_workspace_scope.py, test_schedule_projection_authority.py,
  test_scheduler_projection_authority.py) with the same live DSN: 290 passed,
  1 skipped (62.5s) — the skip is the by-design memory leg of
  `test_independent_processes_racing_startup_converge_on_canonical_truth`
  (two processes need durable state to share; the sqlite and postgres legs
  pass).
- Named acceptance tests re-run explicitly: restart and occurrence-claim
  (`test_restart_executes_the_queued_run_once`,
  `test_restart_after_a_cursor_crash_keeps_the_same_run`,
  `test_two_live_runners_claim_one_occurrence`,
  `test_hive_row_cannot_force_a_schedule_that_is_not_due`) 4 passed;
  `test_independent_processes_racing_startup_converge_on_canonical_truth`
  and `test_restart_retains_a_canonical_edit_and_repairs_the_stale_row` 5
  passed / 1 by-design skip across backends.
- `tests/cross_product_parity/`: 26 passed (strict-#459 closeout scenario
  evidence intact at the merged head).

No suite count moves (merge is docs/config/lock only), so no
`inventory-delta` is recorded for this addendum.

