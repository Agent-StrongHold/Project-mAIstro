# L337 round 10 — develop sync to `41deb105c` + re-proof of every red gate from the last merge-queue evaluation (2026-10-26)

Head entering: `83a03d3c6` (round-9 handoff + the a4b820e14 unused-wiring
removal). Head leaving: this commit. New develop base: `41deb105c`
(prompts-diff CONNECT + ledger prunes, the lane's stated base).

## What this round did

**Develop sync.** Merged `origin/develop` (`41deb105c`: factory soul-upsert
prompt-diff CONNECT, vulture/reachability debt prunes, workflow-inventory
refresh). Auto-resolved clean — zero conflicts; the commit touches
`maistro-core/agents/factory.py` and quality ledgers, none of the #337
hive surface. `git log HEAD..origin/develop` is empty afterwards.
Ledger-safety check per repo convention: `git diff --numstat origin/develop
-- quality/` → **empty** (no rows silently lost; vulture multiset never
passed through `set()`).

**Hygiene.** The untracked `actionlint` binary a prior round downloaded to
reproduce the workflow-lint gate was added to `.gitignore` (same class of
reproduction-tool noise as round 9's trivy `.cache/`). Nothing deleted.

## Gates re-proven at the merge head — every red job from the last merge-queue evaluation

CI at `83a03d3c` showed five non-cancelled failures plus a wave of
cancelled downstream jobs. Each is addressed with its CI-exact command:

| Red CI job | Local command (CI-exact args) | Result |
|---|---|---|
| Quality gate (Pillars 1–4, 7, 8) / vulture ledger | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **exit 0** — 1255 reviewed identities → 1255 findings; **no ledger amendment needed or made** |
| Quality / Workflow inventory | `uv run python scripts/check-workflow-inventory.py` | **clean** (32 workflows dispositioned) |
| Quality / Release consistency | `uv run python scripts/check-release-consistency.py` | **ok** |
| workflow-lint | `./actionlint -no-color -oneline`; `scripts/check-install-functions.py`; `node --test tests/ci/integration-scope.test.cjs`; `scripts/check-required-checks.py` | **all exit 0** (77 PR checks match REQUIRED-CHECKS.md; integration-scope 0 failed) |
| SAST (bandit + semgrep + gitleaks) | bandit step from `security.yml:62-80` verbatim | **bandit Medium+ count: 0 (strict gate)** |

Further quality pillars at this head: radon (127→127), reachability
(103 unreachable, dispositions OK 82/20/1), workspace-retirement (89
entries match), security-inventory (61 paths resolve), backlog
consistency (167 items OK) — all exit 0.

The hosted-only jobs (Gate C clean install; the cancelled wave) were
cancelled by queue starvation, not by this tree: their logs show
"The operation was canceled" with no check output, the lane cannot push,
and develop's own `41deb105c` commit message records "ci: retrigger
CONNECT checks after Actions queue starvation" for the same window.

## Issue #337 acceptance — re-verified against reachable behavior at this head

- **Durable owners wired (AC-1):** `foundation.py:133-170` initializes
  stores, fills `stores.dag_runs` from SQLite *before*
  `configure_dag_run_store`, then wires durable metrics
  (`node_metrics_store.configure_store`), settings, profiles, and
  registration onto the same `PersistedStore`/`State` spine.
- **Canonical identity correlation (AC-2):** `NodeObservation` carries
  `run_id`/`node_run_id`/`attempt_id`/`workspace_id`
  (node_metrics_store.py:54-77); attempt id is the idempotency key.
- **Restart + multi-replica (AC-3):** restart/replica-keyed tests →
  **34 passed, 4 skipped** (skips are the `MAISTRO_TEST_PG_DSN` PG leg,
  produced by the hosted PG-gated job).
- **No unused setter/wiring (AC-4):** sole production
  `feedback_service.set_outcome_store` caller is
  `engine._wire_outcome_store` (engine.py:266-291, wired in `start()` at
  engine.py:376-377 with the #1181 unwind); the dead
  `feedback_service.record_outcome` duplicate was removed at `a4b820e14`;
  the only remaining production `record_outcome` is the #1036 terminality
  owner (`dag_run_store.py:473`).
- **Retention/scope/pagination explicit (AC-5):** `/v1/dag-metrics/retention`
  states the bound and eviction-not-delete
  (routes/metrics.py:57-75); principal scoping via `require_actor_id` +
  `authorized_workspace_ids`; `window_seconds` and `limit` clamped
  (metrics.py:97-105).
- **Migration/parity tests precede retirement (AC-6):**
  `docs/testing/inventory-notes/issue-337-durable-dag-state.md` (delta +13)
  and `auto-337-a36c.md` carry the front-matter blocks; suite inventory
  **ok: 21 suite(s) match the recorded inventory** (34806 unique
  identities, 0 duplicates).

Full #337 acceptance battery at this merge head:
`test_durable_node_metrics` + `test_feedback_route` +
`test_goal_inspection` + `test_node_metrics` +
`test_dag_run_history_durability` + `test_dag_run_scope` +
`test_profile_durability` + `test_thumbs_read_through_the_protocol` →
**263 passed**. Generated-API-types gate (ci.yml:692-695 verbatim):
dump-hive-openapi + gen:api → `git diff --exit-code` on `types.gen.ts`
**clean**. `ruff check .` / `ruff format --check .` → clean (3537 files).

## Residual

- Hosted CI remains unobserved from this lane (no-push). Every step that
  failed in the last observed run is fixed in-tree and re-proven above
  with CI's exact commands; the cancelled jobs have no check output to
  repair.
- The 4 skipped restart/replica nodes need live Postgres; their producer
  is the hosted PG-gated job.
