# Issue #860 — round 40 (job ef8e76dc) repair: `.gitleaksignore` merge-overlap dedup

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`,
  starting head `ec5cbb471172abb065e99da4eaf4099858ecbb9f` (clean on arrival,
  identical to the previous round's end head — nothing to salvage), develop
  base `d592654aca614fb74467487542693c46b3aa30fb`, merge-base `e46ad6708fda`.
- This round's job directory supplied **no `check-*.log` files** (listed:
  only `dispatch-context-receipt.json`, `dispatch-context.json`,
  `events.jsonl`, `manifest.json`, `prompt.txt`, `state.json`). The prior
  failure referenced by the lane (`98a11313/check-3.log`,
  `assert 24 == 21` in `test_ensure_schema_fences_ddl_behind_advisory_lock`)
  was already repaired by `cd77bb81c` — re-run here and green (37 passed,
  6 skipped). The immediately previous run (`a631e6453`) died on a provider
  timeout, not a validation failure.
- The one candidate edit is the `.gitleaksignore` dedup below. No test added
  or removed (no inventory delta — `check-suite-inventory.py` still reports
  17/17), no `quality/*.json` edit (exact vulture gate produced no unbanked
  identities), no gate weakening, no remote mutations, no destructive git
  operations.

## The repair: duplicate fingerprints after the develop merge

`tests/test_gitleaksignore_contract.py::test_fingerprints_are_unique` failed
at this head: `.gitleaksignore` carried
`77c17b9b8…:packages/maistro-evolve/tests/test_attribution.py:generic-api-key:{462,476}`
twice. Provenance: the branch re-keyed these entries in `31c82fe84`
("re-keyed after line drift" block); develop-side `d30f6c4ae` (#1624) later
added the identical pair as a "Historical M4-A8 merge commit (#1750)" block;
merge `6a9a2d4b8` kept both copies because the hunks did not textually
overlap. Duplicates add no suppression coverage — which is exactly what the
contract test enforces.

Repair: drop the redundant pair, keep the single keyed copy, and replace the
duplicate block's fingerprints with a comment recording why (pointing at the
re-keyed block and the enforcing test), so the documentation trail survives.

Evidence the repair is behavior-neutral (A/B, gitleaks 8.30.1 — CI's pinned
version):

- Range arm, CI-shaped: `gitleaks git --redact
  --log-opts="d592654a…HEAD"` → `no leaks found`, rc=0, **before and after**.
- `--all` arm: exit=1 with 10 findings **before and after**; the suppression
  sets are byte-identical (`newly exposed: []`, `newly suppressed: []`).
  All 10 findings trace to `refs/remotes/origin/gh-readonly-queue/*` merge
  refs that exist only in this local clone (commits absent from HEAD, base
  and `origin/develop`), so they cannot appear in a CI checkout's `--all`
  run; the arm itself only executes on pushes to `main`/`integration`/
  `develop` (`security.yml:96–115`). Pre-existing local artifact, not a
  regression of this branch.

## Deterministic gates re-executed at this head (all green)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,195 files already formatted |
| `uv run pytest` targeted battery (gitleaksignore contract, soak promotion gates, `test_pg_learnings.py`, tasks concurrency/run-identity/idempotency/rate-limit, prod-stack boot contract) | **165 passed, 6 skipped** |
| `uv run mypy` (exact 10 CI src dirs, `ci.yml:118–130`) | Success: no issues in 1,027 source files |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0; base `e46ad6708fda`, candidate `ec5cbb471172`; 1,326 reviewed identities = 1,326 findings |
| `uv run python scripts/check-suite-inventory.py` | ok: 17 suite(s) match the recorded inventory |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `uv run python scripts/check-adr-index.py` / `check-merge-markers.py` / `verify-monorepo-layout.sh` | ok / ok / ok |

## Structural blockers re-verified live at this head (unchanged)

1. **Gate evaluation.** Live import of `failed_promotion_checks()` from
   `scripts/soak/run_soak.py` against the newest evidence pack
   (`docs/testing/soak/evidence/m3a-round30-shakedown.json`) →
   `['sustain_duration', 'exact_rc_artifact']`:
   `sustain_duration` minimum 14,400 s (`run_soak.py:67`) vs observed
   420.08 s; `preflight_artifact_check()` (`run_soak.py:730`) returns
   `ok: false`, topology `host-uvicorn-preflight`. The no-override,
   no-preflight-pass behavior is pinned by
   `tests/test_soak_promotion_gates.py:103`
   (`test_four_hour_preflight_cannot_pass_cli`, part of the 65 green).
2. **No RC designation exists — freshest capture.** This round's
   `dispatch-context.json` (61 sources; 717 issue-860 comment records):
   designation-style regex sweep → exactly 1 match, which **is the issue
   body itself** (posted by the issue author 2026-08-31). No release-owner
   designation comment exists. Parent #89 remains open; PR #1672 remains an
   open draft.
3. **Evidence staleness re-quantified.** The newest pack's recorded
   `git_head` `c4f45b309` is an ancestor of this head;
   `git diff --name-only c4f45b309 HEAD -- packages/ scripts/ deploy/` →
   **278 production paths**. Under #89's own clause ("any code/runtime-config
   change requires a new soak"), even the harness-grade round-30 pack is
   stale for promotion.

## Terminal condition (unchanged)

The two remaining failed promotion gates cannot be satisfied by any in-lane
bounded action: `exact_rc_artifact` needs a release-owner-designated RC
Compose artifact (none exists in the freshest capture), and `sustain_duration`
needs ≥ 14,400 s on that exact artifact — a combination the tested harness
refuses to fake. Everything a lane can execute is green at `ec5cbb471`.
Resolution requires a release-owner decision: designate the RC
artifact/configuration and host the ≥ 4 h production-Compose soak on it, or
explicitly rule on the preflight evidence's sufficiency for the M3 promotion
decision.
