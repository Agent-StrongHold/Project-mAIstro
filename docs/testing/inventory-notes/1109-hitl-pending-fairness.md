---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +32
---
# 1109-hitl-pending-fairness

Issue #1109: pending HITL discovery must be fair instead of filtering after a
bounded PAUSED prefix. The fix is the pause-kind projection the issue asks for
by preference — `has_hitl_pause` on `GraphContinuation`, maintained on every
write beside the #1056 deadline projection, queried through
`DurableRunStore.list_hitl_paused` on all three backends (in-memory, SQLite,
PostgreSQL, the latter via migration 059) — plus one canonical bounded walk,
`pending_hitl_records`, that both consumers of pending discovery share: the
`/v1/hitl/pending` route and the Workspace Attention projection
(`services/attention.py`), which had duplicated the old filter-after-prefix
walk and now walks the projection with it.

## packages/maistro-core/tests: +29

`tests/graph/durable_runs/test_hitl_paused_index.py` is new: 29 collected node
IDs across the three-backend continuation fixture (projection claims only
PAUSED human rows, includes deadline-less pauses, pages on the created cursor,
filters by project), the canonical store (real executor-produced pause
discoverable, answered work leaves the projection, a stale projected row is
never disclosed, scope filters bind before disclosure, a zero limit answers
before the projection is read at all, and a machine-only
PAUSED prefix longer than the limit cannot occupy the page — the mutation test
for `list_by_status(PAUSED, limit=N)` + in-memory filtering), the standalone
stores (same contract, plus SQLite reopen/backfill restart safety), and the
canonical walk itself (items-not-records bounding, multi-pause runs counting
per item, the membership recheck as the disclosure decision, Workspace-wide
vs named-Project scope, and the inspection ceiling).

## packages/hive-conductor/backend/tests: +3

`test_hitl_door.py` gains the HTTP-boundary regressions: a HITL pause behind a
machine-only prefix longer than the request inspection ceiling is still
returned (the ceiling must not become the starvation one size up), repeated
requests keep returning the same pending work (no consumed scan position, so
restart cannot make an item unreachable), and multiple human pauses on one Run
are returned individually and count individually against `limit`. The existing
two human pauses behind a `limit`-sized machine prefix and the offset-cursor
regressions keep pinning the request-scoped paging contract; the ceiling test
was rewritten to pin the bound that remains (a request stops) rather than the
starvation the projection removed.

Verified against a real PostgreSQL 18 server (`MAISTRO_TEST_PG_DSN`, migration
059 applied, and the 058 → 059 backfill exercised by planting a pre-059 row
and upgrading): the PostgreSQL parametrizations of the new suite pass, and
`packages/maistro-core/tests/graph/durable_runs` +
`packages/maistro-core/tests/runs` are green with the PG legs enabled
(2067 passed, 3 skipped).

## CI-repair round: adoption-safe DDL for migration 059

The first CI evaluation of this branch failed `postgres (pg17/pg18)`,
`coverage (PostgreSQL)`, `test`, and (by aggregation) `integration-scope` on
one root cause: 059's bare `ADD COLUMN`/`CREATE INDEX` assumed a fresh
database, so the chain re-application path (`stamp` to 039's parent, then
`upgrade head` — the repair walk `test_migration_chain.py` pins) died on
`DuplicateColumn: column "has_hitl_pause" ... already exists`, and the root
suite's chain-tip pin still named `058`. The repair makes 059's DDL guarded
(`ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`, the contract 045
states for the chain; the backfill re-runs safely because it recomputes the
projection from canonical pause entries with the runtime's own policy) and
re-points the tip pin to `059`. No test was added or removed: the delta above
is unchanged, and the regression evidence is the pre-existing chain-level
adoption test, which failed before the repair and passes after.

Repair verified against a real PostgreSQL 18.6 server: the full `postgres`
job sequence (chain tests, `upgrade head`, `downgrade base` + `upgrade head`,
persistence 809, container_postgres 15, workspaces with
`MAISTRO_REQUIRE_PG_LEGS=1` 328, canvas supported path 7), the full
`tests/migrations` suite under coverage on an unmigrated database (157
passed), and the `coverage (PostgreSQL)` producer's core suites (5610
passed).

## CI-repair round: committed OpenAPI types + the zero-limit guard's evidence

The second CI evaluation (head 374a13a89) failed `test` and the diff-coverage
half of the coverage gate on the implementation's own evidence, not its
behavior. First, the rewritten `/v1/hitl/pending` docstring changed the
endpoint's OpenAPI description, and the generated
`packages/hive-conductor/frontend/src/api/types.gen.ts` was not regenerated —
the `test` job's #1048 step diffs the two. The file is regenerated with the
gate's own commands and committed. Second, the `limit <= 0` guard at
`canonical_store.py:837` in `CanonicalDurableRunStore.list_hitl_paused` was
the one changed line below the per-file 90% floor (83.3% of 6);
`test_zero_limit_costs_zero_projection_reads` covers it and pins the guard's
contract through a counting continuation store: a zero or negative limit
answers before the pause-kind projection is consulted at all (zero reads),
while the same store, asked for work, still returns the planted human pause
(that second assertion is what keeps the empty answer from passing for a
vacuous "nothing pending"). Mutation-checked: removing the guard fails the
test (the projection is read twice).

