---
inventory-delta:
  packages/maistro-core/tests: +18
---
# Recovery claim activation-window proof (#837)

The original two-recovery-store harness test failed intermittently on unchanged
`ab8b3737` source: four of 60 isolated coverage processes, and three of 40
unmodified test processes without the diagnostic plugin. This repair targets
that shared-core race independently of the six-file Hive convergence PR #1991.
It follows the RUNNING-only guard from #2092, without claiming the separate
empty-frontier or long-running walker work in #1626, #1373, or #1861.

## Deterministic regressions and inventory

`test_harness_timer_recovery.py` adds 18 collected cases:

- Three forced contender windows times three stores: stale due listing after
  the owner's claim, a contender already past its initial guard, and a claim
  whose canonical Run was reactivated before its next continuation checkpoint
  (+9). The owner is held by events, not timing sleeps. The contender must
  neither reconcile Attempts nor mutate the persisted record; exactly one
  provider dispatch and poll complete. Historical tick time proves the
  projection mirror cannot reinterpret ownership with a different wall clock.
- An ordinary future timer whose deadline equals the previous claim's deadline
  remains directly resumable after re-parking clears the marker (+3).
- Process-loss simulation before and after canonical reactivation, followed by
  expiry takeover, adopts the same remote handle without redispatch (+6).

The first two windows failed against unchanged production in both executable
local backends. The third failed until the projection mirror guard was added.
Independent review then reproduced a historical-clock failure, fixed by making
that mirror decision depend on claim identity rather than expiry.

Existing tests are strengthened without changing their collection counts:
`test_resume_refuses_a_demonstrably_live_attempt` proves refusal writes nothing;
`test_retry_adopts_node_run_created_before_checkpoint_failure` proves a failed
checkpoint cannot justify immediate theft of a live claim, then adopts the
same canonical NodeRun once the claim expires.

## Scope and evidence limits

PostgreSQL parametrizations use the existing migrated canonical PgRunStore,
PgGraphContinuationStore, and persisted invocation collaborators. They run in
`quality.yml`'s existing coverage (PostgreSQL) producer after migration, with
`MAISTRO_REQUIRE_PG_LEGS=1`. This environment has no PostgreSQL DSN or server;
local PostgreSQL skips are not acceptance proof. Hosted exact-head PG execution
is required before readiness. SQLite cases are the existing race harness, not
an expansion of supported canonical storage. Reconstructed stores and simulated
process loss do not prove an OS-process-kill or distributed deployment test.

The marker uses existing Graph continuation metadata, so no schema or backend
policy changes. Historical unmarked WAITING rows are intentionally still
ordinary timers: their original format cannot distinguish an old writer's
claim from a park. Existing unmarked RUNNING claim protection stays intact.
