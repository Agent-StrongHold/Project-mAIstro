# L337 verification round 5 — handoff (2026-10-24)

Head entering and leaving this round: `c70aece24a4c` (develop base
`f956a8142`). No code changes were needed; this round is an independent
re-verification of issue #337's acceptance criteria plus a re-run of every
gate that was red in the last merge-queue evaluation.

## Entering state (previous block re-checked)

Round 4 already resolved the "worker left uncommitted work" block: the round-3
worker died on a provider 402 after its driver checks passed, leaving only an
untracked `.cache/` trivy-scan directory. Round 5 re-confirmed: `git status`
clean at the exact assigned head, `origin/develop` still at `f956a8142`
(fetched; no sync needed), and the driver checks for job
`ea5426bf8fb542b58371ec7d10201e48` all exited 0 (sync, ruff check, ruff
format, 4 durability suites = 113 passed, suite inventory = 3991 hive IDs).

## Independent verification performed this round (fresh runs, not inherited claims)

- Full hive backend suite: `uv run pytest packages/hive-conductor/backend/tests -q`
  → **3966 passed / 25 skipped** in 235s.
- Vulture ledger with CI's exact args
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) → **1302 reviewed == 1302 findings**, base
  read from `f956a8142` (merge base), candidate `c70aece24a4c`.
- OpenAPI types-drift gate with ci.yml's exact commands
  (`scripts/dump-hive-openapi.py`, `npm --prefix
  packages/hive-conductor/frontend run gen:api`,
  `git diff --exit-code -- .../types.gen.ts`) → **exit 0**, working tree
  clean afterwards. This was the actual red step of CI job 120834925096.
- Feedback + outcome-protocol suites
  (`test_thumbs_read_through_the_protocol.py`, `test_feedback_route.py`) →
  **42 passed**, pinning `set_outcome_store`'s production caller and the
  canonical-identity refusals.
- Full suite inventory (all suites): **21/21 match, 34171 unique identities,
  0 duplicate evidence**.

## Issue #337 acceptance criteria -> production evidence at this head

1. *Canonical durable owner per state family, all readers/writers connected* —
   `services/foundation.py:101` `_init_state` wires dag-run history
   (`configure_dag_run_store(stores.dag_runs)`), node metrics
   (`configure_metrics_store(node_metrics)`), profiles
   (`configure_profiles(PersistedProfileRecordStore(persisted))`), settings
   and registration policy onto the persisted State; the feedback outcome
   store is bound in production by `services/engine.py:301`
   (`_wire_outcome_store`), with the stale-binding unwind at :304.
2. *Canonical Run/NodeRun/Attempt correlation* — `routes/feedback.py:107-156`
   resolves the visible canonical identity through the Workspace inspection
   door and returns **409** for a projection-only run
   (`feedback is unavailable for a run without canonical execution identity`).
3. *Restart and multi-instance reads return the same history* —
   `test_durable_node_metrics.py::test_metrics_survive_restart_and_refresh_an_existing_replica`
   (writer + running replica + post-restart store read one observation);
   `test_dag_run_canonical_lifecycle.py:421` reopens the store over the same
   file as a restart read; `test_goal_inspection.py:334` reopens the durable
   canonical event store; `dag_run_inspection._fresh_store()` reloads before
   every HTTP read.
4. *No unused setter implying durability* — `set_outcome_store` has the
   production caller above; `test_thumbs_read_through_the_protocol.py` pins
   the read-through path.
5. *Retention, scope authorization, pagination, deletion explicit* —
   `GET /v1/dag-metrics/retention` (`routes/metrics.py:50`) and
   `retention_bounds()` (`services/dag_run_inspection.py:521`); list clamps
   (`routes/dag_runs.py:59-61` limit<=100, `routes/metrics.py:92-105`
   limit<=1000); scope via `authorized_workspace_ids`/`_in_scope` with
   `test_durable_node_metrics.py::test_workspace_scoped_reads_are_fail_closed`;
   retention eviction pinned by
   `test_metrics_retention_evicts_the_oldest_durable_row`; no ad-hoc deletion
   (canonical Run retention owns execution records).
6. *Migration/parity tests precede retirement* —
   `test_dag_execution_transport_parity.py` plus the durable-store tests
   above; profile cutover is fail-loud (`_warn_if_postgrest_profiles_are_being_left_behind`,
   foundation.py:19-39) rather than silently volatile.

Definition of done: history/metrics survive restart and are replica-visible
(criterion 3 evidence); unsupported state is fail-loud/removed, not silently
volatile (profile PostgREST cutover warning).

## Inventory

No tests were added or removed this round, so no
`docs/testing/inventory-notes` delta is required; the recorded baseline
(34171 identities, 21 suites) still matches.

## Residual risks

- Hosted CI at this head is not yet observed; every previously red gate was
  re-proven against CI's exact commands locally.
- If `origin/develop` advances again, repeat round 4's sync discipline
  (merge, resolve in place, re-run the gate battery).