No delta change beyond +1 to `packages/maistro-core/tests` above. Repair
verified locally at 315e07cb4: `dump-hive-openapi.py` + `gen:api` +
`git diff --exit-code -- types.gen.ts` exits 0 on the committed tree; the
core-graph producer with PostgreSQL legs enabled (1919 passed, 1 skipped) and
the hive-conductor producer (3416 passed, 6 skipped) under coverage feed
`check-diff-coverage.py coverage.xml --base 0df275362d2863d2d541866ffa2f67bb57986898`
to `ok: every measured file this change touches is at or above 90% lines /
80% branch arcs`; `check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` exits 0 with no ledger
amendment (1332 reviewed = 1332 findings); `check-test-duplicates.py` and the
suite-inventory check pass at the new counts.

## CI-repair round: a page that assembles to nothing eligible is progress, not the end

Independent verification of head 4e0eed4b6 found the one starvation the pause-kind
projection alone cannot remove, one layer down: `CanonicalDurableRunStore.list_hitl_paused`
filters each assembled page by Workspace scope (#1240) and projection staleness after the
projection page was cut, and returned a plain list — so a page of 2000 foreign-Workspace
human pauses assembled to `[]`, and `pending_hitl_records` read an empty page as the end of
the projection (`exhausted=True`). A Workspace-wide walk (Attention's exact shape,
`project_id=None`) answered empty forever and called it complete, and the Attention
docstring's claim that a Workspace-wide walk "cannot hide this Workspace's work behind
another tenant's" was false. The repair follows the `scan_due_page` precedent (#1098):
`list_hitl_paused` now returns a `ScanPage` on every backend — the canonical store pages
the projection internally past the rows it drops (bounded by `max_inspected`), reporting
`resume_after`/`inspected`/`exhausted` separately from the eligible items — and the walk
advances by `resume_after`, so an all-foreign page is progress. `exhausted` is now set only
by the projection's real end, so a ceiling stop is reported as capped, never as ran-out.

No delta change from the repair itself; the regression tests add +3 to
`packages/maistro-core/tests` (`test_a_page_of_ineligible_rows_is_progress_not_the_end`,
`test_a_ceiling_stop_is_reported_as_such`,
`test_walk_reaches_the_workspace_behind_a_full_page_of_foreign_pauses` — the last is the
mutation test: against the pre-repair walk it returns an empty, "exhausted" scan) and +1 to
`packages/hive-conductor/backend/tests`
(`test_attention_finds_the_workspace_pause_behind_a_full_page_of_foreign_pauses`, driven
against the canonical store with `MAX_PENDING_SCAN_RECORDS` pulled down to the page size so
the foreign prefix is a full page at Attention's own limit; without the repair Attention
answers empty with `truncated: False`). Existing assertions moved from list shape to
`page.items`; the zero-limit read-count pin went 1 → 2 because the walk's final read is the
one that confirms the projection ran out, which is what makes `exhausted` honest.

## CI-repair round: develop sync renumbers the projection migration 059 → 061

The develop sync for this round (origin/develop 9bd1a93eef) landed the backlog pair
(#98/#102) on the `058` tip this branch's projection migration had taken: develop's trunk
now carries `059_backlog_work_source` and `060_backlog_authority_cutover`, so the tree held
two `059` revisions and two heads, and the chain-tip conformance pin
(`test_capability_invocation_effect_index_migration.py`) conflicted — its branch side
named `059` as the single head, develop's named `060`. The resolution follows the chain's
own convention (046 records it, 058 is the nearest precedent): a landed trunk migration
never moves, so the branch-side projection migration renumbers past the incoming tip —
`alembic/versions/059_hitl_pause_kind_index.py` becomes
`061_hitl_pause_kind_index.py`, `revision = "061"`, `down_revision = "060"` — and the
merged pin walks to `061`, asserts the whole ancestor path through `060`, and pins
`get_heads() == ["061"]` (`alembic heads` reports the single head). No test was added or
removed: the delta above is unchanged, and the evidence is the resolved conformance test
plus `tests/migrations` passing (the DB legs skipped without a live server, as in CI's
unit shards).

## Validation round: develop sync completed, gates proven at the merged head

The develop sync this section describes was completed at b114d7144: the only
conflict was CHANGELOG.md (both sides had added their entry at the top of
`### Fixed`), resolved by keeping both entries; the migration renumber to 061
merged clean and `alembic upgrade head` applied 058 → 059 → 060 → 061 in order
on a live PostgreSQL 18.6 server with `tests/migrations` green against it
(157 passed) and the five PostgreSQL parametrizations of
`test_hitl_paused_index.py` passing (32/32). The mutation claims above were
re-proven from scratch at this head: reintroducing the pre-ScanPage store
shape (one projection read, filter after assembly, no paging past dropped
rows) together with the pre-repair walk semantics (an itemless page reads as
the end of the projection) fails all three regressions named in the previous
section — `test_walk_reaches_the_workspace_behind_a_full_page_of_foreign_pauses`,
`test_a_page_of_ineligible_rows_is_progress_not_the_end`, and
`test_attention_finds_the_workspace_pause_behind_a_full_page_of_foreign_pauses`
— and the restored tree is green again (67 passed across the three suites).
Gates proven at the merged head with CI's exact arguments: ruff check, ruff
format --check, mypy (all ten listed package trees, 1021 files),
check-suite-inventory, check-backlog-consistency, check-release-consistency,
check-merge-markers, verify-monorepo-layout, check-vulture-baseline
`packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (1328
reviewed = 1328 findings, no ledger amendment), the full `packages/maistro-core/tests`
(13968 passed), full `packages/hive-conductor/backend/tests` (3438 passed),
root `tests/` (4578 passed), the one-process trio step (8682 passed),
hive-conductor frontend lint + build, and the #1048 OpenAPI drift check with
`openapi.json` regenerated and `gen:api` re-run for real (types.gen.ts
unchanged). One anomaly, recorded rather than papered over: the first
one-process trio run failed
`test_property_marked_field_is_immediately_locked` once (a Hypothesis
property over an in-process TTL map, untouched by this branch's delta); it
passes standalone, in every pairwise combination, and on a full re-run of the
identical trio command, with no clock-mock leak candidate in the tree —
recorded as a non-reproducing flake, not a repair target.

## CI-repair round: the radon ratchet itself, and the complexity ledger it enforces

Independent verification of head 3c6b563c6 failed the quality gate's radon
ratchet (`scripts/check-radon-baseline.py`) on two new unauthorized C(13)
blocks this branch's own #1109 code had introduced:
`durable_runs/hitl.py:422 pending_hitl_records` and
`durable_runs/canonical_store.py:814 list_hitl_paused`. The gate list in the
previous section silently omitted check-radon-baseline, xenon and
interrogate — the one gate that fails is the one that was not claimed; that
omission is corrected here. A radon grant could not have authorized these:
`scripts/ratchet_provenance.py` loads grants from the merge base (the
two-merge rule), so a branch cannot self-authorize new complexity — the
complexity had to go, not be banked.

The repair is a behavior-preserving extraction following the store's own
`scan_due_page`/`_due_candidate` precedent (#1098): `list_hitl_paused`'
per-row disposition (fetch, cursor advance, PAUSED + human-pause + Workspace
scope) moves to `_hitl_paused_candidate`, which returns the row's keyset
position and its record only when eligible — `None` position for a row
deleted mid-page, exactly like `_due_candidate`; `pending_hitl_records`'
per-page admission loop (live canonical human pause + membership permit,
cumulative item accounting) moves to `_admit_pending_items`, returning the
running item total and the mid-page limit-stop flag. `pending_hitl_records`
drops C(13) → B(9), `list_hitl_paused` C(13) → B(10); helpers A(5)/B(6).
Behavioral order is unchanged on every axis the suite pins: cursor advance
before admission, permit calls once per candidate in page order,
limit-stop breaking before the `exhausted` check.

No test was added or removed: the delta above is unchanged, and
check-suite-inventory still reports all 17 suites at the recorded counts.
Evidence at the merged head (origin/develop feb19affc965 merged clean; only
CHANGELOG.md overlapped and auto-resolved, all `quality/*.json` row-identical
to develop by `git diff --numstat`): `check-radon-baseline.py` exits 0 at
138 current C/D/E/F blocks = 138 baseline entries, no new/regressed/improved/
stale rows and no ledger amendment; xenon with CI's exact arguments
(`--max-absolute B --max-modules B --max-average A -i third_party`, ten
package trees) reports 140 block violations against the 145 floor, 0 module-
rank and 0 project-average violations; `interrogate -f 38` on graph/nodes
(51.3%) and `-f 45` on durable_runs (60.0%) pass; ruff check/format clean;
mypy on packages/maistro-core/src strict-clean (768 files); the full
durable_runs suite 666 passed and the hive attention/door suites 40 passed.
The new helpers are mutation-checked on the tested path: dropping the
Workspace scope clause from `_hitl_paused_candidate` fails 3 tests of
`test_hitl_paused_index.py`; dropping the item-limit return from
`_admit_pending_items` fails `test_walk_bounds_items_not_records`; the
restored tree is green again.

