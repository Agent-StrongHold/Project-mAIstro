# REPAIR-NOTES — #330 CI-repair round (branch `auto-330`, base of round `9f73003f8384`)

Job `e618d845ba454e4e9b7842e197132004`, 2026-10-24. Scope: the eight red CI
checks at head `9f73003f83848f5a10c69dcc4835150430bacdbf`. Every red was
reproduced, root-caused from the actual CI logs (fetched read-only), and either
fixed in-tree or attributed with evidence.

## Root causes and fixes

| CI red | Root cause (from log) | Fix |
|---|---|---|
| `test` (3 failed of 5823) | `TestToolingReachesTheTopRung` pinned `@tool/mutation_ratchet` as its dead stand-in, but #330's workflow restoration made that script genuinely reachable (nightly invokes it by path; `check_mutation_baseline.py` imports it), so the committed ledger un-banks it. `check-reachability.py` itself passed — only the test's hardcoded stand-in was stale. | Stand-in repointed to `@tool/mutation_filter_annotations` (still statically invisible), docstring records the service history. `tests/test_check_ac_state.py`. |
| `test` + `workflow-lint` + `Coverage gate` | `check-branch-protection.py`: the new check name `Mutation gate (changed critical lines)` was neither required nor advisory; the generated `BRANCH-PROTECTION.md` tables no longer matched. Develop passes the same gate; this is branch-caused. | Advisory entry with the paths-scope rationale in `.github/branch-protection.json` (a `paths`-filtered check can never be required — it would hang on `Expected`), then `--update-doc` regenerated the one added table row. |
| `workflow-lint` (actionlint) | SC2034: unused `tests` variable in `mutation.yml`'s per-source diff loop. | Field read into `_tests` with the column-folding rationale commented. |
| `Supply chain (pip-audit)` + `security` | fastmcp 4.0.11 (GHSA-7xgj-8392-5q4r, GHSA-vqqp-x5qm-5qp4 → fix 4.1.2) and setuptools 84.0.0 (GHSA-xmj3-9gf7-h52w → fix 84.1.0). Gate's own instruction: upgrade. | `uv lock --upgrade-package fastmcp --upgrade-package setuptools` → fastmcp 4.1.3, setuptools 84.2.1 (pyproject constraints `>=3.2.0,<5` unchanged). Local pip-audit run: only the triaged ecdsa advisory remains; gate exit 0. |
| `Container scan + SBOM + cosign` | Trivy HIGH on pypdf 6.21.1 (CVE-2026-115572/115580/115585, fixed 6.21.2) in the maistro-engine-research image; images install via `uv export --locked`. | `uv lock --upgrade-package pypdf` → 6.21.2. |
| `integration-scope` | Downstream: `docker-build` `needs: workflow-lint`; workflow-lint red ⇒ docker-build skipped ⇒ aggregator failed on `docker-build ... concluded skipped`. No independent defect. | Resolved by the workflow-lint fix. Classifier verified: this diff's scope is `docker_build=true` only, required set `["docker-build"]`. |
| `gates-ran` | Aggregate over the red checks above. | Downstream. |
| `Coverage gate` (combine step) | The step re-runs the root suite as the `scripts` producer: the same 3 test failures aborted it; and the diff-coverage leg scored the new gate scripts below 90%/80% (mutation_pr_gate 64%, mutation_select_tests 79.1%, mutation_critical 87.8%, mutation_packet 75%, check_mutation_baseline 66.7%). | 31 tests added across the five mutation suites covering the untested halves (baseline-run aborts, CLI plumbing, refusal paths, SKIPPED-row exclusion, no-upload mode, continuation contract) — see `docs/testing/inventory-notes/330-ci-repair-diff-coverage-and-contract.md`. |

## Local proof (CI's exact commands where defined)

- Root producer: `uv run coverage run --branch --source=scripts -m pytest tests/
  tests/test_model_check_consumer_claim.py
  packages/maistro-core/tests/extensions/test_lifecycle_proof.py --timeout=30 -q`
  → **5854 passed, 140 skipped** (was 3 failed).
- Diff coverage: `check-diff-coverage.py coverage.xml --base 4de7e906…` →
  **ok: every measured file at or above 90% lines / 80% branch arcs**.
- `check-branch-protection.py` → OK (19/32); `check-required-checks.py` → 76 match;
  actionlint 1.7.7 + shellcheck over all workflows → clean.
- pip-audit (strict, JSON) + `pip_audit_gate.py` → OK (1 known, triaged).
- `check-suite-inventory.py` → all suites ok (`tests/: 5972`).
- Vulture with CI's exact args (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`) → 1302 = 1302, exit 0; **no ledger amendment needed**.
- `packages/maistro-server/tests` → 644 passed on the upgraded fastmcp 4.1.3.
- ruff check / format: clean. Workflow-inventory, branch-independence,
  reachability, dispositions, compliance, mutation-critical validate: green.

## Not touched

- `quality/vulture-baseline.json` (no new debt; gate green without amendment).
- No gate weakened; branch-protection disposition is an honest advisory entry,
  the same decision the contract forces for `pr-base`/`DevSkim`.
- Downstream greening of `integration-scope`/`gates-ran` on the queue is
  inferred from the wiring (`needs: workflow-lint`), not locally provable.
