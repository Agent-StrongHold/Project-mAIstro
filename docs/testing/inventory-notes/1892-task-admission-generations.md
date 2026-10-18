---
inventory-delta:
  tests/: +14
---

Issue #1892 (M1, parent #1845) adds the forward admission-generation
representation on `task_idempotency` — alembic revision
`054_task_admission_generations` (numbered `053` when written; develop then
claimed `053` for its learning-lifecycle columns, so per the chain's
documented collision convention the revision re-parented onto
`053_learning_lifecycle_columns` as `054`), a schema-only leaf on the
L41/#1325 integration line. No writer is activated; nothing here claims mixed old/new
writers are safe.

`tests/migrations/test_task_admission_generation_upgrade.py` (+14) runs the
migration against the live PostgreSQL catalog on a disposable database (same
`MAISTRO_TEST_DATABASE_URL` gating as `test_migration_chain.py`; skipped
without a server, so CI's postgres legs own the coverage). It covers:

- the upgrade contract: shipped-038 rows preserved byte-for-byte in their old
  columns with `format_version` defaulting to 1; the known #1325 L41 shape
  (`claim_token` NOT NULL, defaulted `completed_at`) reached through a real
  chain history and retained as found; stamp-back + re-upgrade over an
  already-applied, populated v2 shape adopted unchanged; the exact contracted
  column set on a fresh chain (and no `completed_at`, which v2 does not need).
- refusal paths: a wrong-typed baseline column, a missing primary key, and a
  lost expiry index each stop the upgrade before any forward DDL with the
  stamp unmoved; a runtime-provisioned table with PRE-038 history is blocked
  by shipped 038 before this revision can run.
- the v2 CHECK: NULL injected into each of the ten nullable-but-required v2
  fields independently (PostgreSQL CHECK passes UNKNOWN, so each needs its own
  explicit `IS NOT NULL`); bad-hex/nil identities, blank ids/action, half-bound
  or mis-bound task/run pairs, acknowledgement on an unbound row, and
  non-positive windows all rejected; a complete generation (unbound, then
  bound-to-own-receipt and acknowledged) admitted; format-v1 rows unconstrained.
- downgrade: refuses before any change while a non-legacy row exists (stamp,
  columns and row all survive the failed attempt); with legacy-only data it
  drops exactly the v2 columns and the CHECK, retains the optional legacy
  `claim_token`, preserves every row, and the resulting safe-downgrade shape
  re-upgrades cleanly.

One existing test moves with the chain tip, per that sentinel's own documented
convention: `test_capability_invocation_effect_index_migration.py`
`test_effect_index_migration_follows_the_chain_tip` now walks to and pins head
`054` (was develop's `053`) — same count, updated identity, no delta.

Focused run (issue #1892):
`uv run pytest tests/migrations/test_task_admission_generation_upgrade.py
tests/migrations/test_migration_chain.py::TestTheChainApplies::test_reapplying_the_chain_over_an_already_migrated_schema_is_adopted
tests/migrations/test_migration_chain.py::TestTheChainApplies::test_the_chain_round_trips -q`
— 16 passed; the full `tests/migrations` package passes with the sentinel
update; head re-stamped to `053` afterwards since the round-trip test ends at
base.

Repair at this lane (CI `coverage (PostgreSQL)` gate): the migration's raw
`ALTER TABLE ... ADD/DROP COLUMN` f-strings interpolated loop-bound names the
retention-inventory scan (`check-durable-table-inventory`, enforced by
`test_retention_reference_inventory.py`) must resolve statically and so
refused — `test_every_run_id_table_is_in_the_purge_inventory` and
`test_scan_sees_the_known_reference_shapes` failed. Fixed by moving the
dynamic column work to the scan-supported `op.add_column` / `op.drop_column`
idiom (same DDL: TEXT/SMALLINT/BIGINT, `format_version DEFAULT 1`) and
keeping `_FORWARD_COLUMNS` an unannotated module tuple so loop-bound names
stay statically resolvable. No test added or removed — delta above unchanged.
Re-validated on a fresh PostgreSQL database: `tests/migrations` 117 passed;
CI's coverage-postgres step 2 suites 5077 passed, 8 skipped; canvas leg 516
passed, 3 skipped; `scripts/check-durable-table-inventory.py` ok (89 durable
tables); vulture ledger 1340/1340 with CI's exact arguments.

Repair at this lane (develop sync): agreed integration base
`origin/develop` = `8a4bc239fe9af429be9faa087916f965e9fb20f7`, merged via
`35f2e0158` (feece6c63) then `88be7e33c`; the merge reintroduced the
revision-id collision — develop's
`053_learning_lifecycle_columns` and this branch's admission-generation
revision both claimed `053` on `052`. Resolved per the migration's own
documented convention (whichever revision lands second re-parents onto the
merged tip): the branch revision re-parented onto develop's tip as
`054_task_admission_generations`; the chain sentinel walks to head `054`. The
refusal-path stamp assertions hold unchanged: the upgrade run is one
transaction, so a refusing 054 rolls develop's 053 back with it (stamp stays
`052`), and a refused downgrade leaves the stamp at head `054`. No test added
or removed — delta above unchanged.

Repair at this lane (develop sync, M4-B3 collision, second landing): the next
develop sync (`9a5eb7ba6`/`30677b185`) collided the head again, with the
sides flipped — this branch now holds `054_learning_applicability_epistemics`
(#119) on parent `053`, so this revision — landing second for the second
time — re-parents onto that applicability tip as
`055_task_admission_generations` (`down_revision = "054"`). The chain
sentinel (`test_effect_index_migration_follows_the_chain_tip`) walks to head
`055`; the refusal-path stamp assertions hold unchanged: the upgrade run is
one transaction, so a refusing 055 rolls 053 and 054 back with it (stamp
stays `052`), and a refused downgrade leaves the stamp at head `055`. No
test added or removed — delta above unchanged.

Repair at this lane (develop sync, third landing, #1047 re-parents past the tip):
the next develop sync (`cd5618223`) brought develop's
`054_learning_applicability_epistemics` (#119) plus the admission tip renumbered
to `055_task_admission_generations`, colliding with this branch's
`055_user_model_facts` (#1047) on the same parent. Per the chain's collision
convention the #1047 revision — landing third — re-parents onto the admission
tip as `056_user_model_facts` (`down_revision = "055"`). The chain sentinel
walks to head `056`; the refusal-path stamp assertions hold unchanged: the
upgrade run is one transaction, so a refusing 055 rolls 053 and 054 back with
it (stamp stays `052`), and a refused downgrade leaves the stamp at head `056`
(the previously head-pinned assertion tracks the new tip). No test added or
removed — delta above unchanged.

Update (auto-1572 develop sync, Goal-store collision): the Goal-store lane
(#1572) had independently landed `056_canonical_goals` on the same quota door,
so the merged tree renumbers this revision — the later-integrated one — onto
that landed tip as `057_user_model_facts` (`down_revision = "056"`). The
same sync lands #863's planner-stability revision, which on develop had
re-parented onto the user-model tip as `057` — colliding with the
renumbered `057_user_model_facts` — so it renumbers again onto that tip
as `058_run_store_planner_stability`. The chain sentinel walks to head
`058`; the head-tracking stamp assertions follow it. No test added or
removed — delta above unchanged.

Repair at this lane (develop sync, #102 backlog pair, third landing): the
auto-102 sync that merged `origin/develop` `b672b799a` re-parented the
backlog work-source/authority-cutover pair (#98/#102) after this revision's
chain — the quota door `043_invocation_quota_door` (parent `055`) is the
merged tip, and the backlog pair attached after it as `056` and `057`. The
revision itself is untouched (`055`, parent `054`).

Repair at this lane (develop sync, fourth landing, #1047 lands on the tip): the
next develop sync (`c560d4cca`) landed #1047's user-model tables on develop's
trunk as `056_user_model_facts` on the same quota-door parent as the backlog
pair. per the chain's convention — a landed trunk migration never moves; the
branch-side pair re-parents onto the incoming develop tip — the backlog
work-source/authority-cutover pair renumbers to `058_backlog_work_source` and
`059_backlog_authority_cutover`, with develop's #863 planner-stability
revision landing between them as `057_run_store_planner_stability`. The chain
sentinel now walks to head `059`, and the refused-downgrade stamp assertion
pins that head by the same head-artifact reasoning as the rounds above. No
test added or removed — delta above unchanged.

Repair at this lane (develop sync, fifth landing, the Gauntlet provenance
ledger takes `058`): the next develop sync (`11376c7bef`) landed #118's
M4-B2 Gauntlet validation provenance on develop's trunk as
`058_learning_validation_provenance` (parent `057`), colliding with this
branch's `058_backlog_work_source` on the same parent. Per the chain's
convention — a landed trunk migration never moves; the branch-side pair
re-parents onto the incoming develop tip — the backlog pair renumbers to
`059_backlog_work_source` and `060_backlog_authority_cutover`. The chain
sentinel now walks to head `060` (asserting `056`/`057`/`058`/`059`/`060`),
and the refused-downgrade stamp assertion — previously head-pinned — reads
the head dynamically (`_chain_head()`) from the same version files the
upgrade ran, so this and future collisions cannot stale-pin it. No test
added or removed — delta above unchanged.

Correction (auto-1572 salvage): the Goal-first renumbering above describes
an abandoned draft, not supported migration history. User-model `056` and
planner `057` retain their shipped identities. The incoming backlog pair
retains `059`/`060`; unmerged Goals append as candidate `061` (central
reservation still requires confirmation). Downgrade refusal continues to
assert the pre-downgrade stamp, not a hard-coded tip. Test count unchanged.
