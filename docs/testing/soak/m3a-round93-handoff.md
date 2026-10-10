# Issue #860 — round 93 (job d9412432431444a493b1801e10513bcc) independent re-validation at 1f74d2d39

**Not promotion evidence or integration approval.** This round's manifest is
empty (`checks: []`, `timeout_s: 5400`, no `check-*.log` files) and the prior
attempt (job `34e76f32`) requested `NEEDS-DEEP-REVIEW`, so the deterministic
battery was executed directly at the dispatch head
`1f74d2d39107016b08e45e9255c2e533aabd8935` (working tree clean on arrival;
that head is round 92's handoff commit, so the content delta from the
round-92-validated tree `fa579a731723` is exactly the one round-92 handoff
file, docs-only). Every gate reproduced rounds 72–92.

## Deterministic battery executed (all green at HEAD 1f74d2d39)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Canonical 13-file soak/contract/release-guard/concurrency set (`tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py`) | **308 passed, 16 skipped** (14.05 s) — exact reproduction |
| Drain + rate-limit set (`packages/maistro-server/tests/test_queue_singleton_drain.py`, `packages/maistro-server/tests/api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py`) | **38 passed** — exact reproduction |
| Broader concurrency/boot superset extras: `tests/test_ci_merge_group_scope.py` + `tests/test_shipped_surface_truth.py` + `tests/test_check_promotion_surface.py` | **109 passed** — arithmetic pin 308 + 109 = 417 holds |
| Broader drain/restart/shutdown coverage: `test_queue_singleton_drain.py`, `test_sigterm_shutdown.py`, `test_task_restart_recovery.py`, `api/test_main.py` | **29 passed, 1 skipped** |
| Promotion/governance pytest set: `tests/test_check_release_consistency.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `packages/maistro-rsi/tests/test_gate_evidence.py`, `packages/maistro-core/tests/memory/learnings/test_evidence_promotion.py`, `packages/maistro-core/tests/memory/user_model/test_promotion.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py` | **173 passed** — exact reproduction |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (78.65 s) — exact reproduction |
| PG live set (`packages/maistro-core/tests/persistence/test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 17 h, `127.0.0.1:18433`, `MAISTRO_TEST_PG_DSN` from the container's own env, plain `postgresql://` scheme), live alembic head verified `062` via `alembic_version` | **46 passed**; DDL-fence `test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure does not reproduce at this head |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (delta 0; no tests added this round) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `scripts/check-merge-markers.py` / `git diff --check` | Matrix complete / every relative markdown link resolves / no conflict markers / clean |
| `scripts/check-promotion-surface.py` / `scripts/check-release-consistency.py` | promotion surface: ok / released none, shipping 0.9.0, working toward 1.0.0 |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `quality.yml:1075-1080`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `1f74d2d39107`) — ledger matches; no amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** |

## Develop drift (unchanged; not a sync conflict)

`git fetch origin develop` at round start: `origin/develop` is `435dc1937e04`
— exactly this round's manifest base; merge-base `4aa68edc0b6b` unchanged.
`git diff --name-only <merge-base> HEAD -- quality/` is **empty** (this branch
banks nothing); vs `435dc193` only the develop-side prunes
(`durable-table-retention.json` −24 rows, `shipped-surface-truth.json` −10
rows) made by `435dc1937` on files this branch never touched. Validated at
the contractual head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) replayed across
all 16 evidence packs in `docs/testing/soak/evidence/` (11 of them
threshold-bearing):

- Rounds 26, 27, 28, 29, 30, 43 and round 6 fail **exactly**
  `['sustain_duration', 'exact_rc_artifact']` (round-43 is the canonical
  pack). Round 5 additionally fails `rate_limit_enforced`;
  `m3a-repair-validation.json`, the five threshold-free round-7 prodstack
  observation documents, `m3a-round8-prodstack-extended.json` and
  `m3a-soak-evidence.json` fail strict supersets. Best observed sustain
  across all packs is `420.1 s` (round-29) — none approaches the floor.
