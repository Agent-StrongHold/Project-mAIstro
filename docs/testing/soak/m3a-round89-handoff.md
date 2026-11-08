# Issue #860 — round 89 (job d04d1e65b71b4f6e87ad7bcc6ffcf2c1) independent re-validation at 41edeeead

**Not promotion evidence or integration approval.** The immediately prior
attempt at this exact head (job `0fe908650c8341abad1ffe44db49e215`) died on a
provider timeout with zero checks run (`result.json`: `failure_kind:
provider_error`, `checks: []`), and this round's manifest is also empty
(`checks: []`, `timeout_s: 5400`, no `check-*.log` files), so the full
deterministic battery below was executed directly at the dispatch head
`41edeeada906baf85bf0d5d4eda3ce027a75b33` (working tree clean on arrival,
exactly the dispatch head — the round-88 handoff commit itself). Content delta
from round 88 is nil (docs-only rounds; `git diff` between the validated
round-87 tree and HEAD adds only round 88's handoff file), and every gate
reproduced rounds 72–88.

## Deterministic battery executed (all green at HEAD 41edeeead)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Canonical 13-file soak/contract/release-guard/concurrency set (same composition as rounds 72–88; round-88's handoff abbreviates the last path — the file lives at repo root `formal/models/test_strike_concurrency.py`): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** — exact reproduction (skips are PG-parameterized rows) |
| Drain + rate-limit set (`test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `security/test_rate_limiter.py`) | **38 passed** — exact reproduction |
| Broader concurrency/boot coverage (superset re-check): adds `tests/test_ci_merge_group_scope.py`, `tests/test_shipped_surface_truth.py`, `tests/test_check_promotion_surface.py` to the 13-file set | **314 passed, 16 skipped** |
| Broader drain/restart/shutdown coverage: `test_queue_singleton_drain.py`, `test_sigterm_shutdown.py`, `test_task_restart_recovery.py`, `api/test_main.py` | **29 passed, 1 skipped** |
| Promotion/governance/release pytest set: `tests/test_check_release_consistency.py`, `evolve/test_promotion_governance.py`, rsi promotion tests (3 files), `memory/learnings/test_evidence_promotion.py`, `memory/user_model/test_promotion.py`, `governance/test_promotion_contract.py` | **173 passed** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** — exact reproduction |
| PG live set (`test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 15 h, `127.0.0.1:18433`, credentials from the container's own env), live alembic head verified `062` | **46 passed, 0 skipped**; DDL-fence test `::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure (assert 24 == 21) does not reproduce at this head |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (delta 0) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `scripts/check-merge-markers.py` / `git diff --check` | Matrix complete / every relative markdown link resolves / no conflict markers / clean |
| `scripts/check-promotion-surface.py` / `scripts/check-release-consistency.py` | promotion surface: ok / released none, shipping 0.9.0, working toward 1.0.0 |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `quality.yml:1076-1080`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `41edeeada90`) — no ledger amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** |

## Develop drift (unchanged; not a sync conflict)

`git fetch origin develop` at round start: `origin/develop` is `435dc1937e04`
— exactly this round's manifest base; merge-base `4aa68edc0b6b` unchanged.
`quality/` numstat: **0 rows** changed between merge-base and HEAD (this
branch banks nothing); vs `435dc193` only the develop-side prunes
(`durable-table-retention.json` −24, `shipped-surface-truth.json` −10) made by
`435dc1937` on files this branch never touched. Validated at the contractual
head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`; every other committed
pack returns a strict superset of those two rows (replayed across all 12
packs with thresholds); `preflight_artifact_check()` returns
`ok: False, topology: host-uvicorn-preflight` and
`PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` read live.

- `sustain_duration`: pack observed `420.09 s` vs floor `14,400 s`
  (`run_soak.py:67`, compared at `:1601-1602`). A scan across every committed
  evidence pack confirms the best observed sustain anywhere is `420.1 s`
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
  (occurrences_with_multiple_runs=0), `exactly_once_tasks` (12 concurrent
  submissions → 1 distinct run id), rate limit enforced on direct replicas;
  `final_runs_by_status` completed=2359 cancelled=1, `nonterminal_runs` 0,
  `duplicate_evidence.runs_sharing_one_task_run_identity` = 0.
- Pack provenance re-verified: recorded `hashes.git_head` `3da4e035eb1f` is an
  ancestor of HEAD (`git merge-base --is-ancestor`), and
  `git diff 3da4e035..HEAD -- scripts/soak/` is empty — zero gate-code drift
  since the evidence head, so the replay is faithful.

## External pair (this round's 19:18Z capture, 69 sources)

Issue #860 open, **455** comments (delta +3 vs round 88's capture), all 10
acceptance checkboxes unchecked (0 checked across body and all 455 comment
bodies). The three newest comments are lane progress markers only
(`maistro-progress:0245db89…:started`, `maistro-progress:dfeb70722…:started`
/ `:blocked`) — zero RC-designation tokens (a regex sweep over body, parent
body, and all comments finds none). Parent #89 open, 0 comments, updated
2026-09-22. Linked PRs unchanged: #1672 open draft (`16b244414b`, unmerged);
#1567, #1602, #2100 closed and merged (`d22378795c`, `927a9c3c5b`,
`b950e5933a`).

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
