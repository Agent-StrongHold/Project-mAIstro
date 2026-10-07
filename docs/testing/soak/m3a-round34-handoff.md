# Issue #860 round-34 independent revalidation (job a49f66d0)

- Branch tip at start and end: `1c2f5b863d4b5fd9f3ea36ee2a7339b5f92deafa` (docs-only round-33
  handoff on top of `dbb62e2c7`; `dbb62e2c7..HEAD` diff is exactly one new doc file, 0
  production files). `c4f45b309` remains the harness-code tip every evidence pack is hash-bound to.
- Prior failed validation artifact (`job 98a11313`, `check-3.log`):
  `packages/maestro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`
  asserted `24 == 21` DDL statements. **Re-run at this tip: that file passes (37 passed, 6
  skipped)** — the failure predates the current tree and is stale.
- Develop sync: `origin/develop` has moved +5 commits past fork point `df00785bb` (`0df275362`
  PR-closure keywords, `51679882b` registry test paths, `7dbec238d` #753 turing evidence,
  `9ad158230` registry front-matter id, `30a30d10e` M9-A2 extension context). Overlap with this
  branch's 246 changed files vs develop: **empty** — no develop-sync conflict; no merge required.

## Deterministic gates re-executed this round at `1c2f5b863` (not trusted from round 33)

| Gate (CI argv) | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3094 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suites match; 0 byte-identical test files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1332 reviewed == 1332 findings, rc=0 |
| `uv run mypy <7 CI src dirs>` | Success: no issues in 846 source files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 93 passed, 6 skipped |

## Evidence packs re-read at this tip (not trusted from prior rounds)

`docs/testing/soak/evidence/m3a-round30-shakedown.json` (git_head=`c4f45b309…`, git_clean=true,
sustain 420.08 s, 47,175 requests):
- exactly-once: 12 concurrent duplicate submissions → 11 duplicate ids collapsed, 1 distinct run;
  schedule-occurrence race across 2 processes → 1 occurrence, 1 run, 0 multi-run, ok=true both.
- rate limiting: 800-request direct probes against **both** replicas, authenticated and
  unauthenticated: 429 + Retry-After + x-ratelimit-* headers; `enforced_everywhere=true`.
- kill/restart: SIGTERM, drain 1.0 s, 0 drain 5xx, 0 conn errors, replica 2 rejoined;
  0 non-terminal runs after settle (final: completed=2265, cancelled=1).
- round-30 metrics trace `m3a-round30-shakedown-metrics.jsonl`: 212 samples spanning the full
  sustain; pg_connections 5–13 (S3 pool budget: no saturation, no sustained pressure),
  pg_waiting_locks = 0 throughout, `pg_probe_ms` wire-latency samples present, per-replica fds
  30→42 max, RSS 182→195 MB (≤6.6% growth), `runs_by_status` spine depth sampled — AC6 metric
  coverage re-verified against the thresholds table in `m3a-load-profile.md`.
- The **only** failed promotion checks remain `sustain_duration` (observed 420.08 vs floor
  14,400 s, `run_soak.py:67`) and `exact_rc_artifact` (`run_soak.py:686`,
  "deliberately no CLI override") — both by design; module docstring states the host-process
  preflight cannot sign promotion.

## Issue-comment re-scan (capture 2026-10-07T01:05Z, 168 comments)

Latest activity through `2026-10-07T00:50:05Z` is maistro-progress bot markers only (started /
blocked). Regex sweep over all 168 comment bodies for RC / release-candidate / RC-designation
phrasing: **0 matches** — the AC8 release-owner RC designation remains absent.

## Acceptance status (re-evidenced this round; unchanged in substance from round 33)

- AC1 load profile: `docs/testing/soak/m3a-load-profile.md` — proven.
- AC2 >=2 replicas: round-30 pack `replica_boot_seconds=2.5`, per-replica logs committed — proven at harness grade.
- AC3 sustained load: 420.08 s shakedown (47,175 req, 0 5xx, 0 non-terminal runs, fd/RSS bounded) + round-8 1200 s production stack — **14400 s promotion floor NOT met (external)**.
- AC4 exactly-once: re-read this round — proven.
- AC5 rate limiting per-replica direct probes: re-read this round — proven; N× aggregate is #842 policy.
- AC6 metrics+thresholds: 212-sample trace re-verified against the load-profile thresholds — proven.
- AC7 kill/restart: re-read this round — proven at harness grade.
- AC8 exact-RC soak >=14400 s: **NOT MET, externally blocked** — no RC designation through capture, and a >4 h production-Compose run exceeds lane budget/authority. Weakening either gate would falsify evidence, not satisfy it.
- AC9 findings classified external in round handoffs; GitHub filing prohibited in-lane.
- AC10 evidence tied to hashes: re-read this round — proven.

Terminal for lane authority: identical to round 33. Both remaining failed promotion checks
require a release-owner RC designation plus a >=4 h production-Compose soak that no 90-minute
lane can host. No in-lane repair remains.
