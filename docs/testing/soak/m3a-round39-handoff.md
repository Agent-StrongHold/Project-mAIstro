# Issue #860 — round 39 (job 3a66901f) re-validation

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `5c040ecbff7df4297c1705c7f9d321c39d60858b` (identical to the
  previous round's end head — clean on arrival, nothing to salvage),
  develop base `d592654aca614fb74467487542693c46b3aa30fb`.
- This round's job directory supplied **no `check-*.log` files** (verified by
  listing: only `dispatch-context-receipt.json`, `dispatch-context.json`,
  `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`). No prior
  verification claim was trusted; everything below was re-executed locally at
  this head.
- Candidate edits limited to this report. No test added or removed (no
  inventory delta — suite inventory still matches), no `quality/*.json` edit
  (exact vulture gate produced no unbanked identities), no gate weakening, no
  remote mutations, no destructive git operations.

## Deterministic gates re-executed at this head (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run mypy` (exact 10 CI src dirs per `ci.yml:118–130`) | Success: no issues in 1,027 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; base `e46ad6708fda`, candidate `5c040ecbff7d`; 1,326 reviewed identities = 1,326 findings |
| `uv run pytest tests/test_soak_promotion_gates.py -q` | **65 passed** |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_tasks_run_identity.py packages/maistro-server/tests/api/test_tasks_idempotency.py packages/maistro-server/tests/api/test_rate_limit.py tests/test_prod_stack_boot_contract.py -q` | **55 passed** |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-adr-index.py` | OK |
| `uv run python scripts/check-merge-markers.py` | ok: no conflict markers |
| `bash scripts/verify-monorepo-layout.sh` | ok |

## Structural blockers re-verified live at this head

1. **Gate evaluation.** Live import of `failed_promotion_checks()` from
   `scripts/soak/run_soak.py` against the newest evidence pack
   (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
   `['sustain_duration', 'exact_rc_artifact']`:
   `sustain_duration {minimum_seconds: 14400, observed_seconds: 420.08,
   ok: false}`; `exact_rc_artifact {ok: false, topology:
   "host-uvicorn-preflight"}`. `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
   (`scripts/soak/run_soak.py:67`).
2. **No override exists — by tested design.** Full argparse surface re-read
   (`scripts/soak/run_soak.py:1678–1714`): no exact-RC override flag.
   `preflight_artifact_check` (`scripts/soak/run_soak.py:730–741`) returns
   `ok: false` unconditionally for host-process topology. This is pinned by
   `tests/test_soak_promotion_gates.py:102–123`
   (`test_four_hour_preflight_cannot_pass_cli`): even a
   `PROMOTION_MIN_SUSTAIN_SECONDS`-duration preflight run cannot pass the CLI
   while the artifact gate is missing/null/preflight. The blocker is tested
   anti-fabrication behavior, not stale code text.
3. **No RC designation exists — freshest capture.** This round's
   `dispatch-context.json` (captured 2026-10-09T06:41:30Z): all 324 comments
   on #860 are `maistro-progress` bot markers from a single bot account
   (latest: `blocked`, 2026-10-09T06:24:42Z, job `d44ea482`). Designation-style
   regex sweep over all comment bodies → **0 matches**. Parent #89 ("M3-A7 —
   Run RC soak and byte-equivalent final promotion") is **open** — RC
   selection is its release-owner decision and has not been made. PR #1672
   remains an open **draft** claim-stake.
4. **Evidence staleness re-quantified.** The newest pack's recorded
   `git_head` `c4f45b309` is an ancestor of this head;
   `git diff --name-only c4f45b309 HEAD -- packages/ scripts/ deploy/` →
   **278 production paths** changed since. Under #89's own clause ("any code
   or runtime-affecting configuration change requires a new soak"), even the
   harness-grade round-30 pack is stale for promotion; only the
   deterministic-gate claims above transfer to this head, and those were
   re-run green.

## Correction to the previous round's develop-sync record

The d44ea482 report claimed "no soak, promotion-gate, task-route, or
rate-limit file is touched on the develop side." Imprecise: develop commit
`4a86dc0e2` (M8-D5 research series) modifies
`packages/maistro-server/tests/api/test_tasks_idempotency.py` — a flake fix
replacing a racing fixed client deadline with a parked-event gate. The
conclusion is unchanged: re-fetched `origin/develop` = `d592654ac` = base
tip; merge-base `e46ad6708fda`; develop side touches 166 files, branch side
320, **overlap 0** (`comm -12` → empty), so a future merge takes develop's
version of that test cleanly. The branch version passes deterministically
here (included in the 55-test battery above). No merge is owed this round.

## Terminal condition (unchanged)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action:

1. `exact_rc_artifact` requires the exact production Compose
   image/configuration of a release candidate that no release owner has
   designated (0 matches in the freshest capture; parent #89 open).
2. `sustain_duration` requires ≥ 14,400 s on that exact RC artifact; a run
   without (1) fails it by construction (`test_four_hour_preflight_cannot_pass_cli`),
   a bounded attempt cannot host a 4-hour production soak, and mislabeling
   host-preflight evidence as a promotion soak is forbidden by the harness.

Everything a lane can execute is green at `5c040ecbf`. Resolution requires a
release-owner decision: designate the RC artifact/configuration and host the
≥ 4 h production-Compose soak on its exact artifact, or explicitly rule on
the preflight evidence's sufficiency for the M3 promotion decision.
