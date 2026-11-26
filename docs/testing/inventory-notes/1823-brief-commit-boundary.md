---
inventory-delta:
  packages/hive-conductor/backend/tests: +34
  packages/maistro-core/tests: +3
---
# 1823-brief-commit-boundary

The brief interview's commit turn no longer stops at a draft (#1823):
`services.brief_commit` is the one authorized boundary that turns a confirmed
interview into one canonical Goal revision plus one CreativeBrief version,
under a durable commit record that replays, concurrent tabs and process death
all resume into the same logical commit.

`packages/hive-conductor/backend/tests/test_brief_commit.py` holds the
boundary itself (26 async boundary tests plus 3 unit tests = 29 collected):
one test per acceptance criterion group — commit shape and provenance
read-back, restart read-back over re-opened PostgreSQL pools,
unconfirmed/incomplete refusal, replay and concurrent-confirmation
idempotency, forced process deaths before/between the writes resumed from the
durable record, non-owner refusal, foreign-goal revision refusal, the
cross-Workspace refusal when a principal administering two Workspaces aims
``revises`` at another Workspace's Goal or lineage, canonical
enumeration after restart, Goal-revision vs creative-only revision paths,
and the explicit recoverable limitation. A caught, reported failure is the
principal's to retry: two tests pin that the startup recovery sweep never
auto-drives a ``failed`` record (so a draft cancelled or replaced after a
failure is not committed by a restart), while the failure's own
re-confirmation resumes the recorded identities and adopts the stranded
brief. These run against the real supported durable stores — `PgGoalStore`
and `PgCreativeBriefStore` over one PostgreSQL server migrated by the real
alembic chain, through the same skip contract (`MAISTRO_TEST_DATABASE_URL` /
`MAISTRO_REQUIRE_PG_LEGS`) the maistro-design brief-store suite uses; the
three unit tests run anywhere.

`test_chat_brief_interview.py` grows the shipped chat-path commit tests (+5
net after the drafted-turn test became the pre-confirmation test): a
confirmed turn commits and enumerates through the product's Goal inspection
route, cancel writes nothing while the next model turn still admits a Run,
a replayed confirmation after a lost response returns the same ids, a
non-owner confirmation is refused without writing, and an unavailable store
answers the honest retryable copy with the interview kept open.

`packages/maistro-core/tests/goals/test_scoped_goal_identity.py` (+3) pins
the one core-seam change: `ScopedGoalStore.create_goal` now passes a
caller-chosen `goal_id` through (identity selection for the crash-safe
protocol), and the tests hold that the ADMINISTER decision still gates it.
