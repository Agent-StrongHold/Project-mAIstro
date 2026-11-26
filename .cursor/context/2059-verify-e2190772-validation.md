# #2059 independent verification — round 5 (2026-11-25, head e219077258f0)

Lane CR2059 verify, job `2dfd4e6e6b8c4223af4df49ca06aa9ff`. Head
`e219077258f0` (= PR #2059 head as dispatched), tree clean, base
`bd96877ed8ccd0` fully contained (`git merge-base --is-ancestor` true;
merge-base = `bd96877ed8ccd0`). Head is docs-only vs round-4's
`a23fec659dd4` (`git diff --stat` = one new context note, 80+/0-), so all
code below was still re-executed at `e219077258f0`, nothing inherited.

## Executed evidence

1. **Sole semantic workflow change**: `git diff bd96877ed8..HEAD --
   .github/workflows/` = quality.yml only (comments + `if:` on the vulture
   step: push-only, refs != develop/integration/main); vulture-ratchet.yml
   0-line. Parsed-YAML walk (PyYAML, develop vs head) → exactly **1**
   differing path: `jobs.quality-vulture.steps[6].if` ADDED.
2. **No forbidden #1357 hunks**: `git diff bd96877ed8..HEAD -- packages/
   migrations/ quality/vulture-baseline.json` → 0 lines. `quality/` change
   additive-only (new `ac-state-notes/fix-vulture-single-owner-1357.json`,
   17+). Full diff 36 files: tests, scripts (check-gates-ran.py
   refactor+tighten, check-required-checks.py), docs/inventory notes,
   Dockerfile/pyproject merge-queue repairs, CHANGELOG.
3. **CI-exact vulture scan** `uv run python scripts/check-vulture-baseline.py
   packages/*/src --min-confidence 60 --exclude '*/third_party/*'` →
   **exit 0**, 1221 reviewed identities → 1221 findings, vulture 2.16,
   base `bd96877ed8cc`, candidate `e219077258f0`.
4. **Focused tests**: `uv run pytest tests/test_ci_vulture_ownership.py
   tests/test_check_gates_ran.py tests/test_check_required_checks.py
   tests/test_gates_ran_merge_group_scope.py -q` → **232 passed**;
   `--collect-only tests/test_ci_vulture_ownership.py` → **80 tests**
   (the body's "80 new ownership cases" claim is exact). Ownership tests are
   substantive: 25 fail-closed workflow mutations × 2 owners, 4 duplicate-
   fallback conditions rejected, prerequisite-after-scan rejected (both
   provenance and shipped-surface scripts), exact event matrix.
5. **Merge-queue repair tests** (truncated-CI manual inspection):
   `pytest tests/test_cpython_base_grype_floor.py
   tests/test_docker_cli_vendored_advisory_floors.py
   tests/test_temporalio_bridge_zip_floor.py tests/test_devskim_scan_scope.py
   tests/test_restore_oracle_characterization.py
   tests/test_restore_oracle_readiness_gate.py -q` → **60 passed**.
6. **Local gates**: `check-required-checks.py` → exit 0 (79 checks match
   docs/ci/REQUIRED-CHECKS.md); `ruff check .` → exit 0; `ruff format
   --check .` → exit 0 (3659 files); `check-suite-inventory.py` → exit 0
   (21 suites); `check-backlog-consistency.py` → exit 0. Driver check logs
   agree (uv sync resolved, ruff passed, 3659 formatted).
7. **No premature closure**: closure-keyword grep over
   `bd96877ed8..HEAD` subjects+bodies → exit 1 (no matches); PR body
   explicitly states it does not close #1357/#160/#1605.
8. **Live read-only rollup** (`gh pr view 2059 … statusCheckRollup` at
   `e219077258f0`): 26 legs QUEUED, **0 failed**, `isDraft: False`.
   Hosted required-check green on this exact head stays **UNVERIFIED**
   until the queue drains — merge must await the hosted rollup.

## Known GitHub-side staleness (lane-prohibited body edit)

- Body "1,328 reviewed identities = 1,328 findings" vs measured **1221**
  (scan exit 0 at both a23fec659dd4 and e219077258f0).
- Body "337 focused … tests" vs measured **232 + 60 repair**; the "80 new
  ownership cases" figure IS exact.
- Body "Keep draft pending exact-head hosted checks" vs live
  `isDraft: False`.
