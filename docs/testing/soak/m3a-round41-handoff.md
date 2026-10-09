# Issue #860 — round 41 (job 734c96d5) repair: backlog roundtrip pin caught up to engine-116

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `7c6ae6149050070829004bf41342f0e0603ffb85` (clean on arrival,
  identical to the previous round's end head — nothing to salvage), develop
  base `d592654aca614fb74467487542693c46b3aa30fb`, merge-base `e46ad6708fda`.
- This round's job directory supplied **no `check-*.log` files** (listed:
  only `dispatch-context-receipt.json`, `dispatch-context.json`,
  `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`). The prior
  failure the lane referenced (`98a11313/check-3.log`,
  `assert 24 == 21` in
  `test_ensure_schema_fences_ddl_behind_advisory_lock`) was already repaired
  by `cd77bb81c` and re-verified green again this round (see battery).
- No test added or removed (no inventory delta — `check-suite-inventory.py`
  still reports 17/17), no `quality/*.json` edit (exact vulture gate rc=0,
  1,326 = 1,326), no gate weakening, no remote mutations, no destructive git
  operations.

## The repair: stale pinned count in the backlog roundtrip test

Running the **full** `packages/maistro-core/tests` suite (prior rounds ran
only targeted files) exposed one genuine failure at this head:

- `packages/maistro-core/tests/backlog/test_markdown_migration.py::
  test_real_backlog_roundtrips_byte_for_byte` — `assert 168 == 167`.
- Root cause is lane-owned: commit `45a309dd2` ("docs(#860): ... file
  engine-116 cluster-wide rate-limit finding") appended the engine-116 item
  to the canonical `BACKLOG.md` but did not update the test's pinned item
  count. `scripts/check-backlog-consistency.py` accepts the file
  ("OK: 168 backlog items parse, every status, gap marker and citation
  resolves, and every terminal item outside the legacy set carries closure
  evidence"), so the item itself is well-formed; only the drift-catcher pin
  was stale.
- Repair: pin updated 167 → 168 with a comment naming the engine-116
  append, so the next silent item loss still trips the test. The
  byte-for-byte render assertion — the actual losslessness proof — is
  untouched and passes.

## Deterministic gates re-executed at this head (all green after the repair)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; base `e46ad6708fda`, candidate `7c6ae6149050`; 1,326 findings = 1,326 reviewed identities |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/ packages/hive-conductor/backend/tests packages/maistro-design/tests -q --timeout=60` (CI's exact invocation, `ci.yml:650`) | **9,090 passed, 149 skipped** (8 min 44 s) |
| `uv run pytest packages/maistro-core/tests -q` | **14,676 passed, 1,050 skipped, 3 xfailed** (was 1 failed before the repair) |
| `uv run pytest packages/maistro-core/tests/backlog/ -q` | **96 passed, 20 skipped** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-test-duplicates.py` | ok: no byte-identical test files |
| `uv run python scripts/check-doc-links.py` | Every relative markdown link resolves |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |

## Acceptance re-derived from raw evidence at this head

- Live import of `failed_promotion_checks()` from `scripts/soak/run_soak.py`
  against the newest evidence pack
  (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
  `['sustain_duration', 'exact_rc_artifact']` — unchanged.
- **Staleness re-quantified:** the pack's recorded `git_head` `c4f45b309`
  is 147 commits behind this head, and **278 production paths** under
  `packages/`, `scripts/`, `deploy/` differ across that range. Per #89's own
  new-soak clause, no pack in `docs/testing/soak/evidence/` is promotion-grade
  for this tree.
- **RC designation, fresh first-hand sweep of this round's capture**
  (`dispatch-context.json`, 61 API sources, captured 2026-10-09T07:35Z):
  792 comment-like records scanned; designation-style regex
  (`(release candidate|RC)\s*(designation|designated|selected|is)\b|designat`)
  → **0 hits**. Parent #89 remains open — RC selection is its release-owner
  decision. PR #1672 remains an open draft.

## Terminal condition (unchanged)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action:

1. `exact_rc_artifact` requires the exact production Compose
   image/configuration of a release candidate that no release owner has
   designated (0 hits in this round's fresh capture; parent #89 open).
2. `sustain_duration` requires ≥ 14,400 s (`scripts/soak/run_soak.py:67`,
   `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`) observed on that exact RC
   artifact; a run without (1) fails it by construction, and the harness's
   own design (pinned by
   `tests/test_soak_promotion_gates.py::test_four_hour_preflight_cannot_pass_cli`)
   forbids mislabeling host-preflight evidence as a promotion soak.

Everything a lane can execute is green at `7c6ae6149` (plus the backlog-pin
repair commit of this round). Resolution requires a release-owner decision:
designate the RC artifact/configuration and host the ≥ 4 h production-Compose
soak on its exact artifact, or explicitly rule on the preflight evidence's
sufficiency for the M3 promotion decision.

No `quality/*.json` edit (exact vulture scan is clean); no GitHub mutation,
merge, reset, or destructive cleanup.
