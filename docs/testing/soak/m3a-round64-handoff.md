# Issue #860 — round 64 (job f88a5b42) independent re-validation at 8e7f78eb

**Not promotion evidence or integration approval.** This round re-executes the
deterministic battery at the dispatch head `8e7f78eb2627aa65f8e2bec2723a8478a22cb486`
(working tree clean on arrival, exactly the dispatch head) and re-derives the
terminal external pair from this round's own 69-source capture
(2026-10-10T08:21:27Z). The round-53 escalation (NEEDS-DEEP-REVIEW) remains
**external and unchanged**: acceptance rows 3 and 8 require a release-owner RC
designation under parent #89 plus a release-owner-hosted ≥14,400 s soak of the
exact production Compose artifact, neither of which any repair worker can
supply.

Prior-run facts resolved this round: the immediately preceding job `e592ed4c`
died on provider timeout (`provider_error` — "Request timed out", `checks: []`)
at this same head — nothing to salvage, no worker commits lost (HEAD is exactly
its dispatch head). This round's driver manifest again carried an **empty
`checks` list** (no `check-*.log` files exist for job `f88a5b42`), superseded
by direct full-battery execution below. The prompt's "Validation failed"
pointer again referenced job `98a11313`'s `check-3.log` — the same **stale
round-44 artifact** whose DDL-fence failure
(`test_ensure_schema_fences_ddl_behind_advisory_lock`) predates the current
head and was re-executed green this round (below). No source, test, gate,
ledger, or inventory file changed; the only artifact is this handoff note.
Inventory delta: 0 (no collected tests added or removed;
`check-suite-inventory.py` 17/17 green confirms).

## Deterministic battery executed at `8e7f78eb` (all green, this round)

| Gate | Result |
| --- | --- |
| `git rev-parse origin/develop` | `1f328be9` == this round's dispatch base. Not an ancestor of HEAD (diverged, 345 lane commits ahead / 12 develop-side behind), matching rounds 57–63: the 12 develop-side commits are the security/WIP batch whose only soak-adjacent path is `deploy/scripts/backup.sh` (re-derived this round via `git diff --name-only HEAD...origin/develop -- scripts/soak/ deploy/ tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py tests/test_release_guard.py` → `deploy/scripts/backup.sh` only); zero develop-side overlap with `scripts/soak/`. This lane's failures were provider timeouts / empty driver checks, never a sync conflict, so per the dispatch rule **no merge is mandated** |
| Stale `check-3.log` failure file: `pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 37 passed, 6 skipped — the round-44 DDL-fence failure does not reproduce at this head |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,238 files already formatted |
| `uv run pytest` over all twelve soak/contract/release-guard test files (`test_soak_promotion_gates.py`, `test_release_guard.py`, `test_check_release_consistency.py`, `test_check_promotion_surface.py`, `test_answers_parity_contract.py`, `test_build_evidence_result_contract.py`, `test_check_api_route_contracts.py`, `test_check_contract_markers.py`, `test_distribution_contract.py`, `test_gates_ran_publisher_contract.py`, `test_gitleaksignore_contract.py`, `test_prod_stack_boot_contract.py`) | 363 passed in 14.86 s (broader than the 105-test soak-only set of rounds 44–63; superset, all green) |
| `scripts/check-suite-inventory.py` | ok: 17/17 suites match the recorded inventory |
| `scripts/check-backlog-consistency.py` | OK (168 items) |
| Exact CI vulture gate `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1,323/1,323 reviewed identities banked |
| `scripts/check-radon-baseline.py` | 137/137 C-or-worse blocks banked |
| `scripts/check-doc-links.py` | Every relative markdown link resolves (0 broken) |

## Promotion replay (live gate code, this round)

`failed_promotion_checks()` (`scripts/soak/run_soak.py:744`) applied to the
round-43 pack `docs/testing/soak/evidence/m3a-round43-shakedown.json` returns
exactly `['sustain_duration', 'exact_rc_artifact']`:

- `sustain_duration`: observed `sustain_seconds = 420.09` (pack field;
  `requested_sustain_seconds = 420`) vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`run_soak.py:67`), gate read at `run_soak.py:1601-1602`. No
  env/CLI override exists: `os.environ` appears only as subprocess env
  plumbing (`env = dict(os.environ)` at `run_soak.py:197/:221`), and the
  constant has no other reference in the file.
- `exact_rc_artifact`: `ok: false`, `topology: host-uvicorn-preflight` — the
  refusal in `preflight_artifact_check` (`run_soak.py:730-743`) is deliberate
  ("deliberately no CLI override", docstring) and carries no override: this
  driver boots host processes, never the promoted Compose artifact.
- All 8 correctness gates `ok: true` (`exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `lb_failover_bounded`, `replica_2_rejoined`, `nonterminal_runs_after_settle`,
  `task_admission_availability`, and `graceful_drain` with `drain_5xx = 0`,
  `drained: true`, SIGTERM required); `rss_growth`/`fd_growth` rows are
  informational (`ok: null`).
- Pack provenance re-verified: `git log --diff-filter=A` shows the pack was
  added by exactly one commit `215bdec8a` whose **parent is the recorded
  `git_head` 3da4e035eb1f46093d507db0f90b131a3a8d6dbe**, the pack was never
  modified after that commit, and `git merge-base --is-ancestor 215bdec8a
  HEAD` → true. Soak-path drift `git diff --stat 3da4e035..HEAD --
  scripts/soak/ deploy/ tests/test_soak_promotion_gates.py` → empty:
  runtime/gate/deploy trees byte-identical since the evidence head.

## External pair re-derived from this round's own capture

- Parent #89 "M3-A7 — Run RC soak and byte-equivalent final promotion":
  **open, 0 comments**, updated 2026-09-22T22:46:14Z — no RC designation
  exists at the promotion authority.
- Issue #860: open, updated 2026-10-10T08:03:15Z.
- PR #1672 (this issue's soak implementation PR): **open draft** at
  `16b244414b01` — not merged, not a designation.
- PRs #1567, #1602, #2100: all merged; none designates an RC artifact.
- Designation-language regex (`RC[-\s]?\d|release[-\s]candidate`,
  case-insensitive) across all captured #860 comment records in the 69-source
  dispatch capture: **0 hits**.

## Why neither failing row is reachable in-lane

Satisfying `sustain_duration` requires one continuous ≥14,400 s soak of the
exact RC artifact; the lane job budget is 5,400 s and background execution is
prohibited, so no in-lane run can flip the row. Satisfying `exact_rc_artifact`
additionally requires a release-owner RC designation under parent #89 (still
open, 0 comments) plus a production Compose runner — a governance act outside
this lane's authority. Weakening either gate is prohibited. The escalation
routing (NEEDS-DEEP-REVIEW) is therefore unchanged.
