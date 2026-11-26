# Repair round — #2110 CI gate repair at 4b6c793653 (job 9bc4939350e847ec9190e387ae90a174)

Lane CR2110 · branch `fix/windows-bootstrap-prerequisite` · starting head
`4b6c793653cc99373137a2108f5411a960bfd657` (= PR head d4b7d7b856 + driver
NOTICE-tweak commit) · develop base `221dc3d517e7580dc80859259cfdf15a2fd3ec9e`.

## Why this round was needed

Prior attempts died on provider 404 / timeout after green driver pre-checks
(`uv sync`, `ruff check`, `ruff format` — all exit 0 in
`/home/dev/maistro/jobs/9bc4939350e847ec9190e387ae90a174/check-{0,1,2}.log`),
so no repair landed. The dispatch's check-run capture at PR head d4b7d7b856
(131 runs) shows exactly two failing gates: `lint-and-type-check` and `test`
(run 45573851502, jobs 139066801725 / 139066801588); `Coverage gate` was still
in_progress at capture. No log content was available, so both jobs were
reproduced locally step by step.

## Root cause (reproduced locally, not assumed)

Both red gates share one root cause: the two #313 temporary exemptions in
`quality/public-routes.json` (`/v1/auth/register`, `/v1/setup/`) expired
2026-11-24; CI ran 2026-11-25.

- `uv run python scripts/check-public-routes.py` (ci.yml:291, the
  "Every unauthenticated path is declared and justified" step): exit 1 with the
  gate's own expiry message for both paths. This step is in **both** failing
  jobs (ci.yml runs it inside lint-and-type-check's step list and it is also
  reached via the tests/ tree self-checks in the test job).
- `uv run pytest tests/test_check_public_routes.py` (test-job step `pytest
  tests/`): 2 failed — `TestTheRepositorysOwnRegistry::test_it_agrees_with_the_middleware`,
  `::test_main_passes_and_says_how_many` — against the live registry.
- Byte-identity: develop tip 221dc3d517 ships the same expired file, so the
  failure is base-inherited, exactly as recorded in the d4b7d7b856 commit
  message ("re-justification authored by lane #2372 at 71db1c9109, not yet on
  origin/develop").

## Fix applied

`quality/public-routes.json`: both exemptions re-justified per the gate's own
instruction ("close it (#313) or re-justify it with a new date and a reason
that survives review a second time"): `expires` 2026-11-24 -> 2027-02-22
(exactly 90 days) and reasons recording the second review (#313 still open, no
invite-gating replacement shipped, throttling since #366 unchanged, closes when
#313 lands or on the new date). The resulting file is **byte-identical** to the
reviewed lane-#2372 repair: `git diff 71db1c9109 -- quality/public-routes.json`
is empty. Route identities unchanged (12 -> 12, ratchet reports base-authorized
against base 221dc3d517e7 — no authorization-file edit needed, none made).
No vulture-ledger rows were touched (CI-repair exception not exercised: the
vulture gate passes unchanged, see below).

## Executed evidence at 4b6c793653 + this fix

1. `scripts/check-public-routes.py` -> exit 0, "all 12 unauthenticated path(s)
   are declared and base-authorized".
2. `uv run pytest tests/test_check_public_routes.py` -> 24 passed, 0 failed.
3. CI-exact vulture ledger: `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` -> exit 0,
   1221 reviewed identities = 1221 findings, base 221dc3d517e7.
4. `uv run ruff check .` / `uv run ruff format --check .` -> green.
5. `python scripts/check-suite-inventory.py` -> 21 suites match; `python
   scripts/check-test-duplicates.py` -> ok.
6. lint-and-type-check steps: `bash scripts/verify-monorepo-layout.sh` ok;
   `python scripts/check-merge-markers.py` ok; `uv run mypy` over the 10 CI
   trees -> "Success: no issues found in 1131 source files"; the three steps
   after the public-routes step (`check-closure-targets.py` — skip without PR
   body, `check-shell-execution.py` ok, `check-build-context.py` ok).
7. Test-job step `uv sync --locked --extra dev --extra bootstrap` ok, then
   `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest tests/
   --ignore=tests/tools/registry` (the exact failing step, env-matched):
   run 1 — 2 failed (the two public-routes self-checks above, i.e. the CI
   failures) + 1 Docker-probe flake; run 2 after the fix — **5968 passed /
   140 skipped / 1 failed**, the sole failure being
   `tests/test_prod_postgres_probe_live.py::test_first_boot_ready_only_after_init_completed`.
8. Probe-flake triage (run-2 sole failure): the file is byte-identical to
   develop (`git diff 221dc3d517 -- tests/test_prod_postgres_probe_live.py`
   empty); a different test of the same file failed in run 1 and passed in run
   2 and standalone (dedicated run of
   `test_wrong_credentials_fail_closed_with_diagnostics` -> passed; full file
   -> 3 passed in 61s; the run-2 flakes -> passed standalone in 13.88s). The
   tests assert transient Docker health-log states inside 15s windows and boot
   real pg17 containers — per-run variance under suite load, not branch
   content (the PR touches no Python runtime code).
9. `npm audit --json` (canvas frontend) -> 0 advisories; `python scripts/npm_audit_gate.py /tmp/npm-audit.json` -> exit 0 ("npm audit OK").
10. gen:api drift step: `dump-hive-openapi.py` (250 paths) + `npm run gen:api`
    + `git diff --exit-code -- packages/hive-conductor/frontend/src/api/types.gen.ts`
    -> no drift.
11. PR's own Windows acceptance at this head: `uv run pytest
    tests/test_get_ps1_wsl_detection.py -v` -> 28 passed (incl.
    test_relaunch_argument_construction executing the real harness); `pwsh
    -NoProfile -NonInteractive -File tests/installer/run-wsl-detection-e2e.ps1
    -PowerShell pwsh` -> "all 23 cases passed" + "RESULT relaunch-policy ok",
    exit 0. Regression bite re-proven: harness against `git show
    221dc3d517:get.ps1` throws 'Unexpected elevation arguments'
    (relaunch_policy_harness.ps1:42).
12. CI-pinned gitleaks 8.30.1, CI-exact range
    `gitleaks git --redact --log-opts=221dc3d517e7..4b6c793653 .` -> 26
    commits, "no leaks found", exit 0.
13. Local-debris handling: untracked, git-ignored `quality/ac-state.json`
    (generated by scripts/check-ac-state.py on every local run; absent from
    HEAD and develop) made
    `tests/test_branch_independence_repository.py::test_every_quality_json_state_surface_is_classified_once`
    fail locally. Moved (not deleted) to `/tmp/ac-state.json.salvage-*`;
    the test passes after the move. CI checkouts never contain the file.

## Still UNVERIFIED (declared limits, unchanged)

- Real Windows PowerShell 5.1/7 execution, actual execution-policy enforcement,
  UAC prompt, reboot RunOnce resume — no Windows host; the release-installer
  workflow runs on tags/manual dispatch only.
- Live CI completion at the new head — this round commits the fix; fresh CI
  runs must be observed, never inferred.
- The one-process coupling step (`pytest tests/ packages/hive-conductor/
  backend/tests packages/maistro-design/tests -q --timeout=60`) was not
  re-run in full this round; the d4b7d7b856 round recorded it CI-exact at
  11254 passed / 222 skipped with only the now-fixed public-routes failures,
  and this round re-ran its `tests/` portion end to end twice (item 7).

No test files, ledgers, or baselines were modified by this round; the only
tree change is the `quality/public-routes.json` re-justification plus this
record. No inventory delta (test count unchanged: +0).
