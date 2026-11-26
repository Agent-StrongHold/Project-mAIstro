# #2059 repair round 7 — independent validation log (2026-11-25)

Lane CR2059, branch `fix/vulture-single-owner-1357`, head `e23146346d20`
(unchanged this round; no semantic edit). Tree clean, base `bd96877ed8ccd0`
fully contained (`git merge-base HEAD origin/develop` → `bd96877ed8ccd0`;
develop fetched and unchanged at `bd96877ed8ccd0`). This round: re-execute
every RED-listed gate locally with CI-exact arguments, diagnose the one local
failure to root cause, and repair the one in-tree doc over-claim left by the
round-6 verify note. No production code changed.

## Gates executed at `e23146346d` (CI-exact arguments from `quality.yml`)

1. `uv run ruff check .` → **exit 0**; `uv run ruff format --check .` →
   **exit 0**.
2. exact-debt-ledger: `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
   **exit 0**, 1221 reviewed identities → 1221 findings, `unclassified: 0`,
   `never_allowlist: 0`, base `bd96877ed8cc`, candidate `e23146346d20`.
   No unbanked identities; the permitted ledger amendment stays unused.
3. `scripts/check-required-checks.py` → **exit 0**;
   `scripts/check-suite-inventory.py` → **exit 0**;
   `scripts/check-backlog-consistency.py`, `check-contract-markers.py`,
   `check-convergence-matrix.py`, `check-agent-store-writes.py`,
   `check-execution-lifecycles.py` → **all exit 0**;
   `scripts/vendor_bfcl.py --check` (Quality / BFCL provenance) → **exit 0**.
4. Focused suites (ownership, gates-ran, required-checks, merge-group scope,
   grype/docker-CLI/temporalio floors, devskim scope, restore-oracle) →
   **292 passed** (= 232 focused + 60 repair, matching rounds 4–6);
   collect-only on `tests/test_ci_vulture_ownership.py` → **80 (exact)**.
5. Coverage gate, diff half (CI-exact producer replay):
   `coverage run --branch --source=scripts -m pytest tests/ --timeout=30 -q`
   → 6182 passed / 1 failed (see §Local-only artifacts), then
   `coverage xml` + `scripts/check-diff-coverage.py coverage.xml --base
   bd96877ed8ccd0` → **exit 0** ("every measured file this change touches is
   at or above 90% lines / 80% branch arcs"; 2 measured files = the two
   `scripts/` changes, 10 test files exempt by declaration). Publish-set
   aggregate floor: `packages/*/src` diff vs develop is **0 lines**, so the
   floor outcome is inherited from develop (hosted producer legs
   `coverage (no services)`, `coverage (MinIO)`, `coverage (PostgreSQL)` all
   COMPLETED/SUCCESS at this head).
6. Quality / Acceptance state (CI-exact PR invocation)
   `check-ac-state.py --run-tests --ratchet --mandate bd96877ed8ccd0` →
   **exit 0** after provisioning the job's own environment (see §Diagnosis):
   `design coverage: 44.4608% over 166 taken decisions (87 at zero)` —
   byte-identical to the hosted run log, "10 debt counters sit exactly on
   their ceilings and 1 progress counter sits exactly on its floor".

## Diagnosis: local Acceptance-state failure was environment, not the branch

- First local run failed: `design_coverage: 40.2801 falls below the floor of
  44.4608`. Root cause chain, all local:
  1. The job's `services:` uses db `maistro_test` and env
     `MAISTRO_TEST_PG_DSN`/`DATABASE_URL`; locally only db `maistro` was
     provisioned, so service-gated AC-marked tests **skipped** instead of
     passing (core alone: 111 skipped under `-m ac`), dropping criteria off
     the `reachable` rung (40.2801).
  2. After `CREATE DATABASE maistro_test`, `alembic upgrade head`,
     `uv sync --locked --all-extras` (hosted parity), the same CI-exact
     command measures **44.4608 — exactly the base fold** → exit 0.
  - Hosted corroboration: completed pull_request run `45611609025`
    (head `f3fd60990d`, same base fold `bd96877ed8cc`, 52 notes) log reads
    `design coverage: 44.4608% over 166 taken decisions`; hosted
    `Quality / Acceptance state` at this exact head = COMPLETED/SUCCESS
    (both pull_request and push legs). The local-vs-CI slack policy
    difference (`check-ac-state.py` `_canonical_develop_pr_ci`:
    "Local and synthetic callers stay conservative by default") did not
    even come into play once the environment matched.
- A stale **gitignored** `quality/ac-state.json` (`.gitignore:88`, 06:00
  artifact of an earlier round's local run) made
  `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` fail in the root
  suite: `discover_quality_json` rglobs the quality root regardless of
  tracked status. CI checkouts never contain the file. Moved aside →
  **1 passed**; restored afterwards (untracked, `git status` clean).

## Hosted rollup at exact head `e23146346d20` (read-only, 2026-11-25)

`statusCheckRollup` on PR #2059: 130 legs — **122 COMPLETED/SUCCESS,
1 SKIPPED (path-filtered), 0 FAILURE**; still in progress (runtime, not
repair): `integration-scope`, one twin each of `coverage (no services)` /
`coverage (PostgreSQL)`, `test`, `docker-build`, and the two aggregates.
Confirmed SUCCESS at this head: `exact-debt-ledger`, `Quality / Vulture`,
`workflow-lint`, `Quality / Mypy strict`, `Quality / Acceptance state` (×2),
`Quality gate (Pillars 1–4, 7, 8)` (×2), all three coverage producer legs.

## Repair performed this round

- `.cursor/context/2059-verify-230f581988-validation.md` item 8 over-claim
  corrected: the PR body's "This PR does not close #1357, #160 or #1605"
  contains the closer keyword `close #1357` and GitHub ignores negation;
  the prior note's "PR body explicitly does not close" claim was wrong and
  is now marked as corrected. The reword remains a GitHub-side action
  outside lane authority.
- No test files changed → no suite-inventory delta (`inventory-notes/`
  unchanged).

## Residual (lane-prohibited, unchanged)

- PR body stale figures ("1,328 reviewed identities" vs measured 1221;
  "337 focused tests" vs measured 232+60; "Keep draft" vs `isDraft:false`)
  and the negated closer-keyword sentence: GitHub-side body edit required.
- Merge must await the hosted rollup draining (straggler legs + two
  aggregate summaries) on this exact head.
