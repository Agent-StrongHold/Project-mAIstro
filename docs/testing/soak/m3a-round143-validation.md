# #860 round 143 — fresh battery re-execution and external-blocker re-verification at dispatched head `1aaf9ac21`

- Dispatched head: `1aaf9ac21ac0366c3536415e7013beaf2b3b5cbb` (branch
  `auto-860`, base `ab8b3737fa64f8d840f421ef87ca506c509444ff`); the dispatched
  head **is** the round-142 record commit, `git status --porcelain` empty at
  start.
- Job: `/home/dev/maistro/jobs/94c975b1afa4496e9e383cf88579b1f6`
  (**no `check-*.log` files exist in the job directory** — the driver executed
  no deterministic checks), so every check below was executed by the worker at
  this head. Nothing was taken on trust from round 142 or any earlier record.
- Immediate prior attempt `55f520d87b3642e5b56906cd51550c46` (same head) died
  of an upstream **provider 429 rate limit** before running any check
  (`result.json`: `failure_kind: "rate_limited"`, `checks: []`) — no
  validation evidence was lost or contradicted; this round re-executes the
  full battery.
- Previous block to resolve: round 142 **BLOCKED** (external prerequisites for
  criterion 8). Resolution attempt below — the block is external and stands,
  with **one new external development**: the develop ref **moved** for the
  first time since round 132 (re-derived below).

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — 13th consecutive non-reproduction at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint | `uv run ruff check .` | **clean** (all checks passed) |
| Format | `uv run ruff format --check .` | **3301 files already formatted** |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |
| Vulture per-identity ledger (CI's exact arguments) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **rc=0: 1322 reviewed identities = 1322 findings, base `ab8b3737fa64`, candidate `1aaf9ac21ac0`, ledger unamended** |

## Meaningful-test spot checks behind the acceptance criteria (executed this round)

- Rate limiting under concurrency (criterion 5): `uv run pytest
  packages/maistro-server/tests/api/test_rate_limit.py -q` — **26 passed**
  (identity-keyed enforcement per closed #842).
- Exactly-once occurrence claims (criterion 4): `uv run pytest
  packages/maistro-core/tests/runs/test_spine_conformance.py -k
  "occurrence_claim" -q` — **2 passed, 1 skipped**; and
  `packages/maistro-core/tests/scheduling/test_admission.py::TestRecoverySeesTheRunStoreBeforeThePolicy::test_two_tickers_consuming_one_occurrence_count_it_once`
  — **1 passed** (two concurrent tickers → occurrence counted once). The
  PG-backed counterpart
  `test_pg_admission.py::test_two_admitters_concurrently_claim_each_due_occurrence_once`
  exists in-tree; the two-replica end-to-end equivalent is demonstrated in the
  round-109 pack (`exactly_once_schedule_claim`, re-verified below).

## Structure checks

- Develop base `ab8b3737fa64` is an ancestor of HEAD
  (`git merge-base --is-ancestor` exit 0).
- `git diff --numstat ab8b3737fa64..HEAD -- quality/` is **0 rows**: the
  vulture ledger is untouched (confirmed by the rc=0 gate above; no
  CI-repair amendment needed or made).
- `git diff 5a59c724a..HEAD -- packages/ scripts/soak/` is **0 rows**:
  production and soak-gate code are byte-identical to the evidence-pack-bound
  head `5a59c724a20ef1241d57c048df90758f2c2e1e25`, so the round-109 pack
  remains a valid observation of the code at this head. Only round-record
  documentation differs.
- **Develop ref-state CHANGED this round**: explicit
  `refs/remotes/origin/develop` = `6c739f054f99db5547c1e12d96ea6c6467232a7d`,
  advanced from round 142's `07fac4abd807bab225e555efa200994811bd6c4a` by
  **3 commits** — `498ff93a3` fix(core): fence recovery claims before
  reconciliation (#837, #2144), `7ced47d8c` fix(tasks): validate canonical
  cancellation receipt projection (#1339, #2143), and `6c739f054` chore(quality):
  authorize design_coverage fall to measured 39.641 (two-merge rule, #2145);
  `07fac4abd` verified as ancestor of the new tip. Still not contained in HEAD
  (`git merge-base --is-ancestor` exits non-zero); disposition unchanged: not
  merged, to preserve the round-109 pack byte-identity binding; flagged for
  the release integrator. Note the direction of the implication: #2144/#2143
  are production-code changes on develop, so under criterion 8's own rule
  ("any code/runtime-config change requires a new soak") the eventual RC soak
  must run on a candidate that includes them — this reinforces, and cannot be
  satisfied by, the blocked-gate disposition below.

## Promotion gates re-derived live (not read from any doc)

`failed_promotion_checks(m3a-round109-shakedown.json)` executed at this head
by importing `scripts/soak/run_soak.py`:

- Result: `['sustain_duration', 'exact_rc_artifact']` — exactly the two
  externally blocked gates, nothing else.
- `sustain_duration`: observed 420.05 s vs `PROMOTION_MIN_SUSTAIN_SECONDS =
  14_400` (`scripts/soak/run_soak.py:69`) — fails correctly against the ≥4 h
  floor.
- `exact_rc_artifact`: `preflight_artifact_check`
  (`scripts/soak/run_soak.py:744`) returns `ok: false` unconditionally by
  design ("not the exact production Compose image and configuration"; there
  is no CLI override), and the CLI exits 1 on any failed gate.
- Raw pack re-inspected under exact key paths this round:
  `thresholds.checks` — `graceful_drain {SIGTERM, drained, drain_seconds 1.0,
  drain_5xx: 0, escalated: false, required: true, ok}`,
  `lb_failover_bounded {observed 0 5xx+conn errors in 6.58 s window vs 4320.0
  budget, ok}`, `replica_2_rejoined: true`,
  `nonterminal_runs_after_settle {count 0, ok}`,
  `task_admission_availability {ratio 1.0, 2764/2764 accepted, 0
  backpressured, 0 unretryable 429, ok}`;
  `thresholds.checks.fd_growth` r1 30→36 (max 41) / r2 29→34 (max 39);
  `thresholds.checks.rss_growth` r1 +9.0% / r2 +7.7%;
  `rate_limit` per-replica direct probes with enforced
  `x-ratelimit-remaining: 0` headers (documented #842-era process-local
  scope); top-level
  `exactly_once_tasks {12 concurrent submissions, 12 delivered, 1 distinct
  run id, 11 duplicate run ids, statuses all 202, ok}`,
  `exactly_once_schedule_claim {occurrences_with_runs 1,
  occurrences_with_multiple_runs 0, admission_failures [], ok}`;
  `kill_restart {SIGTERM, exit 143, drained, killed 05:20:00Z, rejoined
  true}`; `final_runs_by_status {completed: 2796, cancelled: 1}`;
  `nonterminal_runs: 0`; `hashes.git_head = 5a59c724a…`, `git_clean: true`,
  `profile: "M3-A multi-replica load/concurrency soak"`.

Both gates fail correctly; weakening them or fabricating a pass would violate
the issue's own stop condition ("Do not convert this into a benchmark vanity
number") and the lane's no-gate-weakening rule.

## External blockers (re-derived from this job's own capture, 2026-10-17T20:33Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comment objects** in this job's own `dispatch-context.json` — no RC
   designated. RC PR #1672 is **open, `draft: true`, `merged: false`**, head
   `15ce4681c4d918cc37812837c9a02a49ca1db178` (matches this job's
   `linked_pr_heads`). Designating an RC is a release-owner GitHub action;
   GitHub mutations are prohibited for this lane.
2. **`sustain_duration` — no authorized ≥4 h production window.** The floor is
   14,400 s of sustained observation of the exact RC artifact. A ≥4 h
   multi-replica production-soak window is an infrastructure/release-owner
   authorization no in-repo change can create, and the soak must target the
   RC artifact from blocker 1 — the two gates are coupled.

## Acceptance-criteria disposition (re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented
process-local rate-limit scope; sustained observation is 420 s, not ≥4 h);
8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two gates
above. Full per-criterion evidence table: `m3a-round132-validation.md`,
spot-checked against the raw pack this round (see above). No in-repo change
can move criterion 8.

## Disposition

Round 142's BLOCKED verdict stands. Every deterministic gate is green at this
head (8-check battery, suite inventory, vulture ledger with CI's exact
arguments, plus the meaningful-test spot checks for criteria 4 and 5), the
stale verifier failure is confirmed non-reproducing (13th consecutive time),
the two promotion failures fail correctly against external prerequisites no
in-repo change can satisfy, and the evidence pack remains hash-bound to
byte-identical code. This round's only state movement is external (develop
advanced 3 commits; recorded above with its criterion-8 implication); the
in-repo tree is unchanged except this record (docs-only, no test additions —
no inventory delta required; the suite-inventory gate above confirms 17
suites unchanged).

Progress: `{checked: 16, done: 16, skipped: 0, errors: 0}` — 8-check fresh
battery, 4 meaningful-test spot checks, 3 structure checks + develop
ref-state re-derivation (**changed** `6c739f054f99`, +3 commits enumerated),
live promotion-gate re-derivation with preflight re-read plus raw-JSON pack
verification under exact key paths, external blockers re-derived from this
job's own capture, round-142 disposition re-confirmed.
