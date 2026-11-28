# Issue #860 — round 83 (job 25892dfe8fab4699b01b9c802364412d) independent re-validation at cca2719a3

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `cca2719a3ae68565f07eabf30661585eb49d7211`
(working tree clean on arrival, exactly the dispatch head — HEAD is round
040b7d4d's own commit; that attempt completed verdict NEEDS-DEEP-REVIEW and its
docs-only round-82 handoff is the sole content delta from the previously
validated `ff28509ade698`, re-verified with `git diff --stat`: one new file,
110 lines). No `check-*.log` files exist for this job (driver `checks` empty
per manifest), so the full battery was run directly at HEAD. The prior attempt
at this same head (job `e570209e00fb`, head `cca2719a3ae6`) died on a provider
timeout ~56 s in before any validation ran (`result.json`:
`failure_kind: provider_error`, `checks: []`), so this round's execution is the
first validation actually performed at `cca2719a3`. Every gate reproduced its
rounds 72–82 result exactly, including the stale-failure check: the
`test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`
failure recorded in an older job's `check-3.log` (24 ≠ 21 DDL statements) does
not reproduce at this head — the PG set passes 46/46 live and the DDL-fence
test passes standalone, both with and without `MAISTRO_TEST_PG_DSN`.

## Develop drift this round (base advanced; still not a conflict)

`git fetch origin develop` at round start: `origin/develop` is now
`435dc1937e04` — exactly this round's manifest base (prior rounds dispatched
against `bb4257f0960f`; develop advanced past it by `435dc1937` / #2021).
Three commits sit on the develop side (`d11368cd7`, `bb4257f09`, `435dc1937`),
merge-base `4aa68edc0b6b` unchanged. Programmatically: develop side changed 26
files, branch side 372, **intersection empty** (zero conflict risk). The
manifest `surfaces` list (372 files) equals the branch-side two-dot diff
exactly — 0 surfaces outside the diff, 0 diff files missing from the manifest,
0 surfaces touching develop-side files. The `quality/` row deltas
(`durable-table-retention.json` +24, `shipped-surface-truth.json` +10) are
additions made solely by develop-side `435dc1937`; this branch never modified
those files since the merge base (fork-point artifact, not a merge loss). Not
a sync conflict; validated at the contractual head without merging.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as rounds 72–82): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** |
| Drain + rate-limit set: `packages/maistro-server/tests/test_queue_singleton_drain.py`, `packages/maistro-server/tests/api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py`, `packages/maistro-core/tests/governance/test_conformance.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** |
| `packages/maistro-core/tests/persistence/test_pg_learnings.py` (incl. the DDL-fence test) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:18433/maistro` against soak DB `maistro-soak-pg` (container up 12 h; credentials taken from the container's own `POSTGRES_USER`/`POSTGRES_PASSWORD` env), live-checked at alembic head `062` via `DATABASE_URL=… alembic current` | **46 passed, 0 skipped** |
| DDL-fence test standalone (`::test_ensure_schema_fences_ddl_behind_advisory_lock`) | **1 passed** (with and without PG DSN) |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / every relative markdown link resolves |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1076-1082; gates resolve base `4aa68edc0b6b`, candidate `cca2719a3ae6` = HEAD) | 1,323/1,323 reviewed identities banked; no ledger amendment needed |
| `scripts/check-radon-baseline.py` **with CI's exact invocation (no positional args, quality.yml:852)** | 137/137 C-or-worse blocks banked |

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']` — re-executed this round:

- `sustain_duration`: observed `420.09 s` vs
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`run_soak.py:67`, compared at
  `:1601-1602`; pack row `{observed_seconds: 420.09, minimum_seconds: 14400,
  ok: False}`). `--sustain-seconds` (default 420, `run_soak.py:1678`) only
  sets run length (`:1399/:1405/:1485/:1504-1505`), never the floor — no
  override exists. The 14,400 s continuous floor exceeds this job's
  `timeout_s = 5400` (read directly from this round's manifest), and
  background commands are prohibited, so no in-lane run can flip this row.
- `exact_rc_artifact`: `ok=False`, topology `host-uvicorn-preflight`,
  reason `not the exact production Compose image and configuration`.
  `preflight_artifact_check()` (`run_soak.py:730-743`) refuses host-process
  topology deliberately — its docstring states "There is deliberately no CLI
  override: an exact-RC runner needs its own observed image/configuration
  evidence" — and no RC artifact/configuration has been designated upstream
  (see external pair below), so there is nothing to soak against yet.
- All other gates re-read from the pack's `thresholds.checks` and ok:
  `graceful_drain` ok=True required=True (drain_5xx=0, drain_conn_errors=0,
  drain_seconds=1.0, SIGTERM, not escalated), `lb_failover_bounded` ok=True
  (0 5xx/conn errors in a 5.54 s kill window vs the passive-health budget),
  `exactly_once_schedule_occurrence` True, `exactly_once_task_admission` True,
  `rate_limit_enforced` True, `replica_2_rejoined` True,
  `nonterminal_runs_after_settle` ok=True count=0, `task_admission_availability`
  ok=True ratio=1.0 (2333/2333 accepted outside the kill window, 0
  backpressuring 429s); `rss_growth`/`fd_growth` informational (ok=None);
  `duplicate_evidence.runs_sharing_one_task_run_identity` = 0;
  `final_runs_by_status` completed=2359/cancelled=1, nonterminal 0,
  `replica_boot_seconds` 2.6.
- Pack provenance re-verified: added once by `215bdec8a` ("fresh two-replica
  shakedown at 3da4e035eb"), unmodified since (`git log 215bdec8a..HEAD --
  <pack>` empty); recorded `hashes.git_head` `3da4e035eb1f` is a merge-base
  ancestor of HEAD; `git diff 3da4e035..HEAD --stat -- scripts/soak/` is empty
  (zero drift on the gate code since the evidence head), so the replay is
  faithful to the pack's generation code.

## External pair (this round's 16:37Z capture, 69 sources)

Issue #860 open, 438 comments, updated 2026-10-10T16:19:19Z; all 10
acceptance checkboxes unchecked (0 checked anywhere in body+comments), zero
RC-designation tokens (the single regex hit is the issue body's own
acceptance prose "release-candidate load profile"). The newest comments are
lane progress markers only (`maistro-progress:…:started` / `:blocked` for jobs
`c4569c95…` / `d0664643…`). Parent #89 open, 0 comments, updated 2026-09-22 —
its single RC-token hit is prose ("Promote a release candidate through the
exact shipping pipeline"), not a designation. Linked PRs: #1672 open draft,
`merged_at` null, head `16b244414b`; #1567, #1602, #2100 closed AND merged
(`d22378795c`, `927a9c3c5b`, `b950e5933a`).

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