- `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` read live (`run_soak.py:67`;
  compared at `:1601-1602`). The floor exceeds this job's `timeout_s = 5400`
  (manifest), and background commands are prohibited, so no in-lane run can
  flip `sustain_duration`.
- `exact_rc_artifact` is hardwired to `preflight_artifact_check()`
  (`run_soak.py:730-743`), which refuses host topology deliberately
  (`ok: False, topology: host-uvicorn-preflight`, no CLI override by design).
- Round-43 pack correctness rows re-read ok: `graceful_drain` required+ok
  (drained, drain_5xx=0, drain_conn_errors=0, drain_seconds=1.0, no
  escalation), `exactly_once_schedule_occurrence` True,
  `exactly_once_task_admission` True, `rate_limit_enforced` True,
  `lb_failover_bounded` ok (0 5xx/conn-errors in the measured 5.54 s window
  vs 4320 s budget, upper bound 27.0), `replica_2_rejoined` True,
  `nonterminal_runs_after_settle` ok (count 0), `task_admission_availability`
  ok (2,333 submissions outside kill window, ratio 1.0, zero unretryable
  429s).
- Pack provenance: recorded `hashes.git_head` `3da4e035eb1f` is an ancestor
  of HEAD (`git merge-base --is-ancestor`) and
  `git diff 3da4e035eb1f..HEAD -- scripts/soak/` is empty — zero gate-code
  drift since the evidence head, so the replay is faithful.

## External pair (this round's 21:07Z capture, 69 sources)

Issue #860 open, **466** comments (+3 since round 92's 463 — all three are
lane progress markers for jobs `f75a7f80` and `34e76f32`: two started, one
blocked), **0/10 acceptance boxes checked** across body+comments, and zero
`release-candidate`/RC-designation regex hits outside the issue's own
criterion text, i.e. **no RC has been designated upstream**. Parent #89
open, 0 comments (updated 2026-09-22). Linked PRs: #1567, #1602, #2100
closed and merged; #1672 still open draft `16b244414b` (unmerged).

## Acceptance disposition (unchanged by this round)

Correctness-facing criteria stand as evidenced by the round-43 canonical pack
and the committed pytest/soak suites (two deployed replicas; exactly-once
task admission and schedule-occurrence fencing; kill/restart drain/failover
with zero loss or duplication in the window; per-replica rate limiting with
its documented per-process boundary — `api/rate_limit.py` enforcement-scope
note: N replicas ⇒ N × the configured limit, deliberately not cluster-wide;
admission availability ratio 1.0; nonterminal runs 0). Still unmet, and not
resolvable by a repair worker:

1. `sustain_duration`/`exact_rc_artifact` require a frozen, selected
   immutable RC artifact (none designated upstream: parent #89 open with zero
   comments) and a ≥4 h instrumented soak of that artifact; the harness
   floor (14,400 s) exceeds this lane's 5,400 s budget and the gate
   correctly still fails every committed pack (best 420.1 s).
2. Successful tool/model calls need provider keys absent from this
   environment, so Graph/node fan-out with successful work, multi-user
   successful traffic, Canvas operations and sustained Goal reconciliation
   remain UNVERIFIED.
3. The "cannot be bypassed by replica selection" criterion conflicts with the
   deliberate per-process rate-limit design (documented in
   `api/rate_limit.py`, enforced per-replica); it needs an owner/ADR
   decision, not a silent policy change.
4. Filing load findings github-side is prohibited to this worker.

**Verdict: NEEDS-DEEP-REVIEW carried forward (external).** Every
deterministic gate passes at the assigned head; the replay is faithful to
undrifted gate code; no gate was weakened and nothing was edited except this
record. Advancing acceptance requires an operational decision outside this
lane (freeze the RC artifact, provider keys into the gateway, ≥4 h
instrumented soak of the exact artifact) plus the rate-limit ownership call;
another validation-only round cannot advance it.

Progress: checked 1 issue; validation rounds done 1; code changes 0; skipped
0; errors 0; promotion-blocked 1.
