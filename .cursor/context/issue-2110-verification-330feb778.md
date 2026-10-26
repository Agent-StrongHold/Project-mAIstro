# Issue #2110 independent verification record (verify lane)

Frozen scope: PR #2110 only; worktree /home/dev/Git/wt/cr-2110, branch
fix/windows-bootstrap-prerequisite. Head verified 330feb778475b108a403ed20a2163a9e53cd7c0f
(working tree clean at start); supplied develop base 10f872fa7be3ef5aa62c3a896ddc2b1a1027bd2c,
which is also `git merge-base` of the two. Job directory
/home/dev/maistro/jobs/3769c129b3d84a4ea8ca10c69ff57b9c; prior failed provider run
/home/dev/maistro/jobs/b51ea45438f24c1795cca89c1d4d1271 (sync/ruff green, agent died before review).
This record does not close the issue and is not merge or integration approval.

## Why a repair round was needed (prior evidence, re-derived)

Prior verify rounds recorded: CI-exact gitleaks at c3ac5c5ba range
292ff7a008dbc..c3ac5c5ba014 exited 1 with three generic-api-key findings on
fb322ab221607c0ea6fb0be541f4087c9f1839e8 (packages/maistro-evolve/tests/test_attribution.py
lines 462/476; tests/migrations/test_task_admission_generation_upgrade.py line 46), contradicting
the PR body's "SAST/Gitleaks clears". The repair commit 65d7e78c6 added three
.gitleaksignore fingerprints scoped to commit fb322ab (path+rule+line), documented as the
third re-landing of two already-fingerprinted fixture shapes.

## Executed evidence at 330feb778 (all run locally by this lane)

1. gitleaks 8.30.1 (same version as .github/workflows/security.yml pins, sha256-verified there)
   - PR/merge_group exact form `gitleaks git --redact --log-opts=10f872fa7be..330feb7784 .`:
     26 commits scanned, "no leaks found", exit 0.
   - push fallback `330feb7784^..330feb7784`: no leaks, exit 0.
   - protected-branch form `--log-opts=--all`: fb322ab findings absent (0 mentions); 40 residual
     findings come from unrelated local refs not reachable from develop and are outside this PR.
2. `uv run pytest tests/test_get_ps1_wsl_detection.py -v`: 28 passed, 0 skipped. Unlike the
   implementer's host, pwsh exists here, so test_relaunch_argument_construction really executed
   tests/installer/relaunch_policy_harness.ps1 against real get.ps1 ("RESULT relaunch-policy ok").
3. `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1 -PowerShell pwsh`: all 23
   detection cases passed and the wired-in relaunch harness ran ("RESULT relaunch-policy ok"), exit 0.
4. Regression bite proven against the OLD code: base get.ps1 extracted via
   `git show 10f872fa7be:get.ps1` into /tmp/oldrepo with this PR's tests copied beside it;
   all three new tests FAIL there (harness throws 'Unexpected elevation arguments' because the
   old Invoke-Elevated carries `-ExecutionPolicy Bypass`; both static tests fail their
   forbidden-token assertions). The tests are not pinned to pass vacuously.
5. `uv run ruff check .` exit 0 ("All checks passed!"); `uv run ruff format --check .` exit 0
   (3557 files already formatted). Also green in driver check-1.log / check-2.log.
6. `uv run python scripts/check-suite-inventory.py` (CI ci.yml exact args): exit 0, 21 suites
   match, 35152 collected node IDs, 0 duplicate evidence, 0 byte-identical test files. The PR's
   delta note docs/testing/inventory-notes/security-windows-policy-prerequisite.md (tests/: +3)
   is consistent with the passing sum.
7. Read-only `gh pr view 2110 --json statusCheckRollup` at this exact head: 109 SUCCESS,
   0 FAILED, 8 in progress/queued (test, docker-build, coverage (no services) x2, coverage
   (PostgreSQL) older run, integration-scope, Container scan + SBOM + cosign, Quality gate),
   7 SKIPPED service-gated, gates-ran PENDING. Every gate RED in the prior attempt history
   (Compliance registry, Container scan + SBOM + cosign, Coverage, Gate C, Quality/Acceptance
   state, Quality/Agent store writes, Quality/Architecture fitness, Quality/BFCL provenance,
   SAST/Gitleaks) now has a SUCCESS run at this head except the still-running instances listed
   above, which remain UNVERIFIED, not green.
8. Closure-keyword review: PR body and all commit messages in 10f872fa7be..330feb7784 contain
   no fixes/closes/resolves + #N constructions (grep exit 1 on the strict pattern).

## Acceptance mapping

| Criterion | Evidence |
| --- | --- |
| Remove process-policy overrides from elevation + RunOnce commands; keep RunAs/quoting/passthrough/registry destination | get.ps1 diff vs base: only the two `-ExecutionPolicy Bypass` tokens removed; harness asserts FilePath powershell.exe, Verb RunAs, RunOnce HKCU path, MaistroInstallResume, String type, exact arg strings |
| Document administrator-approved prerequisites, read-only inspection, fail-closed guidance | get.ps1 .NOTES/.EXAMPLE block; enforced by test_download_example_requires_approved_execution_policy (passes at head, fails on old file) |
| Post-logon resume needs post-logon-effective policy; session-only insufficient | .NOTES text asserted verbatim in the same test |
| Help-text + real-function static regressions + mocked PowerShell harness wired into Windows detection runner | two pytest static tests + relaunch_policy_harness.ps1; run-wsl-detection-e2e.ps1:55-59 invokes it under the requested interpreter; executed under pwsh in item 3 |
| New static regression fails against old relaunch functions | item 4 (3 failed against base get.ps1) |
| SAST/Gitleaks clears | item 1 local CI-exact exit 0 + GitHub SAST/Gitleaks SUCCESS at head |
| Suite inventory delta | item 6 |

## Explicitly UNVERIFIED (declared limits, unchanged from the PR body)

- Real Windows PowerShell 5.1 / PowerShell 7 execution, actual execution-policy enforcement,
  UAC prompt, reboot resume: no Windows host in this environment; release-installer workflow
  runs on tags/manual dispatch, not PRs. Still requires Windows-host validation.
- Live CI completion at this head: runs in progress at snapshot time; pending is UNVERIFIED,
  never inferred green. Container scan + SBOM + cosign instance for this head had no conclusion
  yet at capture.
- `--all` residual findings on unrelated refs (item 1): pre-existing, out of PR scope, not
  re-triaged here.

No source, ledger, gate, or baseline file was modified by this round; the only write is this
record. Worktree otherwise untouched at the assigned head.
