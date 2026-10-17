# Issue #860 round-35 independent revalidation (job d794b4f1)

- Branch tip at start and end: `e1ad14184339b8e51e2f7d4914963a8a6ee4765f` (docs-only round-34
  handoff on top of `1c2f5b863`; `c4f45b309fd622f2e8a4b315dad35e721d81aad3` remains the
  harness-code tip every evidence pack is hash-bound to. `git diff --name-only c4f45b309..HEAD`
  contains zero non-docs paths — 12 files, all under `docs/`).
- Prior block resolved: the driver-recorded failure (`job 98a11313`, `check-3.log`) was
  `test_ensure_schema_fences_ddl_behind_advisory_lock` asserting `24 == 21` DDL statements.
  Re-executed this round at this tip: **PASSED** (explicitly, by node id, and as part of the
  110-passed targeted run below). The tree's `expected_ddl` list already covers the three
  Gauntlet audit columns (`validated_evaluator_version`, `validation_run_ids`,
  `validation_content_hash`) emitted by `_EPISTEMIC_COLUMNS` — the failure predates the
  current tree and is stale. The immediately prior round's block was a provider timeout
  (`result.json`: `failure_kind: provider_error`), not a tree defect.
- Develop sync: `origin/develop` gained `1df433bf5` (PR #2030, NodeRun same-status evidence
  routing: `docs/adr/1334-legacy-evidence-migration.md`,
  `packages/maistro-core/src/maistro/graph/durable_runs/execution_store.py`, its test) past
  fork point `df00785bb`. `comm` of develop's new files vs this branch's changed files:
  **empty** — no develop-sync conflict; no merge required this round.

## Deterministic gates re-executed this round at `e1ad1418` (not trusted from round 34)

| Gate (CI argv) | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3094 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match; 0 byte-identical test files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1332 reviewed identities -> 1332 findings, rc=0 |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items, all statuses/gaps/citations resolve |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `uv run mypy <10 CI src dirs, ci.yml argv>` | Success: no issues found in 1000 source files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 110 passed, 6 skipped |

## Evidence re-verified against files at this tip (not trusted from round 34)

- `m3a-round30-shakedown.json` `hashes`: `git_head = c4f45b309…`, `git_clean = true`,
  `git_status_sha256`/`git_diff_sha256` = empty-tree hash — the pack is bound to the exact
  harness-code tip, and no production file has changed since.
- Promotion gates evaluated live by importing `scripts/soak/run_soak.py` and calling
  `failed_promotion_checks()` on the packs: round-30 shakedown -> `['sustain_duration',
  'exact_rc_artifact']` (the two deliberately-open checks: observed 420.08 s vs 14,400 s
  floor, and the host-preflight that cannot sign `exact_rc_artifact`). Round-5 final also
  fails `rate_limit_enforced`, which is why round-30 is the promotion-grade pack. Weakening
  either gate would falsify evidence, not satisfy it.
- AC6 metric coverage re-computed from the raw `m3a-round30-shakedown-metrics.jsonl` trace
  (212 samples): `pg_connections` 5–13, `pg_waiting_locks` max 0, replica fds max 42/40,
  RSS MB 178→191 / 124→188 (bounded growth, no leak signature), `driver_loop_lag_ms` max
  2.03, `pg_probe_ms` max 8.19, process groups fully classified (`unclassified_pids` never
  populated) — all inside the `m3a-load-profile.md` thresholds.

## Acceptance status (unchanged in substance from round 34)

- AC1 load profile `m3a-load-profile.md` — proven.
- AC2 ≥2 replicas — proven at harness grade (round-30 pack `replica_boot_seconds=2.5`,
  per-replica logs committed).
- AC3 sustained load — 420.08 s shakedown + round-8 1200 s production stack observed pool,
  queue, fd/RSS, shutdown behavior; **14,400 s promotion floor NOT met (external)**.
- AC4 exactly-once admission (duplicate submissions, schedule-occurrence race across 2
  processes) — proven.
- AC5 rate limiting under concurrency, direct per-replica + through-LB probes — proven;
  N× aggregate is #842 policy.
- AC6 metrics + explicit thresholds — proven (recomputed this round, above).
- AC7 kill/restart graceful drain/fencing/recovery — proven at harness grade.
- AC8 exact-RC ≥4 h soak — **NOT MET, externally blocked**: no release-owner RC designation
  exists (regex sweep of all 168 issue comments: 0 RC/release-candidate matches, round 34),
  and a ≥4 h production-Compose soak exceeds lane budget/authority.
- AC9 findings filed/reclassified — external-classified in round handoffs; GitHub filing
  prohibited in-lane.
- AC10 machine- and human-readable evidence tied to exact hashes — proven.

Terminal for lane authority: identical to rounds 33/34. The two remaining failed promotion
checks require a release-owner RC designation plus a ≥4 h production-Compose soak no lane
of this duration can host. No in-lane repair remains; the tree is green on every gate a
lane can execute.
