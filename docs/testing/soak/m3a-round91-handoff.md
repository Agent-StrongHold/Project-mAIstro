# Issue #860 — round 91 (job efaba7528e7e4ceab788ccf6035f6baf) independent re-validation at 6af592b633

**Not promotion evidence or integration approval.** This round's manifest is
empty (`checks: []`, `timeout_s: 5400`, no `check-*.log` files), so the
deterministic battery was executed directly at the dispatch head
`6af592b6339875fbfed79e4af1ac818bc0186299` (working tree clean on arrival;
that head is round 90's handoff commit, so content delta from the
round-90-validated tree `d720b0d57233` is exactly the one round-90 handoff
file, docs-only). Every gate reproduced rounds 72–90.

## Deterministic battery executed (all green at HEAD 6af592b633)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Canonical 13-file soak/contract/release-guard/concurrency set (`tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py`) | **308 passed, 16 skipped** (13.99 s) — exact reproduction |
| Drain + rate-limit set (`packages/maistro-server/tests/test_queue_singleton_drain.py`, `packages/maistro-server/tests/api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py`) | **38 passed** — exact reproduction |
| Broader concurrency/boot superset extras: `tests/test_ci_merge_group_scope.py` + `tests/test_shipped_surface_truth.py` + `tests/test_check_promotion_surface.py` | **109 passed** — arithmetic pin 308 + 109 = 417 holds for the superset composition from the two green runs (round-89's "314" remains a transcription slip; composition green) |
| Broader drain/restart/shutdown coverage: `test_queue_singleton_drain.py`, `test_sigterm_shutdown.py`, `test_task_restart_recovery.py`, `api/test_main.py` | **29 passed, 1 skipped** |
| Promotion/governance pytest set: `tests/test_check_release_consistency.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `packages/maistro-rsi/tests/test_gate_evidence.py` (the "rsi promotion tests (3 files)" of earlier handoffs is this one 34-test file), `packages/maistro-core/tests/memory/learnings/test_evidence_promotion.py`, `packages/maistro-core/tests/memory/user_model/test_promotion.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py` | **173 passed** — exact reproduction |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (83.36 s) — exact reproduction |
| PG live set (`packages/maistro-core/tests/persistence/test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 16 h, `127.0.0.1:18433`, `MAISTRO_TEST_PG_DSN` from the container's own env, **plain `postgresql://` scheme** — `asyncpg` rejects `postgresql+asyncpg://`; a first invocation with the wrong scheme was this round's operator error, not a tree defect), live alembic head verified `062` via `alembic_version` | **46 passed, 0 skipped**; DDL-fence `test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure does not reproduce at this head either |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (delta 0) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `scripts/check-merge-markers.py` / `git diff --check` | Matrix complete / every relative markdown link resolves / no conflict markers / clean |
| `scripts/check-promotion-surface.py` / `scripts/check-release-consistency.py` | promotion surface: ok / released none, shipping 0.9.0, working toward 1.0.0 |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `quality.yml:1076-1080`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `6af592b63398`) — no ledger amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** |

## Develop drift (unchanged; not a sync conflict)

`git fetch origin develop` at round start: `origin/develop` is `435dc1937e04`
— exactly this round's manifest base; merge-base `4aa68edc0b6b` unchanged.
`quality/` numstat: **0 rows** changed between merge-base and HEAD (this
branch banks nothing); vs `435dc193` only the develop-side prunes
(`durable-table-retention.json` −24, `shipped-surface-truth.json` −10) made
by `435dc1937` on files this branch never touched. Validated at the
contractual head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) replayed across
all **16 evidence packs** in `docs/testing/soak/evidence/` (12 of them
threshold-bearing):

- Rounds 26, 27, 28, 29, 30, 43 and round 6 fail **exactly**
  `['sustain_duration', 'exact_rc_artifact']` (round-43 is the canonical
  pack). Round 5 additionally fails `rate_limit_enforced`;
  `m3a-repair-validation.json`, the round-7 prodstack family,
  `m3a-round8-prodstack-extended.json` and `m3a-soak-evidence.json` fail
  strict supersets. Best observed sustain across all packs is `420.1 s`
  (round-29) — none approaches the floor.
- `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` read live (`run_soak.py:67`;
  compared at `:1601-1602`). The floor exceeds this job's `timeout_s = 5400`
  (manifest), and background commands are prohibited, so no in-lane run can
  flip `sustain_duration`.
- `exact_rc_artifact` is hardwired to `preflight_artifact_check()`
  (`run_soak.py:730-743`), which refuses host topology deliberately
  (`ok: False, topology: host-uvicorn-preflight`, no CLI override by design).
- Round-43 pack correctness rows re-read ok: `graceful_drain` required+ok
  (drained, drain_5xx=0, drain_conn_errors=0, drain_seconds=1.0, SIGTERM, no
  escalation), `exactly_once_schedule_occurrence` True with
  `occurrences_with_multiple_runs=0` (1 occurrence → 1 run, duplicate claim
  reported once by the second process as designed), `exactly_once_tasks`
  12 concurrent submissions all 202 → 1 distinct run id (11 duplicates
  deduplicated), `rate_limit_enforced` True, `lb_failover_bounded` ok
  (0 5xx/conn-errors in the measured 5.54 s window vs 4320 s budget),
  `replica_2_rejoined` True, `nonterminal_runs_after_settle` ok
  (nonterminal_runs 0), `task_admission_availability` ok (2,333 submissions
  outside kill window, ratio 1.0, zero unretryable 429s),
  `duplicate_evidence.runs_sharing_one_task_run_identity` = 0,
  `final_runs_by_status` completed=2359 cancelled=1.
- Pack provenance: recorded `hashes.git_head` `3da4e035eb1f` is an ancestor
  of HEAD (`git merge-base --is-ancestor`) and
  `git diff 3da4e035..HEAD -- scripts/soak/` is empty — zero gate-code drift
  since the evidence head, so the replay is faithful.

## External pair (this round's 20:13Z capture, 69 sources)

Issue #860 open, **460** comments (+2 since round 90's 458 — both are this
lane's own progress markers), all 10 acceptance checkboxes unchecked
(0 checked across body and all comment bodies). Zero RC-designation tokens
in comments by regex sweep; the single body hit "RC artifact" is the issue's
own acceptance prose. Newest comments are lane progress markers only
(`maistro-progress:d04d1e65b…:blocked`,
`maistro-progress:be0f40ecd…:started`/`:blocked`). Parent #89 open,
0 comments, updated 2026-09-22. Linked PR heads unchanged: #1672 open draft
(`16b244414b`, unmerged); #1567, #1602, #2100 closed and merged
(`d22378795c`, `927a9c3c5b`, `b950e5933a`).

## Verdict

**NEEDS-DEEP-REVIEW carried forward — the blocker is external to the lane and
unchanged.** Every deterministic gate is green at the contractual head; the
promotion replay fails on exactly the two rows an in-lane run provably cannot
flip (≥4 h continuous soak: floor 14,400 s > lane timeout 5,400 s with
background prohibited; exact-RC soak: no RC artifact/configuration designated
upstream and the harness refusal is deliberate by design). Resolution
requires an upstream decision — designate the RC artifact/configuration that
#89 would promote and run the ≥4 h soak outside lane constraints — not
further code repair. Inventory delta: 0 (no tests added or removed; this
round adds only this handoff doc).
