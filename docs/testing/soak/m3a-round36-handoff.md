# Issue #860 round-36 independent revalidation (job 2d1027f9)

- Branch tip at start and end: `653620201a969dda4f9341465d7b42f81d33384b` — the round-35
  docs tip `2b226d785` plus the develop merge of `1df433bf5` (PR #2030) that round 35
  recorded as pending ("no merge required this round"). The driver performed that merge;
  it landed conflict-free (single merge commit, clean tree, no resolution markers).
- **Delta this round — develop drift is no longer docs-only.** Round 35 stated
  "no production file has changed since `c4f45b309`". True at `e1ad1418`; **false at this
  head**: `git diff --name-only c4f45b309..HEAD` now contains 30 non-docs paths
  (extensions SDK per ADR-104/#950, `graph/durable_runs/execution_store.py` per #1334,
  registry test-path resolution per #2023, `_vulture_whitelist.py`,
  `quality/contract-markers-baseline.json`, CI gate workflows, wheel-import checker).
  Under the artifact-identity contract in `m3a-load-profile.md` and AC8's rule that any
  code change requires a new soak, the eventual promotion-signing soak must postdate this
  merge. This strengthens the standing external block; it does not change which checks
  fail.
- Prior block resolved: the "BLOCKED" flag from the immediately prior run was a provider
  timeout (`result.json`: `failure_kind: provider_error`, model request timed out) with a
  clean tree at the exact expected head — not a tree defect. The older driver failure
  (`job 98a11313`, `check-3.log`, `test_ensure_schema_fences_ddl_behind_advisory_lock`
  asserting `24 == 21`) was re-executed by node id this round: **37 passed, 6 skipped**;
  the tree's `expected_ddl` list already covers the Gauntlet columns.

## Deterministic gates re-executed this round at `653620201a` (not trusted from round 35)

| Gate (CI argv) | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3105 files already formatted |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match; 0 byte-identical test files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1332 reviewed identities -> 1332 findings, rc=0 |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items, all statuses/gaps/citations resolve |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `uv run python scripts/check-contract-markers.py` | OK: every contract claim evidenced or reasoned (merge touched the baseline) |
| `uv run mypy <10 CI src dirs, ci.yml argv>` | Success: no issues found in 1007 source files (+7 vs round 35: extension modules) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | 110 passed, 6 skipped |
| `uv run pytest packages/maistro-core/tests/extensions packages/maistro-core/tests/graph/durable_runs tests/tools/registry tests/test_check_closure_targets.py -q` (merge-touched areas) | 675 passed |
| `uv run pytest packages/maistro-registry/tests packages/maistro-core/tests/graph/durable_runs -q` (merge-touched areas) | 650 passed, 42 skipped |

## Evidence re-verified against files at this tip (not trusted from round 35)

- `m3a-round30-shakedown.json` `hashes`: `git_head = c4f45b309…`, `git_clean = true`,
  `git_status_sha256`/`git_diff_sha256` = empty-tree hash — the pack is bound to the exact
  harness-code tip it was produced from. Post-merge production drift (above) is a new
  fact recorded here, not a defect in the pack.
- Promotion gates evaluated live by importing `scripts/soak/run_soak.py` and calling
  `failed_promotion_checks()`: round-30 shakedown -> `['sustain_duration',
  'exact_rc_artifact']`; round-5 final -> `['rate_limit_enforced', 'sustain_duration',
  'exact_rc_artifact']` (why round-30 is the promotion-grade pack). Identical to round 35;
  weakening either gate would falsify evidence, not satisfy it.
- AC6 metric coverage re-computed from the raw `m3a-round30-shakedown-metrics.jsonl`
  trace (212 samples): `pg_connections` 5–13, `pg_waiting_locks` max 0,
  `driver_loop_lag_ms` max 2.03, `pg_probe_ms` max 8.19; pack-threshold fd growth
  30→35 (max 42/40), graceful drain `drained=true`, `drain_5xx=0` — all inside the
  `m3a-load-profile.md` thresholds.
- Spot re-reads of the round-30 pack: `exactly_once_tasks` 12 concurrent submissions →
  1 distinct run id (11 duplicates rejected), `exactly_once_schedule_claim` true,
  per-replica rate-limit probes show `429` + `retry_after` + `x-ratelimit-remaining: 0`,
  `kill_restart` shows SIGTERM → drained (0 5xx, 0 conn errors, 7.03 s window) → rejoined.

## Acceptance status (unchanged in substance from round 35; drift note under AC8)

- AC1 load profile `m3a-load-profile.md` — proven (thresholds written before results).
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
- AC8 exact-RC ≥4 h soak — **NOT MET, externally blocked**, and now additionally gated on
  the post-merge artifact: no release-owner RC designation exists (regex sweep of all 168
  issue comments: 0 RC/release-candidate matches, round 34), and the merge at this head
  changed production code, so the future promotion soak must run on an artifact at or
  after `653620201a`'s lineage. A ≥4 h production-Compose soak exceeds lane
  budget/authority.
- AC9 findings filed/reclassified — external-classified in round handoffs; GitHub filing
  prohibited in-lane.
- AC10 machine- and human-readable evidence tied to exact hashes — proven.

Terminal for lane authority: identical to rounds 33/34/35. The two remaining failed
promotion checks require a release-owner RC designation plus a ≥4 h production-Compose
soak no lane of this duration can host — now on a post-merge artifact. No in-lane repair
remains; the tree is green on every gate a lane can execute at the current head.
