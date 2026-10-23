# Issue #860 — round 88 (job dfeb707226b549e19b9f4501328c5c22) independent re-validation at 73a6ea02a

**Not promotion evidence or integration approval.** This round re-executes the
full deterministic battery at the dispatch head
`73a6ea02ae4a784514bf068f2b0c20d202ec91f5` (working tree clean on arrival,
exactly the dispatch head — the round-87 handoff commit itself). The driver
ran zero deterministic checks this round (`checks: []` in the job manifest,
`timeout_s: 5400`, and no `check-*.log` files in the job directory), so every
gate below was executed directly at HEAD. Content delta from round 87 is nil
(docs-only rounds; `git diff` between the validated round-86 tree and HEAD
adds only round 87's handoff file), and every gate reproduced rounds 72–87
exactly.

## Deterministic battery executed (all green at HEAD 73a6ea02a)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | Resolved 256 packages, already reconciled (no changes) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| 13-file soak/contract/release-guard/concurrency set (same composition as rounds 72–87): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** (skips are PG-parameterized rows) |
| Drain + rate-limit set (`test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `security/test_rate_limiter.py`) | **38 passed** |
| Promotion-surface/governance/release set (6 files) | **283 passed** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** |
| PG live set (`test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 15 h, `127.0.0.1:18433`, credentials from the container's own env), live alembic head verified `062` | **46 passed, 0 skipped**; DDL-fence test `::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure (assert 24 == 21) does not reproduce at this head |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (delta 0) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `git diff --check` | Matrix complete / every relative markdown link resolves / clean |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `vulture-ratchet.yml:80-86`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `73a6ea02ae4a`) — no ledger amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** |

## Develop drift (unchanged; not a sync conflict)

`git fetch origin develop` at round start: `origin/develop` is `435dc1937e04`
— exactly this round's manifest base; merge-base `4aa68edc0b6b` unchanged.
`quality/` numstat vs `origin/develop` shows only the develop-side additions
(`durable-table-retention.json` +24, `shipped-surface-truth.json` +10) made by
`435dc1937` on files this branch never touched. Validated at the contractual
head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`; `preflight_artifact_check()`
returns `ok: False, topology: host-uvicorn-preflight` and
`PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` read live.

- `sustain_duration`: pack observed `420.09 s` vs floor `14,400 s`
  (`run_soak.py:67`, compared at `:1601-1602`). A scan across every committed
  evidence pack shows the best observed sustain anywhere is `420.1 s`
  (round-29) — no pack approaches the floor. The floor exceeds this job's
  `timeout_s = 5400` (read from the manifest), and background commands are
  prohibited, so no in-lane run can flip this row.
- `exact_rc_artifact`: hardwired to `preflight_artifact_check()`
  (`run_soak.py:730-743`), which refuses host topology deliberately. No RC
  artifact/configuration is designated upstream (see external pair), so there
  is nothing to soak against.
- All other evidence re-read ok from the pack: `graceful_drain` ok=True
  required=True (drain_5xx=0, drain_conn_errors=0, drain_seconds=1.0,
  rejoined), `lb_failover_bounded`, `nonterminal_runs_after_settle`,
  `task_admission_availability` ok; `exactly_once_schedule_claim`
  (occurrences_with_multiple_runs=0, duplicate_claims_reported=1), 
  `exactly_once_tasks` (12 concurrent submissions → 1 distinct run id,
  11 duplicates collapsed), rate limit enforced on direct replicas;
  `final_runs_by_status` completed=2359 cancelled=1, `nonterminal_runs` 0,
  `duplicate_evidence.runs_sharing_one_task_run_identity` = 0.
- Pack provenance re-verified: recorded `hashes.git_head` `3da4e035eb1f` is an
  ancestor of HEAD (`git merge-base --is-ancestor`), and
  `git diff 3da4e035..HEAD -- scripts/soak/` is empty — zero gate-code drift
  since the evidence head, so the replay is faithful.

## External pair (this round's 18:48Z capture, 69 sources)

Issue #860 open, **452** comments (delta +2 vs round 87's capture), all 10
acceptance checkboxes unchecked (0 checked across body and all 452 comment
bodies). The two newest comments are lane progress markers only
(`maistro-progress:c66a5b75d…:started` / `:blocked`) — zero RC-designation
tokens (the sole regex hit is the body's own acceptance prose). Parent #89
open, 0 comments ("RC artifact" wording is its own acceptance prose). Linked
PRs unchanged: #1672 open draft (`16b244414b`, unmerged); #1567, #1602, #2100
closed and merged (`d22378795c`, `927a9c3c5b`, `b950e5933a`).

## Verdict

**NEEDS-DEEP-REVIEW carried forward — the blocker is external to the lane and
unchanged.** Every deterministic gate is green at the contractual head; the
promotion replay fails on exactly the two rows an in-lane run provably cannot
flip (≥4 h continuous soak, floor 14,400 s > lane timeout 5,400 s with
background prohibited; exact-RC soak with no RC artifact designated upstream
and no harness override by design). Resolution requires an upstream decision —
designate the RC artifact/configuration that #89 would promote and run the
≥4 h soak outside lane constraints — not further code repair. Inventory delta:
0 (no tests added or removed; this round adds only this handoff doc).
