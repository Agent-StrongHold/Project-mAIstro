# Issue #860 — round 42 (job 3ee6923c) repair: independent re-verification at 34d760dbb

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `34d760dbb5c90f75a263b3692ebe2e2951edcccf` (clean on arrival,
  identical to round 41's end head — nothing to salvage), develop base
  `0d49d4e068de9ecbf0f9510e33781dba8abc87de`, merge-base `e46ad6708fda`.
- This round's job directory supplied **no `check-*.log` files** (listed:
  `dispatch-context-receipt.json`, `dispatch-context.json`, `events.jsonl`,
  `manifest.json`, `prompt.txt`, `state.json`). The lane brief referenced the
  round-40-era failure (`98a11313/check-3.log`, `assert 24 == 21` in
  `test_ensure_schema_fences_ddl_behind_advisory_lock`): already repaired at
  this head — the test's `expected_ddl` now carries all 24 ordered statements
  including the three Gauntlet columns merged from develop — and re-verified
  green below.
- No test added or removed (no inventory delta — `check-suite-inventory.py`
  still reports 17/17), no `quality/*.json` edit, no gate weakening, no
  remote mutations, no destructive git operations.

## This round's work: re-verification from first principles

No earlier verification claim was trusted; every load-bearing number below
was re-derived in this round's session at `34d760dbb`.

### Deterministic gates re-executed (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; base `e46ad6708fda`, candidate `34d760dbb5c9`; 1,326 = 1,326 |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `uv run pytest packages/maistro-core/tests -q` | **14,676 passed, 1,050 skipped, 3 xfailed** (3 min 21 s) — includes the previously-failing `test_pg_learnings.py` (37 passed) and the backlog roundtrip pin (25 passed) |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60` (CI's exact invocation, `ci.yml:645`) | **9,090 passed, 149 skipped** (8 min 51 s) |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-test-duplicates.py` | ok: no byte-identical test files |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves |

### Terminal condition re-derived from raw evidence (unchanged)

- Live import of `failed_promotion_checks()` from `scripts/soak/run_soak.py`
  against the newest evidence pack
  (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
  `['sustain_duration', 'exact_rc_artifact']`. The pack records
  `sustain_duration` = 420.08 s observed vs 14,400 s required
  (`PROMOTION_MIN_SUSTAIN_SECONDS`, `scripts/soak/run_soak.py:67`), and
  `exact_rc_artifact` = `host-uvicorn-preflight`, which
  `preflight_artifact_check()` (`run_soak.py:730`) fails by design with no
  CLI override. Older packs fail strictly more gates (re-run live: the
  round-5 pack fails 7).
- **Staleness re-quantified:** the pack's recorded head `c4f45b309` is now
  148 commits behind this head (round 41 measured 147 at its one-commit-
  earlier head), and **278 production paths** under `packages/`, `scripts/`,
  `deploy/` differ across that range (`git diff --name-only c4f45b309 HEAD
  -- packages/ scripts/ deploy/ | wc -l`). Per the issue's new-soak clause,
  no pack in `docs/testing/soak/evidence/` is promotion-grade for this tree.
- **RC designation, fresh first-hand sweep of this round's capture**
  (job `3ee6923c` `dispatch-context.json`, 61 API sources, captured
  2026-10-09T08:17Z): **828 comment-like bodies scanned** (round 41 scanned
  792) with the designation-style regex → **0 hits**. Parent #89 remains
  open — RC selection is its release-owner decision; linked PRs #1567 and
  #1602 are closed unmerged and #1672 is an open draft, so no merged RC
  artifact exists either.
- **Environment check:** the Docker daemon is unreachable from this lane
  (`DOCKER_HOST=unix:///var/run/docker.sock` → "Cannot connect to the
  Docker daemon"), so not even a shakedown run — let alone the ≥ 4 h
  promotion soak — can be hosted here this round.

## Terminal condition (unchanged)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action:

1. `exact_rc_artifact` requires the exact production Compose
   image/configuration of a release candidate that no release owner has
   designated (0 hits in this round's fresher 828-body sweep; parent #89
   open).
2. `sustain_duration` requires ≥ 14,400 s observed on that exact RC
   artifact; a run without (1) fails it by construction, and the harness's
   own design (pinned by
   `tests/test_soak_promotion_gates.py::test_four_hour_preflight_cannot_pass_cli`)
   forbids mislabeling host-preflight evidence as a promotion soak.

Everything a lane can execute is green at `34d760dbb`. Resolution requires a
release-owner decision: designate the RC artifact/configuration and host the
≥ 4 h production-Compose soak on its exact artifact, or explicitly rule on
the preflight evidence's sufficiency for the M3 promotion decision.

No `quality/*.json` edit (exact vulture scan is clean); no GitHub mutation,
merge, reset, or destructive cleanup.
