# L337 round 9 — develop sync to `b1c89cdbc` + full re-proof at the merge head (2026-10-24)

Head entering: `d07cae8bc` (round-8 handoff). Head leaving: this commit. New develop base: `b1c89cdbc` (the lane's stated base, 2 commits past round-7's `db4d3eb09`).

## What this round did

**Develop sync.** Merged `origin/develop` (`b1c89cdbc`: #2284 Workspace Attention
shell + #2308 durable Workspace landing/restore preferences) into `auto-337`.
The merge auto-resolved clean — zero conflicts — despite develop touching
`services/profile_store.py` and `routes/profile.py` adjacent to #337's durable
profile store: develop's `workspace_preferences.py` rides the same
`PersistedProfileRecordStore` wiring #337 landed, it does not bypass it
(`test_profile_durability.py` green post-merge, below). Branch now contains
`origin/develop` fully (`git log HEAD..origin/develop` is empty).

**Hygiene.** `.cache/` (a trivy scanner DB left by round-3's Container-scan
reproduction) was untracked and noise in `git status`; added to `.gitignore`
alongside the existing `.pytest_cache/` entry. Nothing was deleted.

## Re-proofs executed at this merge head

- `uv run ruff check .` / `uv run ruff format --check .` → clean.
- Driver battery + develop's new suites (`test_durable_node_metrics`,
  `test_feedback_route`, `test_goal_inspection`, `test_node_metrics`,
  `test_workspace_landing_preference`, `test_attention_projection`) → **137 passed**.
- #337 acceptance surface (dag-run history durability, durable node metrics,
  feedback route, profile durability, dag-run scope/store, settings durability,
  node-metrics-are-measured, thumbs protocol) → **287 passed**.
- **Full hive backend suite → 4020 passed, 25 skipped.** First run had a single
  one-time failure: `test_registration_policy.py::TestInvitations::
  test_concurrent_open_registration_claims_username_once` — a pre-existing
  (not touched by develop or this branch) thread-concurrency test that passed
  on immediate rerun in isolation (1 passed, 1.71s) and in the second full run.
  Same documented-transient class as round 6's `test_restore_oracle_
  characterization`; not a merge regression.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/hive-conductor/backend/tests` → **ok at 4045** (develop's 12 new
  identities arrived with their own inventory notes `1049-*`/`1050-*`; the
  recorded baseline already includes them — no delta note needed from this
  round, which adds no tests).
- Named red gate from CI job 120834925096, with CI's exact commands
  (`ci.yml:689-691`): `uv run python scripts/dump-hive-openapi.py` (241 paths /
  147 schemas) → `npm --prefix packages/hive-conductor/frontend run gen:api` →
  `git diff --exit-code -- .../types.gen.ts` → **CLEAN, zero diff**.

## Acceptance criteria status (unchanged in substance, re-verified post-merge)

- Durable owners wired: `foundation.py` builds the run store only after
  `initialize_stores()` fills `stores.dag_runs` from SQLite, then
  `configure_dag_run_store` (foundation.py:127-133); durable metrics
  projection, persisted profiles/settings/registration all on the same spine.
- Feedback ↔ canonical identity: `routes/feedback.py::_execution_identity`
  (404 foreign/missing run/node, 409 projection-only, 503 spine down), applied
  to every accepted thumb (feedback.py:179).
- `set_outcome_store` production caller: `engine.py:301` inside
  `_wire_outcome_store`, with `_reset_outcome_store_binding` unwind
  (engine.py:304-315, wired at engine.py:387-388).
- Retention/scope/pagination explicit: `/v1/dag-runs` + `/v1/dag-metrics/retention`,
  `require_actor_id` principal scoping, clamped `limit=max(1, min(limit, 1000))`
  (routes/metrics.py:97-105), eviction-not-ad-hoc-delete documented at
  metrics.py:56 and pinned by `test_the_retention_endpoint_states_the_bound`,
  `test_an_evicted_run_leaves_the_records_too`, `test_records_beyond_the_bound_
  are_deleted_on_load`.
- Restart + multi-replica: `test_a_run_and_its_events_come_back_after_a_restart`,
  `test_a_reload_sees_a_write_made_by_another_replica`,
  `test_metrics_survive_restart_and_refresh_an_existing_replica` — green in the
  287-test battery.

## Residual

- Hosted CI remains unobserved at any auto-337 head (no-push lane). Every step
  that failed in the last observed run is fixed in-tree and re-proven locally
  with CI's exact commands (round 8 forensics; types gate re-proven this round).
- The one-time full-suite transients (round 6 restore-oracle; round 9
  registration-concurrency) are green on identical-tree reruns and in
  isolation; neither reproduces deterministically, so no code change is
  justified from them.
