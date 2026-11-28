# Issue #860 — bounded repair d44ea482

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting head `524bb34e13a00128c00e9c53efe7b9b1f24184d8`
  (identical to the previous round's end head — nothing arrived to salvage),
  develop base `d592654aca614fb74467487542693c46b3aa30fb`; clean on arrival.
- This round's job directory supplied **no `check-*.log` files** (verified by
  listing: only `dispatch-context.json`, `events.jsonl`, `manifest.json`,
  `prompt.txt`, `state.json`). Prior verification claims were therefore not
  trusted; every load-bearing claim was re-executed locally.
- Candidate edits limited to this report. No test addition (no inventory
  delta — suite inventory still matches), no ledger amendment (exact vulture
  gate produced no unbanked identities), no gate weakening, no remote
  mutations, no destructive git operations.

## Deterministic gates re-executed at this head (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run mypy` (exact 10 CI src dirs per `ci.yml:118–130`) | Success: no issues in 1,027 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; base `e46ad6708fda`, candidate `524bb34e13a0`; 1,326 findings = 1,326 reviewed identities |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_tasks_run_identity.py packages/maistro-server/tests/api/test_tasks_idempotency.py -q` | **21 passed** |
| `uv run pytest tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_rate_limit.py -q` | **34 passed** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-adr-index.py` | OK |
| `uv run python scripts/check-convergence-matrix.py` | OK: 52 subsystems, 1,364 production modules |
| `uv run python scripts/check-merge-markers.py` | ok: no conflict markers |
| `bash scripts/verify-monorepo-layout.sh` | ok |

## Acceptance re-derived from raw evidence at this head

- Live import of `failed_promotion_checks()` from `scripts/soak/run_soak.py`
  against the newest evidence pack
  (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
  `['sustain_duration', 'exact_rc_artifact']`. Records:
  `minimum_seconds=14400, observed_seconds=420.08, ok=false`;
  `topology="host-uvicorn-preflight", ok=false`. The other eight promotion
  gates in the pack pass (`PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` at
  `scripts/soak/run_soak.py:67`; `main()` exits non-zero while either gate
  fails).
- `preflight_artifact_check` (`scripts/soak/run_soak.py:730–741`) deliberately
  has no CLI override (full argparse surface re-read this round: no such
  flag exists). This is anti-fabrication design: an exact-RC runner must
  produce its own observed image/configuration evidence. Running a 4-hour
  host-preflight soak cannot fix this — the artifact gate fails by
  construction, so the run would still exit non-zero.
- **RC designation, fresh sweep of this round's capture**
  (`dispatch-context.json`, 61 API sources captured 2026-10-09T06:16Z): all
  322 comments on #860 are `maistro-progress` bot markers from a single bot
  account (last: `blocked`, 2026-10-09T05:57:51Z, job `a2fea83b`).
  Designation-style regex over all comment bodies → **0 matches**; broader
  RC/release-candidate regex hits are confined to the issue/parent acceptance
  text and prior round reports that themselves state no RC exists. Parent
  #89 ("M3-A7 — Run RC soak and byte-equivalent final promotion") is open —
  RC selection is its release-owner decision and has not been made. PR
  #1672 remains an open **draft** claim-stake.
- **Evidence staleness quantified this round:** the newest pack's recorded
  `git_head` `c4f45b309` (2026-10-06) **is** an ancestor of this head, and
  144 commits / **278 production paths** under `packages/`, `scripts/`,
  `deploy/` have changed since (pinned-develop merge `2b3b73133` plus M1/M9
  work). Per #89's own clause ("any code or runtime-affecting configuration
  change requires a new RC and new applicable soak evidence"), even the
  harness-grade round-30 pack is stale for promotion purposes; only the
  deterministic-gate claims transfer to this head, and those were re-run
  green above.

## Develop-sync assessment (no merge required)

`origin/develop` = `d592654ac` = the assigned base tip (re-fetched this
round). The branch trails by 23 commits / 166 files; `comm` of the two
name-only diffs against merge-base `e46ad6708fda` shows **zero file
overlap** with this branch's 320 changed files, and no soak, promotion-gate,
task-route, or rate-limit file is touched on the develop side. The lane merge
condition ("if it was a develop sync conflict") does not hold; integrating
the 23 non-overlapping research/WIP commits stays a merge-window call, not a
repair this round owes.

## Terminal condition (unchanged, freshly verified)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action:

1. `exact_rc_artifact` requires the exact production Compose image/config of
   a release candidate that no release owner has designated (0 matches in
   this round's fresh capture; parent #89 open).
2. `sustain_duration` requires ≥ 14,400 s on that exact RC artifact; a run
   without (1)'s designation fails it by construction, a bounded attempt
   cannot host a 4-hour soak, and mislabeling host-preflight evidence as a
   promotion soak is forbidden by the harness's own design.

Everything a lane can execute is green at `524bb34e1`. Resolution requires a
release-owner decision: designate the RC artifact/configuration and host the
≥ 4 h production-Compose soak on its exact artifact, or explicitly rule on
the preflight evidence's sufficiency for the M3 promotion decision.

No tree change was made this round other than this report; no test inventory
delta (no tests added or removed); no `quality/*.json` edit (exact vulture
scan is clean); no GitHub mutation, merge, reset, or destructive cleanup.
