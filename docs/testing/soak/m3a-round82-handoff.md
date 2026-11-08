# Issue #860 — round 82 (job d0664643c5824ce1945b8a1f466b176c) independent re-validation at ff28509ad

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head
`ff28509ade698b4ef8feb6457fccd92ed0271541` (working tree clean on arrival,
exactly the dispatch head — HEAD is round 040b7d4d's own commit; that attempt
completed verdict NEEDS-DEEP-REVIEW and its docs-only round-81 handoff is the
sole content delta from the previously validated `14acc692dbee`, re-verified
with `git diff --stat`). No `check-*.log` files exist for this job (driver
`checks` empty per manifest), so the full battery was run directly at HEAD.
The prior attempt at this same head (`c4569c959425`) died on a provider
timeout before any validation ran (`result.json`: `failure_kind:
provider_error`), so this round's execution is the first validation actually
performed at `ff28509ad`. Every gate reproduced its rounds 72–81 result
exactly, including the stale-failure check: the
`test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`
failure recorded in an older job's `check-3.log` (24 ≠ 21 DDL statements)
does not reproduce at this head — the PG set passes 46/46 live.

## Develop drift this round (none)

`git fetch origin develop` at round start: `origin/develop` is still
`bb4257f0960f` — the dispatch base itself. `git diff --numstat bb4257f09 --
quality/` is empty (ledgers identical to the base). The manifest `surfaces`
list (371 files) was programmatically checked against the two-dot branch diff
(376 files): 0 surfaces fall outside the diff and the only extras are exactly
the 5 develop-side files (`packages/maistro-core/src/maistro/runs/pg_store.py`,
`packages/maistro-core/tests/runs/test_pg_root_preparation.py`,
`packages/maistro-core/tests/runs/test_pg_run_insert_connection.py`,
`docs/testing/inventory-notes/1882-pg-root-preparation-seam.md`,
`docs/testing/inventory-notes/1883-pg-run-insert-connection.md`), present
solely because the branch forked at `4aa68edc0b6b` before them. Not a sync
conflict; validated at the contractual head without merging.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as rounds 72–81): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** |
| Drain + rate-limit set: `packages/maistro-server/tests/test_queue_singleton_drain.py`, `packages/maistro-server/tests/api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `governance/test_conformance.py`, `maistro-evolve/tests/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** |
| `test_pg_learnings.py` (incl. the DDL-fence test) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://maistro:soak@127.0.0.1:18433/maistro` against soak DB `maistro-soak-pg` (container up 12 h; credentials taken from the container's own `POSTGRES_USER`/`POSTGRES_PASSWORD` env), live-checked at alembic head `062` via `DATABASE_URL=… alembic current` | **46 passed, 0 skipped** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / every relative markdown link resolves |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1076-1082; gates resolve base `4aa68edc0b6b`, candidate `ff28509ade6` = HEAD) | 1,323/1,323 reviewed identities banked; `git diff --numstat bb4257f09..HEAD -- quality/` = 0 rows (ledgers identical to the dispatch base) |
| `scripts/check-radon-baseline.py` **with CI's exact invocation (no positional args, quality.yml:852)** | 137/137 C-or-worse blocks banked |

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']` — re-executed this round:

- `sustain_duration`: observed `420.09 s` vs
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`run_soak.py:67`, compared at
  `:1601-1602`; pack row `{observed_seconds: 420.09, minimum_seconds: 14400,
  ok: False}`). `--sustain-seconds` (default 420, `run_soak.py:1678`) only
  sets run length, never the floor — no override exists. The 14,400 s
  continuous floor exceeds this job's `timeout_s = 5400` (read directly from
  this round's manifest), and background commands are prohibited, so no
  in-lane run can flip this row.
- `exact_rc_artifact`: `ok=False`, topology `host-uvicorn-preflight`,
  reason `not the exact production Compose image and configuration`.
  `preflight_artifact_check()` (`run_soak.py:730-743`) refuses host-process
  topology deliberately and its docstring states there is deliberately no CLI
  override; an exact-RC runner needs its own observed image/configuration
  evidence. No RC artifact/configuration has been designated upstream (see
  external pair below), so there is nothing to soak against yet.
- All other gates re-read from the pack's `thresholds.checks` and ok:
  `graceful_drain` ok=True required=True (drain_5xx=0, drain_conn_errors=0,
  drain_seconds=1.0, SIGTERM, not escalated), `lb_failover_bounded` ok=True
  (0 5xx/conn errors in a 5.54 s kill window vs 27.0 s bound),
  `exactly_once_schedule_occurrence` True, `exactly_once_task_admission` True,
  `rate_limit_enforced` True, `replica_2_rejoined` True,
  `nonterminal_runs_after_settle` ok=True count=0, `task_admission_availability`
  ok=True ratio=1.0 (2333/2333 accepted outside the kill window, 0
  backpressuring 429s); `rss_growth`/`fd_growth` informational (ok=None);
  `duplicate_evidence.runs_sharing_one_task_run_identity` = 0.
- Pack provenance re-verified: added once by `215bdec8a` ("fresh two-replica
  shakedown at 3da4e035eb"), whose recorded `hashes.git_head` `3da4e035eb1f`
  is a merge-base ancestor of HEAD; `git diff 3da4e035..HEAD --stat --
  scripts/soak/` is empty (zero drift on the gate code since the evidence
  head), so the replay is faithful to the pack's generation code.

## External pair (this round's 16:08Z capture, 69 sources)

Issue #860 open, 435 comments, updated 2026-10-10T15:53:09Z; all 10
acceptance checkboxes unchecked (0 checked anywhere in body+comments), zero
RC-designation tokens (the single regex hit is the issue body's own
acceptance prose). The two newest comments are the prior attempt's own
progress markers (`maistro-progress:040b7d4d…:started` / `:blocked`). Parent
#89 open, 0 comments, updated 2026-09-22 — no RC designation. Linked PRs:
#1672 open draft, `merged_at` null, head `16b244414b`; #1567, #1602, #2100
closed AND merged (`d22378795c`, `927a9c3c5b`, `b950e5933a`).

## Verdict

**NEEDS-DEEP-REVIEW carried forward — the blocker is external to the lane.**
Every deterministic gate is green at the contractual head, and the promotion
replay fails on exactly the two rows that an in-lane run provably cannot
flip: a ≥4 h continuous soak (floor 14,400 s > lane timeout 5,400 s,
background prohibited) of the exact RC artifact, where no RC artifact has
been designated upstream (`preflight_artifact_check` has no override by
design). Resolution requires an upstream decision — designate the RC
artifact/configuration that #89 would promote and run the ≥4 h soak outside
this lane's constraints — not further code repair. Inventory delta: 0 (no
tests added or removed).
