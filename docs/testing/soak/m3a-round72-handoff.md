# Issue #860 — round 72 (job 1042d434) independent re-validation at 15fbb0c2

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `15fbb0c2ea5ab6cf2de613ea662b9ea4d35c7ea0`
(working tree clean on arrival, exactly the dispatch head — HEAD is round
f1cf63c7's own commit, and the immediately prior attempt `854816d2` died on a
provider timeout at this same head with `checks: []`, so nothing to salvage).
No `check-*.log` files exist for this job (driver `checks` empty per
manifest), so the full battery was run directly. `origin/develop` was
re-fetched this round and is still exactly the dispatch base
`4aa68edc0b6b85ae23f97e611d693927218863dc`, already an ancestor of HEAD — no
sync conflict and no merge needed.

## Deterministic battery executed (all green at HEAD)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,270 files already formatted |
| Soak/contract/release-guard/concurrency set (13 files, same composition as round 71 with the sqlite path corrected to `packages/maistro-core/tests/persistence/test_sqlite_schema_concurrency.py`): `tests/test_soak_promotion_gates.py`, `tests/test_release_guard.py`, `tests/test_gitleaksignore_contract.py`, `tests/test_prod_stack_boot_contract.py`, `tests/test_check_deployment_claims.py`, `tests/test_check_gates_ran.py`, `tests/test_check_release_consistency.py`, `api/test_tasks_concurrency_backpressure.py`, `state/test_writer_concurrency.py`, `runs/test_run_concurrency_limits.py`, `graph/test_concurrency.py`, `persistence/test_sqlite_schema_concurrency.py`, `formal/models/test_strike_concurrency.py` | **308 passed, 16 skipped** (skips are PG-parameterized rows) |
| Drain + rate-limit server/core tests: `test_queue_singleton_drain.py`, `api/test_rate_limit.py`, `packages/maistro-core/tests/security/test_rate_limiter.py` | **38 passed** (superset of round 71's 28: the last file adds 10 core rate-limiter rows) |
| Promotion-surface/governance/release set: `tests/test_check_promotion_surface.py`, `governance/test_promotion_contract.py`, `governance/test_conformance.py`, `maistro-evolve/test_promotion_governance.py`, `tests/release/test_installed_workspace_proof_schema.py`, `tests/release/test_installed_workspace_request_chain.py` | **283 passed** (superset of round 71's 271: `governance/test_conformance.py` included this round) |
| `test_pg_learnings.py` (incl. `test_ensure_schema_fences_ddl_behind_advisory_lock`) + `test_pg_sessions_concurrency.py` via `MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:18433/maistro` against the soak DB `maistro-soak-pg`, already at alembic head `062` on arrival | **46 passed, 0 skipped** |
| Full `packages/maistro-rsi/tests/` | **1,624 passed, 4 skipped** (byte-for-byte the round 71 count) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| `scripts/check-shipped-surface-truth.py` / `scripts/check-doc-links.py` | Matrix complete / 0 broken relative links |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (base `4aa68edc0b6b` == dispatch base, candidate `15fbb0c2ea5a`) | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` **with CI's exact invocation (no positional args, quality.yml:852)** | 137/137 C-or-worse blocks banked. Procedural note for future rounds: passing `packages/*/src` explicitly (as the vulture gate does) makes the radon script scan `*/third_party/*` vendored trees and report 19 false "unbaselined" findings — CI passes no args and the script's default scope is authoritative. |

## Promotion replay (live gate code, this round, at HEAD)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']` — re-executed this round:

- `sustain_duration`: observed `420.09 s` vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`, compared at `:1601-1602`). `--sustain-seconds`
  (default 420, `run_soak.py:1678`) only sets the run length, never the floor
  — no override exists. The 14,400 s continuous floor exceeds this job's
  `timeout_s = 5400` (read directly from this round's `manifest.json`) with
  background execution prohibited — **no in-lane run can flip this row**.
- `exact_rc_artifact`: `{'ok': False, 'reason': 'not the exact production
  Compose image and configuration', 'topology': 'host-uvicorn-preflight'}` —
  deliberate refusal in `preflight_artifact_check()` (`run_soak.py:729-743`);
  "There is deliberately no CLI override".
- All 8 correctness gates `ok=true` in the pack, re-read this round:
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced` (`enforced_everywhere=true`),
  `lb_failover_bounded`, `replica_2_rejoined` (`rejoined=true`),
  `nonterminal_runs_after_settle` (0),
  `task_admission_availability`, `graceful_drain` (SIGTERM required, drained,
  not escalated, `drain_seconds=1.0`, `drain_5xx=0`,
  `drain_conn_errors=0`). `rss_growth`/`fd_growth` are informational
  (`ok=None`; growth 8.3%/6.8% RSS, FDs 30→38/29→35 over the shakedown).
  Kill window `5.54 s`; `duplicate_evidence.runs_sharing_one_task_run_identity
  = "0"`; `final_runs_by_status` completed=2359/cancelled=1; 49,151 requests.
- Pack provenance re-verified: `m3a-round43-shakedown.json` has a single-file
  history — added once by `215bdec8a`, never modified since; `215bdec8a^ ==
  3da4e035eb1f46093d507db0f90b131a3a8d6dbe == hashes.git_head` recorded inside
  the pack; `git merge-base --is-ancestor 3da4e035 HEAD` true.
  `docs/testing/soak/m3a-load-profile.md` present (row 1 of the issue's
  acceptance list, unchanged this capture).
- Zero drift since the evidence head on the gate surface:
  `git diff 3da4e035eb..HEAD -- scripts/soak/ tests/test_soak_promotion_gates.py`
  is empty. The only soak-adjacent drift is `deploy/scripts/backup.sh`
  (develop-side #2105 backup-permission hardening, referenced by no soak gate
  file) and develop-side `packages/maistro-rsi` path-traversal hardening in
  `promotion_review.py` `_export_patch` (no soak references anywhere in
  maistro-rsi src; unrelated subsystem).

## External pair re-derived from this round's own 69-source capture (2026-10-10T11:51Z)

- Issue #860 open, 411 comments, updated 2026-10-10T11:31:55Z; body unchanged
  (10 acceptance checklist rows, all unchecked).
- **Parent #89 open / 0 comments / updated 2026-09-22** — no release-owner RC
  designation exists in the body (re-read this round: it lists acceptance
  requirements only).
- Linked PR heads unchanged: **#1672 open draft** at `16b244414b01`
  (`draft: true` re-verified); #1567 (`d2237879`, merged `394ff842`), #1602
  (`927a9c3c`, merged `cfc515c1`), #2100 (`b950e593`, merged `7ffedbb4`) all
  closed **and merged**, no RC designation.
- Designation-regex sweep across all 69 captured sources (RC/`release
  candidate` tied to a sha via `is|at|sha|commit|=|designat*`, plus
  designation verbs): **2 hits, both prose false positives** — an age
  source-commit pin (`b8564ad`) in an open-PR body and an unrelated
  source-tree sha (`bc33b5da`) in another open-PR body. Zero actual RC
  designations.

## Verdict carried forward

NEEDS-DEEP-REVIEW stays correct and external: rows `load profile / two
replicas / exactly-once / rate limiting / kill-restart / metrics-thresholds /
findings-filed / machine-readable evidence` are proven by the round-43 pack
(8/8 correctness gates) and re-proven by the green battery at HEAD; rows
`sustained load observation window` and `soak of the exact RC artifact` remain
**UNVERIFIED pending release-owner action** (RC designation under #89 plus a
release-owner-hosted ≥14,400 s production-Compose run — 2.7× this lane's
5,400 s budget). Gate weakening is prohibited; no in-lane action can advance
them further.

Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` 17/17 green confirms). The only tree change this
round is this handoff note.
