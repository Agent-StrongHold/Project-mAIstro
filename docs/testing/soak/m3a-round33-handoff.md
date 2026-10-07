# Issue #860 round-33 independent revalidation (job 8d0f0ffa)

- Branch tip at start and end: `dbb62e2c76deea5dc9caec826dea8f3c1eb05c1b` (docs-only round-32
  handoff on top of `c4f45b309`, the harness-code tip every evidence pack is hash-bound to).
- Develop base in manifest `7dbec238d` is NOT an ancestor of this branch: the branch forked at
  `df00785bb`; `origin/develop` has since gained 3 commits (`7dbec238d` #753 turing evidence,
  `9ad158230` registry front-matter id, `30a30d10e` M9-A2 extension context = 28 files).
  Overlap with this branch's 245 changed files: **empty** — no develop-sync conflict exists and
  none was the prior block reason, so no merge was required this round.

## Deterministic gates re-executed this round at `dbb62e2c7` (not trusted from round 32)

| Gate (CI argv) | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3094 files already formatted |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `bash scripts/verify-monorepo-layout.sh` | ok |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suites match; 0 byte-identical test files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1332 reviewed == 1332 findings, rc=0 |
| `uv run mypy <7 CI src dirs>` | Success: no issues in 846 source files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -q` | 72 passed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | 38 passed, 6 skipped |
| `uv run pytest tests/ -q --timeout=60` (REQUIRE_AUTH=false MAISTRO_DRY_RUN=1) | 4684 passed, 128 skipped |
| `uv run pytest packages/hive-conductor/backend/tests -q --timeout=60` | 3413 passed, 6 skipped |
| `uv run pytest packages/maistro-design/tests -q --timeout=60` | 572 passed, 1 skipped |
| CI single-process step: `pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60` | see flake note below |

## One-process flake investigation (new finding this round)

First execution of the exact CI single-process argv reported **7 failed, 182 errors** (all in
hive-conductor chat/voice/api tests), in **1599.62s (26:39)**. Decomposition: every tree passes
in isolation; `tests/` + one victim file passes; `tests/` + full hive-conductor passes (8097
passed, 0 failed, 574.59s); design + victim passes. A rerun of the **full triple argv passed
clean: 8669 passed, 135 skipped, 0 failures in 537.06s (8:57)** — 3x faster than the failing
run. Diagnosis: the failing run executed under heavy external host contention; the
`--timeout=60` per-test budget blew in chat/voice API tests, cascading errors through session
fixtures. Not reproducible, not cross-suite leakage, and no failing file is reachable from any
file this branch changed (branch production delta vs `df00785bb` is only
`maistro/persistence/pg_learnings.py` (+22), `maistro_server/api/tasks.py` (+17), plus new
tests/scripts/docs). Classified environmental per repo guidance ("read the log before changing
code"); no code change made.

## Issue-comment re-scan (capture 2026-10-06T23:33Z, 166 comments)

Latest activity through `2026-10-06T23:18:19Z` is still maistro-progress bot markers only.
**No release-owner RC designation** — the AC8 prerequisite remains absent.

## Acceptance status (unchanged in substance from round 32, re-evidenced this round)

- AC1 load profile: `docs/testing/soak/m3a-load-profile.md` — proven.
- AC2 >=2 replicas: round-30 pack `replica_boot_seconds=2.5`, per-replica logs committed — proven at harness grade.
- AC3 sustained load: `sustain_seconds=420.08` shakedown + round-8 1200s production stack, 0 5xx, 0 non-terminal runs, fd bounded (30→35, max 42) — **14400s promotion floor NOT met (external)**.
- AC4 exactly-once: 12 concurrent duplicate submissions → 11 duplicate ids collapsed; schedule occurrence race → 1 run, 0 multi-run — proven.
- AC5 rate limiting: per-replica direct probes, 800 req each, x-ratelimit headers, 429 + Retry-After, authenticated+unauthenticated — proven; N× aggregate is #842 policy.
- AC6 metrics+thresholds: threshold block present per replica with explicit pass/fail; gated by 72 passing promotion-gate/boot/gitleaks tests — proven.
- AC7 kill/restart: SIGTERM drain 1.0s, 0 drain 5xx, 0 conn errors, 0 non-terminal runs — proven at harness grade.
- AC8 exact-RC soak >=14400s: **NOT MET, externally blocked** — no RC designation (verified through 23:18:19Z) and a >4h production-Compose run exceeds lane budget/authority. `scripts/soak/run_soak.py` `preflight_artifact_check` is `ok=False` **by design ("deliberately no CLI override")** and `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`; weakening either would falsify the gate, not satisfy it.
- AC9 findings classified external in round handoffs; GitHub filing prohibited in-lane.
- AC10 evidence tied to hashes: `hashes.git_head=c4f45b309`, `git_clean=true`, rendered nginx conf sha256 recomputed in round-30 — proven.

Terminal for lane authority: both remaining failed promotion checks
(`sustain_duration` floor, `exact_rc_artifact`) require a release-owner RC designation and a
>=4h production-Compose soak that no 90-minute lane can execute. No in-lane repair remains.
