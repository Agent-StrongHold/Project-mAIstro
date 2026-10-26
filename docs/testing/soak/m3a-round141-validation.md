# #860 round 141 — fresh battery re-execution and external-blocker re-verification at dispatched head `2ecd0645e`

- Dispatched head: `2ecd0645ee48c712cd3c9d4a21353a67d20cdd88` (branch
  `auto-860`, base `ab8b3737fa64f8d840f421ef87ca506c509444ff`); the dispatched
  head **is** the round-140 record commit, `git status --porcelain` empty at
  start.
- Job: `/home/dev/maistro/jobs/3d28e9446cf04db0ad316179efc3c8da`
  (**no `check-*.log` files exist in the job directory** — the driver executed
  no deterministic checks; `events.jsonl` is the worker session's own log), so
  every check below was executed by the worker at this head. Nothing was taken
  on trust from round 140 or any earlier record.
- Previous block to resolve: round 140 **BLOCKED** (external prerequisites for
  criterion 8). Resolution attempt below — the block is external and stands;
  **one change since round 140**: the develop ref moved one commit further
  (test-only), recorded under develop ref-state.

## Fresh deterministic battery (all executed this round, at this head)

| Check | Command | Outcome |
| --- | --- | --- |
| Stale verifier failure `98a11313/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`) | `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — 11th consecutive non-reproduction at this head |
| Soak promotion-gate contract | `uv run pytest tests/test_soak_promotion_gates.py -q` | **72 passed** |
| `.gitleaksignore` + prod-stack boot contracts | `uv run pytest tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **16 passed** |
| Concurrency backpressure 429 probe | `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **1 passed** |
| Lint | `uv run ruff check .` | **clean** (all checks passed) |
| Format | `uv run ruff format --check .` | **3301 files already formatted** |
| Suite inventory gate | `uv run python scripts/check-suite-inventory.py` | **ok: 17 suite(s) match the recorded inventory** |
| Vulture per-identity ledger (CI's exact arguments) | `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | **rc=0: 1322 reviewed identities = 1322 findings, base `ab8b3737fa64`, candidate `2ecd0645ee48`, ledger unamended** |

## Meaningful-test spot checks behind the acceptance criteria (executed this round)

- Rate limiting under concurrency (criterion 5): `uv run pytest
  packages/maistro-server/tests/api/test_rate_limit.py -q` — **26 passed**
  (identity-keyed enforcement per closed #842).
- Exactly-once occurrence claims (criterion 4): `uv run pytest
  packages/maistro-core/tests/runs/test_spine_conformance.py -k
  "occurrence_claim" -q` — **2 passed, 1 skipped**; and
  `TestRecoverySeesTheRunStoreBeforeThePolicy::test_two_tickers_consuming_one_occurrence_count_it_once`
  — **1 passed** (two concurrent tickers → `runs_so_far == 1`). The PG-backed
  counterpart `test_pg_admission.py::test_two_admitters_concurrently_claim_each_due_occurrence_once`
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
- Develop ref-state re-derived: explicit
  `refs/remotes/origin/develop` = `07fac4abd807bab225e555efa200994811bd6c4a`
  — **moved by one commit since round 140** (`369ab9add` → `07fac4abd`,
  `#2141` landing 2026-10-17 18:45Z, after round 140's 19:07Z capture basis
  was re-captured here at 19:28–19:29Z). The increment over the already-known
  docstring-only `369ab9add` adds exactly two files
  (`git diff --stat 369ab9add..07fac4abd`): an inventory note and
  `packages/maistro-core/tests/runs/test_attempt_cancellation_cause_codec.py`
  (+568) for #1885 — **no production `packages/*/src` change and no
  `scripts/soak/` change** (the only production delta vs the lane base
  remains the `protocols.py` docstring fix in `369ab9add`). Still **not
  contained in HEAD** (`git merge-base --is-ancestor` exits non-zero).
  Disposition unchanged: not merged, to preserve the round-109 pack
  byte-identity binding; flagged for the release integrator together with
  `369ab9add`.

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
  is no CLI override), and the CLI exits 1 on any failed gate
  (`scripts/soak/run_soak.py:1763`).
