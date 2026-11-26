# #2059 repair round 8 — independent validation log (2026-11-25)

Lane CR2059, branch `fix/vulture-single-owner-1357`, head `9bfc7428ce8e`
(unchanged this round; no semantic edit). Tree clean before and after the
battery; base `c9636e99f1d7` fully contained
(`git merge-base --is-ancestor` → true; `git fetch origin develop` →
origin/develop still exactly `c9636e99f1d7`, so the develop-sync block from
the previous round stays resolved by merge commit `9bfc7428ce8e`). This
round re-executed every acceptance gate locally at the post-merge head and
refreshed the hosted rollup. No production code changed; the driver's
`check-*.log` files referenced by the brief were absent from the job
directory, so all deterministic checks were re-run directly.

## Local gates at `9bfc7428ce8e`

1. `uv sync --locked --extra dev` → exit 0; `uv run ruff check .` → exit 0
   ("All checks passed!"); `uv run ruff format --check .` → exit 0 (3664
   files already formatted).
2. exact-debt-ledger (CI-exact): `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
   **exit 0**, 1220 reviewed identities → 1220 findings, `unclassified: 0`,
   `never_allowlist: 0`, base `c9636e99f1d7`, candidate `9bfc7428ce8e`.
   No unbanked identities → the round's permitted
   `quality/vulture-baseline.json` amendment stays **unused** (nothing to
   fix or re-bank; the count moved 1221→1220 via the develop merge, not via
   debt edits).
3. Focused suites: `pytest tests/test_ci_vulture_ownership.py
   tests/test_check_required_checks.py tests/test_check_gates_ran.py
   tests/test_gates_ran_merge_group_scope.py tests/test_devskim_scan_scope.py
   tests/test_restore_oracle_characterization.py
   tests/test_restore_oracle_readiness_gate.py -q` → **265 passed**;
   collect-only on `tests/test_ci_vulture_ownership.py` → **80 (exact)**.
4. Script gates, CI-exact invocations from `quality.yml`/`ci.yml` — all
   exit 0: `check-required-checks.py` (79 PR checks),
   `check-uv-setup.py` (74 steps), `check-workflow-write-safety.py`
   (33 workflows), `check-branch-protection.py` (21 develop / 35 main),
   `check-test-duplicates.py`, `check-compliance.py`,
   `check-suite-inventory.py` (21 suites — no delta to declare: no test
   files changed), `vendor_bfcl.py --check` (13 artifacts + shim),
   `check-agent-store-writes.py`, `check-contract-markers.py`,
   `check-convergence-matrix.py` (1504 production modules, 52 subsystems),
   `check-workflow-inventory.py`, `check-backlog-consistency.py`
   (167 items), `check-execution-lifecycles.py` (19 vocabularies).

## Sole semantic change re-proven at `9bfc7428ce8e`

- `git diff --stat c9636e99f1d7...HEAD -- .github/workflows/` →
  `quality.yml | 11 ++++++++++-` only (+9/−2);
  `vulture-ratchet.yml` diff = **0 lines** (byte-identical).
- Parsed-YAML recursive walk of `quality.yml` base vs head →
  **exactly 1 delta**: `jobs.quality-vulture.steps[6].if` added
  (push-only, refs ≠ develop/integration/main; source lines 1601–1605).
- Trigger pairing: ratchet owns unfiltered `pull_request`, `merge_group`,
  `push[develop, integration, main]`; Quality's copy survives only on
  topic pushes (`feat/*`, `bug/*`, `fix/*`, `idea/*`, `doc/*`, `docs/*`,
  `chore/*`). Union covers every event; intersection is empty → one scan
  owner per event, encoded by the 80 ownership tests incl. negative
  controls.

## Hosted rollup at exact head `9bfc7428ce8e` (read-only gh, this round)

PR #2059 `headRefOid` = `9bfc7428ce8e…`, state OPEN, not draft.
`statusCheckRollup`: 119 **SUCCESS** / 1 SKIPPED (path-filtered) /
**0 FAILED**; 8 legs still IN_PROGRESS (runtime, not repair):
`integration-scope`, `coverage (no services)` ×2, `coverage (PostgreSQL)`,
`test`, `Container scan + SBOM + cosign`, `hive-conductor-e2e`,
`docker-build`; plus the `gates-ran` queue-leg placeholder (null status).
Confirmed **SUCCESS at this exact head**: `exact-debt-ledger`,
`workflow-lint`, `Quality / Vulture` (both legs), `Quality / Acceptance
state` (both legs), `Quality gate (Pillars 1–4, 7, 8)` (both legs).
Progress since prior round: 115→119 SUCCESS, 13→8 IN_PROGRESS, failures 0.

## Residual (lane-prohibited, unchanged)

- PR body still carries stale figures ("1,328 reviewed identities" vs
  measured 1220; "337 focused tests" vs measured 265) and the negated
  closer-keyword sentence ("does not close … #160 … #1605" — GitHub
  ignores negation). GitHub-side body edit required before merge.
- Merge must await the hosted rollup draining the 8 runtime legs on this
  exact head.
