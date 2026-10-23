# Issue #860 — bounded repair a2fea83b

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting HEAD `3b2fc09263d90b6725d34c909f37cd351e1e4480`,
  base `d592654aca614fb74467487542693c46b3aa30fb`; clean on arrival.
- This round's job directory supplied **no `check-*.log` files**; the
  prior-failure reference (`98a11313…/check-3.log`,
  `test_ensure_schema_fences_ddl_behind_advisory_lock` expecting 21 DDL calls
  and observing 24) was captured against an older head and re-executed here
  rather than trusted.
- The immediately preceding attempt (`a2e6ccca…`) died on a provider timeout,
  not a validation failure, so this round re-ran the full battery from zero.
- Candidate edits limited to this report. No test addition (no inventory
  delta), no ledger amendment (exact vulture gate produced no unbanked
  identities), no remote mutations.

## Deterministic gates re-executed at this head (all green)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | **37 passed, 6 skipped** — the prior check-3 schema-fence failure (24 vs 21) is dead at this head |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run mypy` (10 CI src dirs per `ci.yml:118–130`) | Success: no issues in 1,027 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; 1,326 findings = 1,326 reviewed identities, unclassified 0, never_allowlist 0 → no ledger amendment justified |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -q` | **100 passed** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-merge-markers.py` | ok: no conflict markers |
| `bash scripts/verify-monorepo-layout.sh` | ok |

## Develop-sync assessment (no merge required)

Branch trails `origin/develop` by 23 commits. The lane merge condition
("if it was a develop sync conflict") does not hold: `comm` of the two
name-only diffs (`HEAD...origin/develop` vs base…HEAD) shows **zero file
overlap**, and the prior check-3 failure does not reproduce. The 23 divergent
commits are research/epic WIP plus unrelated harnesses; no soak, learnings, or
promotion-gate file is touched on both sides.

## Acceptance re-derived from raw evidence at this head

- Live import of `failed_promotion_checks()` from `scripts/soak/run_soak.py`
  against the newest evidence pack
  (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
  `['sustain_duration', 'exact_rc_artifact']`; records:
  `minimum_seconds=14400, observed_seconds=420.08, ok=false` and
  `topology="host-uvicorn-preflight", ok=false`.
- Full gate read of that pack: 8 further gates pass (exactly-once schedule
  occurrence, exactly-once task admission, graceful drain, lb failover
  bounded, replica 2 rejoined, nonterminal runs after settle, rate limit
  enforced, task admission availability ≥ 0.99). `fd_growth`/`rss_growth`
  are recorded observables, not required gates.
- `preflight_artifact_check` (`scripts/soak/run_soak.py:730–741`) deliberately
  has no CLI override: an exact-RC runner needs observed image/configuration
  evidence. This is anti-fabrication design, not a defect to repair.
- Fresh RC-designation sweep of this round's capture (702 items across the
  issue body/comments/timeline, captured 2026-10-09T05:50Z — newer than the
  prior round's 316-comment sweep): regex
  `release[- ]candidate|\bRC\b|designat|exact[- ]RC|four[- ]hour|4[- ]?hour|14400`
  → **0 matching items**. No release owner has designated an RC.

## Terminal condition (unchanged from rounds 33–39, freshly verified)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action:

1. `exact_rc_artifact` requires the exact production Compose image/config of a
   release candidate no release owner has designated (0/702 items at this
   round's fresh capture).
2. `sustain_duration` requires ≥ 14,400 s on that exact RC artifact; any run
   without gate (1)'s designation fails it by construction, and a bounded
   attempt cannot host a 4-hour soak.

Everything a lane can execute is green at `3b2fc0926`. Resolution requires a
release-owner decision: designate the RC and host the ≥ 4 h
production-Compose soak on its exact artifact/configuration, or explicitly
rule on the preflight evidence's sufficiency for the M3 promotion decision.

No tree change was made this round other than this report; no test inventory
delta (no tests added or removed); no `quality/*.json` edit (exact vulture
scan is clean); no GitHub mutation, merge, reset or destructive cleanup.