- Raw pack re-inspected under exact key paths this round:
  `thresholds.checks` — `graceful_drain {SIGTERM, drained, drain_seconds 1.0,
  drain_5xx: 0, escalated: false, required: true, ok}`,
  `lb_failover_bounded {observed 0 in 6.58 s window vs 4320.0 budget, ok}`,
  `replica_2_rejoined: true`, `nonterminal_runs_after_settle {count 0, ok}`,
  `task_admission_availability {ratio 1.0, 2764/2764 accepted, ok}`;
  `fd_growth` r1 30→36 (max 41) / r2 29→34 (max 39); `rss_growth` 9.0% /
  7.7%; `rate_limit_enforced: true` with
  `ev.rate_limit.enforced_everywhere: true` and `enforcement_scope:
  "process-local; aggregate budget is replica count times limit"` (the
  documented #842-era limitation); top-level `exactly_once_tasks {12
  concurrent submissions, 12 delivered, 1 distinct run id, 11 duplicate
  run ids, statuses all 202, ok}`, `exactly_once_schedule_claim
  {occurrences_with_runs 1, occurrences_with_multiple_runs 0, ok}`;
  `kill_restart {SIGTERM, exit 143, drained, window 6.58 s with 735×200,
  rejoined true}`; `final_runs_by_status {completed: 2796, cancelled: 1}`;
  `nonterminal_runs: 0`; `hashes.git_head = 5a59c724a…`, `git_clean: true`,
  Postgres image pinned by digest, nginx rendered-config hash recorded;
  `profile: "M3-A multi-replica load/concurrency soak"`.

## External blockers (re-derived from this job's own capture, 2026-10-17T19:28–19:29Z)

1. **`exact_rc_artifact` — no RC artifact exists to soak.** Parent #89
   ("M3-A7 — Run RC soak and byte-equivalent final promotion") is **open with
   0 comment objects** in this job's own `dispatch-context.json` — no RC
   designated. RC PR #1672 is **open, `draft: true`, `merged: false`**, head
   `15ce4681c4d918cc37812837c9a02a49ca1db178` (matches this job's
   `linked_pr_heads`). Designating an RC is a release-owner GitHub action;
   GitHub mutations are prohibited for this lane.
2. **`sustain_duration` — no authorized ≥4 h production window.** The floor is
   14,400 s of sustained observation of the exact RC artifact. A ≥4 h
   wall-clock soak cannot execute inside a bounded worker job (background
   execution prohibited), and the soak target does not exist until blocker 1
   clears. Even an arbitrarily long run of this host-process driver still
   fails `exact_rc_artifact` by design.

Both gates fail correctly; weakening them or fabricating a pass would violate
the issue's own stop condition ("Do not convert this into a benchmark vanity
number") and the lane's no-gate-weakening rule.

## Acceptance-criteria disposition (re-confirmed)

Criteria 1, 2, 4, 6, 7, 9, 10 **MET**; 3/5 **PARTIAL** (documented
process-local rate-limit scope; sustained observation is 420 s, not ≥4 h);
8 (≥4 h exact-RC soak) **UNMET — externally blocked** via the two gates
above. Full per-criterion evidence table: `m3a-round132-validation.md`,
spot-checked against the raw pack this round (see above). No in-repo change
can move criterion 8.

## Disposition

Round 140's BLOCKED verdict stands. Every deterministic gate is green at this
head (8-check battery, suite inventory, vulture ledger with CI's exact
arguments, plus the meaningful-test spot checks for criteria 4 and 5), the
stale verifier failure is confirmed non-reproducing (11th consecutive time),
the two promotion failures fail correctly against external prerequisites no
in-repo change can satisfy, the evidence pack remains hash-bound to
byte-identical code, and the only develop drift since round 140 is one
test-only commit outside this lane's evidence surface. Verdict: **externally
BLOCKED**, not repairable here. No code changes this round; this record is
the only file touched (docs-only, no test additions — no inventory delta
required; the suite-inventory gate above confirms 17 suites unchanged).

Progress: `{checked: 15, done: 15, skipped: 0, errors: 0}` — 8-check fresh
battery, 4 meaningful-test spot checks, 3 structure checks + develop
ref-state re-derivation with the new `07fac4abd` increment inspected, live
promotion-gate re-derivation with preflight/CLI re-reads plus raw-JSON pack
verification under exact key paths, external blockers re-derived from this
job's own capture, round-140 disposition re-confirmed.
