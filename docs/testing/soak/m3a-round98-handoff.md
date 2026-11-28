# Issue #860 — round 98 (job 8bcc6cb21e764ad59f1db7b6023abdee) independent re-validation at 086cfd2ae

**Not promotion evidence or integration approval.** This round's manifest is
empty (`checks: []`, no `check-*.log` files in the job directory) and the
prior attempt (job `5705e15347dd426dab8e335038508422`) died on a provider
timeout with zero checks run, so the deterministic battery was executed
directly at the dispatch head
`086cfd2aec3134a130b8f8139870bc905cfffb3f` (working tree clean on arrival;
that head is round 97's handoff commit, so the content delta from the
round-97-validated tree `35ddf25ef5c6` is exactly the one round-97 handoff
file, docs-only — `git diff --stat 35ddf25ef5..086cfd2ae`). Every gate
reproduced rounds 93–97.

## Deterministic battery executed (all green at HEAD 086cfd2ae)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Canonical 13-file soak/contract/release-guard/concurrency set (`tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`, `packages/maistro-core/tests/state/test_writer_concurrency.py`, `packages/maistro-core/tests/runs/test_run_concurrency_limits.py`, `packages/maistro-core/tests/graph/test_concurrency.py`, `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py`) | **308 passed, 16 skipped** (13.65 s) — exact reproduction |
| Drain + rate-limit set (`packages/maistro-server/tests/test_queue_singleton_drain.py`, `packages/maistro-server/tests/api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py`) | **38 passed** — exact reproduction |
| Broader concurrency/boot superset extras: `tests/test_ci_merge_group_scope.py` + `tests/test_shipped_surface_truth.py` + `tests/test_check_promotion_surface.py` | **109 passed** — arithmetic pin 308 + 109 = 417 holds |
| Broader drain/restart/shutdown coverage: `test_queue_singleton_drain.py`, `test_sigterm_shutdown.py`, `test_task_restart_recovery.py`, `api/test_main.py` | **29 passed, 1 skipped** |
| Promotion/governance pytest set: `tests/test_check_release_consistency.py`, `packages/maistro-evolve/tests/test_promotion_governance.py`, `packages/maistro-rsi/tests/test_gate_evidence.py`, `packages/maistro-core/tests/memory/learnings/test_evidence_promotion.py`, `packages/maistro-core/tests/memory/user_model/test_promotion.py`, `packages/maistro-core/tests/governance/test_promotion_contract.py` | **173 passed** — exact reproduction |
| Full rsi suite, tests-only scope (`packages/maistro-rsi/tests`) | **1,624 passed, 4 skipped** (80.25 s) — exact reproduction of rounds 93–97 |
| PG live set (`packages/maistro-core/tests/persistence/test_pg_learnings.py` + `test_pg_sessions_concurrency.py`) against soak DB `maistro-soak-pg` (container up 19 h, `127.0.0.1:18433`, database `maistro`, `MAISTRO_TEST_PG_DSN` from the container's own env, plain `postgresql://` scheme), live alembic head verified `062` via `alembic_version` | **46 passed**; DDL-fence `test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock` **1 passed** standalone — the stale job-98a11313 `check-3.log` failure (assert 24 == 21) does not reproduce at this head |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory (delta 0; no tests added this round) |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` / `scripts/check-merge-markers.py` / `git diff --check` | Matrix complete / every relative markdown link resolves (incl. this handoff) / no conflict markers / clean |
| `scripts/check-promotion-surface.py` / `scripts/check-release-consistency.py` | promotion surface: ok / released none, shipping 0.9.0, working toward 1.0.0 |
| `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments, `quality.yml:1075-1080`) | **1,323 reviewed identities → 1,323 findings** (base `4aa68edc0b6b`, candidate `086cfd2aec3`) — ledger matches; no amendment |
| `scripts/check-radon-baseline.py` (CI's no-arg invocation, `quality.yml:852`) | **137 reviewed C-or-worse blocks → 137** (candidate `086cfd2aec3`) |

## Develop drift (unchanged; not a sync conflict)

`origin/develop` re-fetched this round: `435dc1937e04` = this round's manifest
base; merge-base `4aa68edc0b6b` unchanged and `git diff --name-only
<merge-base> HEAD -- quality/` is empty (this branch banks nothing; no ledger
edits made or needed). The `git diff --numstat origin/develop -- quality/`
deltas (0+/24−, 0+/10−) are develop-side prunes on files this branch never
touched. Validated at the contractual head without merging.

## Promotion replay (live gate code at HEAD, re-executed this round)

`failed_promotion_checks()` replayed across all 16 evidence packs in
`docs/testing/soak/evidence/` with the gate module loaded live from
`scripts/soak/run_soak.py` at this head:

- Rounds 26, 27, 28, 29, 30, 43 and round 6 fail **exactly**
  `['sustain_duration', 'exact_rc_artifact']` (round-43 is the canonical
  pack). Round 5 additionally fails `rate_limit_enforced`; the remaining
  packs fail strict supersets. Sustain re-read from the packs' top-level
  `sustain_seconds` field: best observed across all packs is **420.1 s**
  (round-29) vs `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (read live,
  `run_soak.py:67`, compared at `:1601-1602`). The floor exceeds this job's
  5,400 s lane budget and background commands are prohibited, so no in-lane
  run can flip `sustain_duration`.
- `exact_rc_artifact` is hardwired to `preflight_artifact_check()`
  (`run_soak.py:730-743`), which refuses host topology deliberately (`ok:
  False`, "not the exact production Compose image and configuration", no CLI
  override by design) — re-invoked live this round, same refusal.
- Round-43 pack correctness rows re-read ok from the pack JSON this round:
  `kill_restart` drained=True drain_5xx=0 drain_conn_errors=0
  drain_seconds=1.0 escalated=False; `exactly_once_schedule_claim`
  occurrences_with_multiple_runs=0 ok=True; `exactly_once_tasks` 12
  concurrent submissions, 12 delivered (all 202) → 1 distinct run id
  (`3cba8e941049…`, duplicate_run_ids=11, ok=true);
  `rate_limit.enforced_everywhere` True; `nonterminal_run_items` empty (0);
  `final_runs_by_status` completed=2359 / cancelled=1;
  `duplicate_evidence.runs_sharing_one_task_run_identity` 0;
  `kill_restart.rejoined` True. Threshold rows re-read ok from
  `thresholds.checks`: `graceful_drain` required, SIGTERM, drained, 0 5xx,
  0 conn errors, 1.0 s, no escalation; `lb_failover_bounded` observed_window
  5.54 s with 0 observed 5xx+conn errors vs 4,320 s budget;
  `task_admission_availability` ratio 1.0 (2,333 accepted / 2,333 available
  outside the kill window, 0 unretryable 429s);
  `nonterminal_runs_after_settle` count 0. The pack's own recorded
  `thresholds.checks` booleans are False for exactly `exact_rc_artifact` and
  `sustain_duration` — matching the live replay for this pack row-for-row.
- Pack provenance re-verified: canonical pack `hashes.git_head`
  `3da4e035eb1f` is an ancestor of HEAD (`git merge-base --is-ancestor`) and
  `git diff 3da4e035eb1f..HEAD -- scripts/soak/` is empty — zero gate-code
  drift since the evidence head, so the replay is faithful.

## External pair (this round's 23:23Z capture, 69 sources in the job's dispatch-context.json)

Issue #860 open, **479** comments, **0/10 acceptance boxes checked** in the
body (`- [ ]`×10, no `- [x]`). A release-candidate regex sweep across all 69
captured sources finds 841 hits, all prose: 821 inside draft PR #1672's
diff of this very branch's handoff docs (which repeatedly state "not
release-candidate soak acceptance"), the issue's own criterion text, the
parent #89 task text and title ("Run RC soak and byte-equivalent final
promotion"), historical #86/#448/#449/#453 and #862 cross-references. A
complementary artifact-designation sweep (sha256/digest/frozen-artifact
shapes) outside #1672's file listing finds only base-image digest pins in
unrelated dependency-update PR bodies (golang/python MCR tags) — **no RC
artifact is designated upstream**. Parent #89 open, 0 comments (updated
2026-09-22). Linked PRs #1567 (`d22378795c`) / #1602 (`927a9c3c5b`) /
#2100 (`b950e5933a`) closed **and merged**; #1672 still open draft
(`16b244414b`, unmerged).

## Acceptance disposition (unchanged by this round)

Correctness-facing criteria stand as evidenced by the round-43 canonical
pack and the committed pytest/soak suites (two deployed replicas; exactly-once
task admission and schedule-occurrence fencing; kill/restart drain/failover
with zero loss or duplication in the window; per-replica rate limiting with
its documented per-process boundary; admission availability ratio 1.0;
nonterminal runs 0). Still unmet, and not resolvable by a repair worker:

1. `sustain_duration`/`exact_rc_artifact` require a frozen, designated
   immutable RC artifact (none exists upstream: parent #89 open with zero
   comments) and a ≥4 h instrumented soak of that artifact; the harness
   floor (14,400 s) exceeds this lane's 5,400 s budget and the gate
   correctly still fails every committed pack (best 420.1 s).
2. Successful tool/model calls need provider keys absent from this
   environment, so Graph/node fan-out with successful work, multi-user
   successful traffic, Canvas operations and sustained Goal reconciliation
   remain UNVERIFIED.
3. The "cannot be bypassed by replica selection" criterion conflicts with
   the deliberate per-process rate-limit design (documented in
   `api/rate_limit.py`); it needs an owner/ADR decision, not a silent policy
   change.
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
