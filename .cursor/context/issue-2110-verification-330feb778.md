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

## Repair-round re-validation at 08841cd3b (job a7a1b97e15374d18811b72231476ed32)

Prior round aborted on a driver provider timeout after green ruff checks; the tree was found
clean at the expected head 08841cd3b264 (330feb778 + this record's docs commit). All evidence
above was re-executed at this head by the repair lane:

1. gitleaks 8.30.1 (CI-pinned version, present locally): CI-exact PR/merge_group form
   `gitleaks git --redact --log-opts=10f872fa7be..08841cd3b26 .` -> 27 commits, "no leaks
   found", exit 0. `--all` sweep: 40 findings on 14 unique commits, **zero** on any commit of
   this PR (fb322ab fingerprints hold); residuals are pre-existing refs outside the PR range
   (the PR gate is the range scan).
2. `uv run pytest tests/test_get_ps1_wsl_detection.py -v` -> 28 passed (harness executed under
   pwsh 7.4.6, PASSED not SKIPPED).
3. `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1 -PowerShell pwsh` ->
   "all 23 cases passed" + "RESULT relaunch-policy ok", exit 0.
4. Regression bite re-proven at this head: base get.ps1 in /tmp with this PR's tests beside it
   -> all 3 new tests FAIL with the right reasons (missing approved-policy help text;
   `-executionpolicy` present in old relaunch bodies; harness throws 'Unexpected elevation
   arguments').
5. `uv run ruff check .` / `uv run ruff format --check .` exit 0; driver check logs agree.
6. CI-exact gates: `uv run python scripts/check-suite-inventory.py` exit 0 (21 suites match);
   `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
   --exclude '*/third_party/*'` exit 0 (1248 reviewed identities = 1248 findings, base
   10f872fa7be3 -> candidate 08841cd3b264; ledger untouched).
7. Read-only `gh pr view 2110` at GitHub head 330feb778: 119 SUCCESS / 0 FAILED / 7 SKIPPED
   (service-gated) / 1 PENDING (gates-ran aggregator). Every gate RED in the earlier attempt
   history (Compliance registry, Container scan + SBOM + cosign, Coverage gate, Gate C,
   Quality / Acceptance state, Quality / Agent store writes, Quality / Architecture fitness,
   Quality / BFCL provenance, SAST / Gitleaks) has a SUCCESS run at that head.

Declared limits unchanged: real Windows PowerShell 5.1/7 runtime policy enforcement, UAC and
reboot resume remain unverified (no Windows host; release-installer workflow is tag/manual
dispatch). No source, ledger, gate, or baseline file was modified by this round either.

## Deep-review round 2 re-validation at 34b24e8ca (job 08b4dddf2aa749b59583a3c18262b36b)

Prior round (NEEDS-DEEP-REVIEW verdict, job dc7fa9fa) findings adversarially re-examined at the
assigned head 34b24e8ca3d7c3b530d329313a40bf30f1a6a516 (= 08841cd3b branch line + develop merge
f8a2df966a1d). Worktree found clean at the assigned head. All prior local evidence re-executed
and holds; one NEW CI failure discovered at this head.

Re-executed and confirmed (all locally, read-only except this record):

1. gitleaks 8.30.1 (same version+sha256 pin as .github/workflows/security.yml:117-118), CI-exact
   PR form `gitleaks git --redact --log-opts=f8a2df966a1d..34b24e8ca3d .` -> 28 commits scanned,
   "no leaks found", exit 0. Also confirmed with `gitleaks detect --log-opts=...` (exit 0).
   Live GitHub statusCheckRollup at this head: SAST / Gitleaks SUCCESS (both runs). The prior
   SAST RED is repaired; .gitleaksignore fingerprints (de8266eff + 3x fb322ab rows) are
   load-bearing as documented.
2. `uv run pytest tests/test_get_ps1_wsl_detection.py -v` -> 28 passed, 0 skipped (pwsh present;
   test_relaunch_argument_construction executed the harness for real, "RESULT relaunch-policy ok").
3. `pwsh -NoProfile -NonInteractive -File tests/installer/run-wsl-detection-e2e.ps1 -PowerShell pwsh`
   -> "all 23 cases passed" + "RESULT relaunch-policy ok", exit 0.
4. Regression bite re-proven at THIS head: `git show f8a2df966a1d:get.ps1` (old relaunch bodies
   carry `-ExecutionPolicy Bypass` at base lines 377 and 390) -> this PR's harness exits 1 with
   `throw 'Unexpected elevation arguments'` (relaunch_policy_harness.ps1:42). The tests bite;
   they are not pinned to pass vacuously. Harness verifies it extracts exactly one production
   FunctionDefinitionAst per name, so the mocked run exercises real function bodies.
5. `uv run ruff check .` / `uv run ruff format --check .` exit 0 (3561 files formatted); driver
   check-0/1/2.log agree (uv sync, ruff check, ruff format all green).
6. `uv run python scripts/check-suite-inventory.py` exit 0 (21 suites match recorded inventory);
   inventory note docs/testing/inventory-notes/security-windows-policy-prerequisite.md (+3)
   remains consistent — no update needed this round.
7. get.ps1 at head: zero `-ExecutionPolicy`/`Bypass` tokens in code; only read-only
   `Get-ExecutionPolicy -List` documentation references (get.ps1:71, get.ps1:82). Invoke-Elevated
   (get.ps1:391-398) and Register-Resume (get.ps1:403-412) keep RunAs, quoting, passthrough and
   the HKCU RunOnce / MaistroInstallResume destination unchanged — matches the PR claims.
8. Closure keywords: strict grep over PR body + all commit messages in
   f8a2df966a1d..34b24e8ca3d -> no matches (exit 1). No premature issue closure.
9. Range contains NO dependency files: `git diff --stat f8a2df966..34b24e8ca -- uv.lock
   '**/pyproject.toml' '**/requirements*.txt'` is empty; full changed set is get.ps1,
   tests/test_get_ps1_wsl_detection.py, tests/installer/relaunch_policy_harness.ps1,
   tests/installer/run-wsl-detection-e2e.ps1, .gitleaksignore, the inventory note, this record.

NEW finding at this head (live read-only `gh pr view 2110 --json statusCheckRollup`):

- **Supply chain (pip-audit) FAILURE** twice (security workflow runs 43783735839 / 43783733310,
  jobs 133026598831 / 133026591322). Gate log: "Found 6 known vulnerabilities in 5 packages";
  4 advisories outside the triaged allowlist (scripts/pip_audit_gate.py): dnspython==2.9.0
  CVE-2026-128089 -> 2.9.2; graphql-core==3.3.0 CVE-2026-119286 -> 3.3.1; joserfc==1.7.5
  CVE-2026-119284 -> 1.7.6; opentelemetry-api==1.45.1 CVE-2026-126360 -> 1.45.2. Because the
  range changes no dependency files (item 9), this failure is inherited from the develop base
  lockfile + advisory DB, not introduced by this PR — but CI is therefore demonstrably NOT green
  at the assigned head, which the prior rounds' "0 FAILED" snapshots predate (the merge of
  f8a2df966 triggered fresh runs). Repair (dependency bumps or gate-allowlist triage) belongs to
  the PR owner; a verify lane must not rewrite PR content.
- Everything else at this head is SUCCESS or still QUEUED/IN_PROGRESS (Gate C, coverage x4,
  the quality gate family, CI test/postgres/docker-build, Container scan + SBOM + cosign,
  formal-conformance, integration-scope, CodeQL python). Pending checks remain UNVERIFIED;
  never inferred green.
- Prior previously-RED gates with SUCCESS runs at this head: Compliance registry, Quality /
  Agent store writes, Quality / Reachability dispositions, exact-debt-ledger (Vulture Ratchet),
  DevSkim, SAST / Bandit, Quality / Radon, Quality / Frontend typed client, Quality /
  Credential authority, Quality / Workflow inventory, Quality / Backlog consistency,
  Quality / Documentation links, workflow-lint, pr-base, block (Cage Guard).

Stale claim drift (non-blocking, unchanged): PR body says "remains draft with automerge
disabled" but live isDraft=false at this head.

Verdict for this round: NEEDS-REPAIR — the six issue criteria are locally proven, but "CI green
at this exact head" fails on the base-inherited pip-audit advisories and dozens of checks are
still pending. Declared limits unchanged: real Windows PowerShell 5.1/7 policy enforcement, UAC
elevation and reboot RunOnce resume remain unverified (no Windows host; release-installer
workflow runs on tags/manual dispatch, not PRs).

## Deep-review round 3 re-validation at f906f8519 (job be02a9fb2ba4)

Head delta vs round-2's 34b24e8ca is docs-only (this file, +71 lines); worktree clean at the
assigned head f906f8519327eb9157fed8a8c567b4091baae14f; base f8a2df966a1d unchanged. All round-2
evidence re-executed independently at this head and holds:

1. `uv sync --locked --extra dev` ok; `uv run pytest tests/test_get_ps1_wsl_detection.py -v`
   -> 28 passed, 0 skipped (pwsh 7.4.6 present; test_relaunch_argument_construction really ran
   the harness, stdout ends "RESULT relaunch-policy ok").
2. `pwsh -NoProfile -NonInteractive -File tests/installer/run-wsl-detection-e2e.ps1 -PowerShell pwsh`
   -> "all 23 cases passed" + "RESULT relaunch-policy ok", exit 0.
3. Regression bite re-proven at this head: harness vs `git show f8a2df966a1d:get.ps1`
   (Bypass at base lines 377/390) exits 1 "Unexpected elevation arguments"
   (relaunch_policy_harness.ps1:42); the two static regressions
   (test_relaunch_functions_do_not_override_execution_policy,
   test_relaunch_argument_construction) also FAIL against that base file, then the tree was
   restored (git status clean). Tests bite, not pinned vacuous.
4. `uv run ruff check .` / `uv run ruff format --check .` exit 0 (3561 files);
   `uv run python scripts/check-suite-inventory.py` exit 0 — 21 suites match; inventory note
   (+3) still consistent, no update needed.
5. gitleaks 8.30.1 (pin verified security.yml:117-118), CI-exact PR form
   `gitleaks git --redact --log-opts=f8a2df966a1d..f906f8519 .` -> 29 commits, "no leaks
   found", exit 0. .gitleaksignore #2110 rows (fb322ab x3, de8266eff) are scoped to
   introducing commit:path:rule:line.
6. Closure keywords: strict grep over all commit messages in
   f8a2df966a1d..f906f8519 -> no matches. Range changes no dependency files
   (`git diff --stat f8a2df966a1d..f906f8519 -- uv.lock '**/pyproject.toml'
   '**/requirements*.txt'` empty); full changed set is get.ps1, three test files,
   .gitleaksignore, inventory note, this record.
7. get.ps1 at head: only the two `-ExecutionPolicy Bypass` tokens removed (elevation +
   RunOnce); RunAs verb, quoting, passthrough, HKCU RunOnce/MaistroInstallResume destination
   all asserted unchanged by the harness; .NOTES/.EXAMPLE add fail-closed guidance incl.
   Get-ExecutionPolicy -List, "session-only ... not sufficient", "do not weaken the policy".

NEW local reproduction of the round-2 live CI failure, CI-exact (security.yml:160-190):
`uv pip freeze --exclude-editable` -> 223 rows; `uv run pip-audit --strict --format=json`
attempt 1 produced a usable report (audit exit 1);
`uv run python scripts/pip_audit_gate.py pip-audit.json` -> exit 1 with 4 advisories outside
the allowlist: dnspython==2.9.0 CVE-2026-128089 -> 2.9.2; graphql-core==3.3.0 CVE-2026-119286
-> 3.3.1; joserfc==1.7.5 CVE-2026-119284 -> 1.7.6; opentelemetry-api==1.45.1 CVE-2026-126360
-> 1.45.2. Because the range changes no dependency files, this is inherited from the develop
base lockfile, not introduced by this PR. Repair (bump the four deps or justified triage in
scripts/pip_audit_gate.py) belongs to the PR owner; a verify lane must not rewrite
dependencies or weaken gates. The historical merge-queue RED list (Compliance registry,
Container scan, Coverage, Gate C, Quality x4) had SUCCESS runs at 34b24e8ca and those jobs'
inputs are byte-identical at f906f8519 (docs-only delta).

Live read-only `gh pr view 2110 --json statusCheckRollup` at f906f8519: headRefOid matches the
assigned head; 18 checks, 0 success / 0 failure / 18 QUEUED (incl. Supply chain, Compliance
registry, Gate C, Coverage family, Quality family, CI test). Everything queued remains
UNVERIFIED; never inferred green. isDraft=false — the PR body's "remains draft" line is stale
claim drift, non-blocking.

Verdict for this round: NEEDS-REPAIR — all issue acceptance criteria are locally proven at the
assigned head, but the CI-exact Supply chain (pip-audit) gate demonstrably fails on
base-inherited advisories and the full rollup is queued. Declared limits unchanged: real
Windows PowerShell 5.1/7 enforcement, UAC elevation, reboot RunOnce resume unverified (no
Windows host).

## Round 4 (job f03149df55984a05a169b2da0346ed61) — manual CI-gate inspection at eeffb0b92

"CI response truncated; manual inspection required" resolved by running every named gate
locally, CI-exact, at head eeffb0b92d0d8357fa8f4728c5b070af9357c8ce (worktree clean; delta vs
f906f8519 is this record only):

1. Lane tests: `uv run pytest tests/test_get_ps1_wsl_detection.py -v` -> 28 passed, 0 skipped
   (pwsh present; harness really ran). `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1
   -PowerShell pwsh` -> 23/23 cases + "RESULT relaunch-policy ok", exit 0.
2. Regression bite re-proven for the RIGHT reason: base get.ps1 (git show
   f8a2df966a1d:get.ps1) + this PR's tests + tests/installer/ copied to /tmp/bite-repo ->
   all 3 new tests fail; harness fails with 'Unexpected elevation arguments'
   (relaunch_policy_harness.ps1:42) because base Invoke-Elevated carries -ExecutionPolicy Bypass.
3. ruff check . / ruff format --check . -> exit 0 (driver check-1/check-2 logs agree);
   scripts/check-suite-inventory.py -> exit 0, 21 suites, 35317 ids; PR inventory note (+3)
   consistent -> no inventory-note update needed this round.
4. Named gates from the historical merge-queue RED list, run locally CI-exact
   (RATCHET_BASE_REV=origin/develop = f8a2df966a1d, exactly CI's PR form):
   - Compliance registry: `uv run --with 'PyYAML>=6,<7' python scripts/check-compliance.py`
     -> "compliance registry and COMPLIANCE.md are valid", exit 0.
   - Quality / Agent store writes: scripts/check-agent-store-writes.py -> exit 0.
   - Quality / BFCL provenance: scripts/vendor_bfcl.py --check -> exit 0 (13 artifacts + shim).
   - Quality / Architecture fitness: PYTHONPATH=packages/maistro-core/src pytest
     packages/maistro-core/tests/fitness -q --timeout=30 -> 39 passed, exit 0.
   - Quality / Acceptance state: disposable pgvector/pgvector:pg18 container
     (cr2110-ac-pg18, port 15439, removed afterwards; no other lane's container touched),
     alembic upgrade head (065->068), then scripts/check-ac-state.py --run-tests --ratchet
     --mandate f8a2df966a1d -> acceptance mandate 0/0, chain mandate 0/0, "OK: every
     criterion this change declares is proven", exit 0.
5. Supply chain (pip-audit) — REQUIRED per .github/branch-protection.json — re-reproduced
   CI-exact at this head: uv sync --locked --all-extras; uv pip freeze --exclude-editable
   (234 rows); pip-audit --strict attempt 1 report complete (audit exit 1);
   scripts/pip_audit_gate.py -> exit 1: dnspython 2.9.0 CVE-2026-128089, graphql-core 3.3.0
   CVE-2026-119286, joserfc 1.7.5 CVE-2026-119284, opentelemetry-api 1.45.1 CVE-2026-126360,
   fixed versions exist (2.9.2/3.3.1/1.7.6/1.5.2-class bumps named by the gate).
   `git diff f8a2df966..HEAD -- uv.lock pyproject.toml requirements*.txt` is empty ->
   base-inherited; the repair (bump the four deps) belongs to the PR owner.
6. SAST / Gitleaks: gitleaks 8.30.1 CI-exact PR form
   `--log-opts=f8a2df966a1d..eeffb0b92` -> 30 commits, "no leaks found", exit 0.
7. Closure keywords: strict grep over `git log --format='%s %b' f8a2df966..HEAD` -> none
   (grep exit 1). Supplied PR body likewise carries no closure keyword.
8. Live `gh pr view 2110` at this head: state OPEN, isDraft=false (body's "remains draft"
   remains stale drift, non-blocking), statusCheckRollup 22 QUEUED + 1 SKIPPED (Container
   scan + SBOM + cosign, service-gated). Everything queued stays UNVERIFIED — never inferred
   green.

Round-4 verdict: NEEDS-REPAIR (unchanged driver: all issue acceptance criteria locally
proven; the required Supply chain gate demonstrably fails base-inherited, and the hosted
rollup at this exact head is fully queued). Declared limits unchanged: real PowerShell 5.1/7
enforcement, UAC elevation, reboot RunOnce resume remain unverified (no Windows host).

## Round 5 (job e2d1b7e99f7c45f1b044f4bf1c35a491) — repair round: the two reproducible gate
## failures fixed and validated locally

Round-4's NEEDS-REPAIR named exactly one reproducible failure (Supply chain pip-audit, 4
base-inherited advisories) plus the historical Container-scan RED. The prior attempt left the
repair uncommitted (uv.lock had been regenerated by an older uv, downgrade to lock revision
3); this round preserved it (backup: job dir incoming-2110-salvage.patch), validated it, and
landed it as commit a7ba1f453 "repair(#2110): clear Supply chain (pip-audit) + Container scan
findings". Files: pyproject.toml (constraint floors in the established triage-comment shape),
uv.lock (dnspython 2.9.2, graphql-core 3.3.2, joserfc 1.8.0, opentelemetry-api/sdk 1.45.2),
Dockerfile + Dockerfile.research (patch golang.org/x/net v0.62.0 + go-jose v4.1.6 on the
pinned docker/cli v29.9.1 in the shared dockerclibuild stage, then re-vendor).

Executed evidence at a7ba1f453 (all local, CI-exact where the gate names exact tools):

1. Supply chain (pip-audit), security.yml:160-190 exact: uv sync --locked --all-extras;
   uv pip freeze --exclude-editable (234 rows; the four vulnerable pins gone); pip-audit
   --strict report parses (exit 1 with findings, as the workflow expects); only remaining
   finding is pre-triaged ecdsa==0.19.1-class PYSEC-2026-1325 (no fix version); scripts/
   pip_audit_gate.py -> **exit 0** ("pip-audit OK (1 known, all triaged in ALLOWED)").
2. Container scan repair, artifact-level with CI's trivy v0.73.0:
   - Bite: built dockerclibuild from HEAD's (unpatched) Dockerfile; `trivy image --scanners
     vuln --severity HIGH,CRITICAL --ignore-unfixed` reports CVE-2026-78661 (golang.org/x/net
     v0.60.0, fix 0.62.0) and CVE-2026-116587 (go-jose v4.1.5, fix 4.1.6), both HIGH, on the
     `out/docker` target — the exact findings the gate fails on; neither is triaged in
     .trivyignore.yaml (it carries only CVE-2026-77214 + 2x CVE-2026-111497).
   - Fix: same build + same trivy invocation on the patched Dockerfile: `go version -m`
     shows x/net v0.62.0 + go-jose v4.1.6, binary still Docker version v29.9.1 dfc520d;
     trivy analyzes 12 language targets incl. `out/docker` and reports **0 HIGH/CRITICAL**.
     (First trivy attempt via `trivy fs <binary>` returned Results:null — vacuous; redone as
     trivy image so the gobinary target is genuinely analyzed.)
   - Residual: the full 4-image gate (SBOM, cosign, grype) needs hosted buildx/GHA cache;
     the image-level scan remains a hosted-only confirmation.
3. No collateral breakage at a7ba1f453: ruff check . + ruff format --check . exit 0;
   tests/test_get_ps1_wsl_detection.py 28 passed (pwsh, harness ran);
   run-wsl-detection-e2e.ps1 23/23 + "RESULT relaunch-policy ok" exit 0;
   scripts/check-suite-inventory.py exit 0 (21 suites match; no test files changed so the
   (+3) note stays consistent); gitleaks 8.30.1 CI-exact range f8a2df966a1d..a7ba1f453 ->
   no leaks exit 0; scripts/check-compliance.py exit 0; check-vulture-baseline.py with CI's
   exact args exit 0 (1238 = 1238, ledger untouched); check-agent-store-writes exit 0;
   vendor_bfcl.py --check exit 0; PYTHONPATH=packages/maistro-core/src pytest
   packages/maistro-core/tests/fitness -q --timeout=30 -> 39 passed under the bumped deps.
4. uv.lock revision 3 concern resolved against CI's pinned toolchain: setup-uv pins uv
   0.12.5 exactly; `uvx --from uv==0.12.5 uv lock --check` -> exit 0 and `uvx --from
   uv==0.12.5 uv sync --locked --extra dev --dry-run` -> exit 0 (local uv 0.12.20 agrees).
   `uv lock` treats the lock as up-to-date and does not rewrite it.
5. Closure keywords: none in the repair commit message; no issue-closure action taken.

Verdict for this round: the two locally-reproducible gate failures are fixed with local
CI-exact proof; issue criteria remain proven (re-executed lane tests at this head); hosted
rollup still UNVERIFIED (queued), Windows-runtime limits unchanged. No inventory-note update
needed (no test count changed).

## Round 6 — repair at 7de64446c2a4 (hive-conductor-e2e-ui + Container scan residuals)

Driver checks (job a9b58ba36b214f40be55c081470cd442): uv sync --locked --extra dev,
ruff check ., ruff format --check . — all exit 0 at the exact starting head.

1. Actual CI evidence fetched (read-only) for the three red checks at 7de64446c
   (run 43806818617, jobs 133099383970 + 133099866372 + 133099386119):
   - Container scan + SBOM + cosign: the failing step was trivy-action_3 =
     `maistro-engine-research:pr-2110` (HIGH/CRITICAL, exit-code 1, ignore-unfixed,
     trivyignores .trivyignore.yaml). Findings: oauthlib 4.0.0 CVE-2026-49272
     (fix 4.0.1), pyasn1 0.6.4 CVE-2026-119194/195/196/197 (fix 0.6.5),
     pypdf 6.21.2 CVE-2026-119203/204/205/206/207/208/209 (fix 6.21.3/6.21.4),
     soupsieve 3.0.3 CVE-2026-126190 (fix 4.0.0). The hive + engine scans in the
     same job PASSED; the rsi-runner scan never ran (job died first).
     The npm-audit lines in the truncated board log were build noise, not the failure.
   - hive-conductor-e2e-ui: 240 passed / 1 failed / 1 flaky / 4 did-not-run
     (serial suite). Failed (both attempts): rsi-polling-resilience.spec.ts:591
     "a success resets the cadence to base and the failure ladder to fresh",
     gapFresh 3760 vs >= 6800 — 3750 + 10ms = the BASE cadence measured as the
     "fresh ladder" gap, twice. The flaky: :459 cap gap 45015 > 45010 (passed retry).
     These specs are develop-inherited (PR #2110 touches no frontend/e2e file);
     develop's own ci.yml run at f8a2df966 passed e2e-ui on 2026-11-08, and
     develop's security workflow has been red since 2026-11-13 (engine image
     x/net finding — which a7ba1f453 already fixed for this branch).
   - integration-scope: meta-gate, failed only because hive-conductor-e2e-ui did.
2. Container scan fix (pyproject.toml + uv.lock): four constraint-dependencies
   floors in the established triage-comment shape (oauthlib>=4.0.1, pyasn1>=0.6.5,
   pypdf>=6.21.4, soupsieve>=4.0.0) — all four roll up through the research
   image's locked export only (google-auth-oauthlib→requests-oauthlib,
   google-auth→pyasn1-modules, browser-use→pypdf/markdownify→beautifulsoup4→
   soupsieve; browser-use = core's `[browser]` extra). `uv lock` re-resolved
   exactly those four (oauthlib 4.0.1, pyasn1 0.6.5, pypdf 7.1.0, soupsieve
   4.1.1 — browser-use 0.5.9 declares pypdf unbounded, 7.1.0 is in-range);
   `uvx --from uv==0.12.5 uv lock --check` exit 0 (CI's pinned toolchain).
   Local CI-exact proof: docker build -f Dockerfile.research ->
   image carries oauthlib 4.0.1 / pyasn1 0.6.5 / pypdf 7.1.0 / soupsieve 4.1.1;
   trivy v0.73.0 (CI's version) `image --severity HIGH,CRITICAL --ignore-unfixed
   --ignorefile .trivyignore.yaml --scanners vuln,secret` -> **0 vulnerabilities**.
   Dockerfile.rsi-runner installs via `uv sync --locked` on the same pyproject +
   uv.lock, so the fix flows there too; hive/engine scans passed in CI on the
   pre-fix tree already.
   Supply chain (pip-audit) stays green: uv sync --locked --all-extras (219 rows,
   none of the four packages are in that env), pip-audit --strict parses,
   scripts/pip_audit_gate.py exit 0 (only the pre-triaged ecdsa PYSEC-2026-1325).
3. e2e-ui fix (packages/hive-conductor/tests/e2e/rsi-polling-resilience.spec.ts,
   test-only; the page's loop code is correct and untouched):
   - :591 — the fixed `counts >= 4` milestone assumed exactly one manual refresh
     request; a click Playwright re-verifies after the cleared banner shifts
     layout can dispatch the refresh handler twice, and the extra manual refresh
     then got indexed as a loop poll, so the base cadence (3.75s) was measured
     as the "fresh ladder" gap (= the observed 3760, both attempts). Replaced
     with banner-synced indexing: the banner's reappearance after setModes
     ("abort") marks the first post-refresh outage poll in every dispatch
     ordering (loop-poll, late duplicate refresh that succeeds, or one that
     aborts — all three orderings produce the same asserted gaps).
   - :459 — the observation loop advanced the fake clock +5ms per expect.poll
     interval while the fetch's real-time finally raced those nudges: each
     nudge landing before the rearm shifted the next deadline +5ms, so a slow
     CI round-trip accumulated unbounded quanta into a gap (45015 = 3 nudges).
     Replaced with one overshooting chunk per step (runFor(delay+5), timer due
     strictly inside the chunk) and observation that never advances the clock,
     making the rearm anchor deterministic and load-independent; the residual
     +0..+15ms is Playwright's 5ms fire quantization, plus a rare exactly-1000ms
     headless-Chromium timer-fire clamp seen once in a local soak. Bounds now
     allow a stated 1100ms envelope (documented in-spec) — adjacent ladder rungs
     are 7.5-15s apart, so discrimination is unchanged, and the 5-minute
     burn-down (<=8 polls at the cap) still pins the cadence.
   - Local proof (isolated compose project cr2110-ui, CI=1 budget, retries on):
     rsi spec 6/6 clean iterations after the final bounds; full compose suite
     `up --build --abort-on-container-exit --exit-code-from e2e-tests` ->
     exit 0 with 245 passed / 1 flaky (dag-builder-unmount-cleanup, unrelated
     environmental class, passed its retry) — the same command ci.yml runs.
     A pre-fix local soak reproduced the CI signatures exactly (45015 > 45010;
     gapFresh 3760-class indexing), so the repairs address the observed
     failures, not a guess.
4. Gates re-run green at this tree: ruff check . / format --check . exit 0;
   check-vulture-baseline.py with CI's exact args (1238 = 1238, untouched);
   check-suite-inventory.py exit 0 (21 suites match — playwright specs are not
   pytest-inventoried and no test count changed, so the (+3) note stays
   consistent); tests/test_get_ps1_wsl_detection.py 28 passed.
5. Residuals: hosted rollup (SBOM/cosign/grype legs, hosted e2e-ui run) remains
   UNVERIFIED until CI runs on the new head; the research image's pypdf 7.1.0
   jump is metadata-valid (browser-use declares pypdf unbounded) but real
   browser-tool behavior on pypdf 7 stays a hosted e2e concern (the image's
   builder smoke passes: import maistro_server.main + browser-use/playwright
   versions). No closure keywords; no issue-closure action.

## Round 6 (2026-11-16, repair at 884daa62a + pin/lock repair commit): the last red gate

Head d3c793ae074e's only failing required check was `Container scan + SBOM +
cosign` (run 43845270217, job 133223751128). Fetched the job log (read-only
API): steps 1–14 all success; **step 15 `Trivy scan maistro-rsi-runner
(HIGH/CRITICAL only)` failed** — not the npm-audit noise the truncated
prior-findings excerpt suggested — on
`workspace/.venv/lib/python3.12/site-packages/temporalio/bridge/Cargo.lock
(cargo)`: crate `zip` 8.6.0, CVE-2026-115905 CRITICAL (fixed 9.0.5) +
CVE-2026-115907/115908/115909 HIGH (fixed 9.0.0). temporalio is a root
dependency (#2143) imported nowhere in-repo; the rsi-runner image is the only
sync selection that installs it (matches #2251's per-image export greps).

Evidence, all local, CI-exact forms (this worktree):

1. Wheel inspection (PyPI, hash-pinned downloads unpacked): temporalio
   1.34.0's vendored `temporalio/bridge/Cargo.lock` pins zip **8.6.0**
   (reproduces the CI finding exactly); 1.35.0 pins 9.1.2, 1.36.1 pins 9.5.1.
2. Lock repair (bounded): `uv lock --upgrade-package temporalio==1.36.1` —
   four rows move (temporalio 1.34.0→1.36.1, nexus-rpc 1.4.0→1.5.0 per
   temporalio's == pin, playwright 1.64.0→1.65.2, patchright 1.64.1→1.64.4);
   temporalio/nexus-rpc/playwright/patchright rows are **byte-identical** to
   CI-proven PR #2251 head 6e11a8b50 (conflict-free convergence). OSV: no
   advisories for temporalio 1.36.1, nexus-rpc 1.5.0, playwright 1.65.2,
   patchright 1.64.4 (pip-audit surface unchanged-clean).
3. Grype projection proven locally before CI would have hit it: grype v0.116.0
   (CI version) on the post-temporalio-fix rsi-runner rebuild exits 2 on
   CPython-binary CVE-2026-115557 (CRITICAL, fixed 3.12.16; docker run on the
   pinned base a0f57064 = 3.12.15) — the same class #2251 closed by moving the
   python bases. Also grype-only: playwright/patchright bundle Node 24.21.0
   (CVE-2026-106069/105483) in the research image; docker/cli v29.9.1 vendors
   klauspost/compress v1.20.1 (GO-2026-6865) that only the grype DB carries.
4. Repairs (mirroring #2251's CI-proven green run 43849992035 today,
   2026-11-16T10:33→10:53): python bases → `python:3.13.18-slim-bookworm@a5a7017e`
   and `python:3.12-slim@5e2bdb1b` (docker run verifies 3.13.18 / 3.12.16) in
   Dockerfile, Dockerfile.research, Dockerfile.rsi-runner,
   packages/hive-conductor/Dockerfile (+ its identity assert (3,13,16)→(3,13,18)),
   packages/hive-conductor/tests/Dockerfile, deploy/sbx/template/Dockerfile.tests,
   scripts/smoke-engine-canvas.sh; docker/cli stage v29.9.1+two-patches →
   #2251's v29.9.3 (5457199) + single x/net@v0.62.0 upgrade (v29.9.3 vendors
   go-jose v4.1.7 and klauspost/compress v1.20.2, vendor.sum verified upstream);
   `constraint-dependencies` floors playwright>=1.65.2 / patchright>=1.64.4
   (in-image: drivers bundle Node v26.13.1 / v24.22.1); both
   quality/image-pins.json entries re-recorded with #2251's exact text;
   CHANGELOG Unreleased Security entries added (container round + the PR's own
   execution-policy change, previously missing).
5. Gate-level proof — all four images rebuilt locally and scanned with the
   workflow's exact arguments (`trivy image --severity HIGH,CRITICAL
   --exit-code 1 --ignore-unfixed --ignorefile .trivyignore.yaml`, trivy
   v0.73.0/DB 2026-11-16; `grype --fail-on high --only-fixed`, grype
   v0.116.0/DB same day as CI's green run):
   hive-conductor trivy 0 grype 0; maistro-engine trivy 0 grype 0
   (docker --version in-image = v29.9.3 build 5457199);
   maistro-engine-research trivy 0 grype 0 (playwright 1.65.2, patchright
   1.64.4 in-image; temporalio absent as expected);
   maistro-rsi-runner trivy 0 grype 0 (temporalio 1.36.1 + nexus-rpc 1.5.0
   in-image; vendored zip 9.5.1). Engine grype was exit 2 (GO-2026-6865)
   before the v29.9.3 switch — the negative control for the docker/cli change;
   rsi-runner grype was exit 2 (CVE-2026-115557) before the base bump — the
   negative control for the pins.
6. Gates re-run green at this tree: uv lock --check; uv sync --locked --extra
   dev; ruff check . / format --check .; check-image-pins.py (9 pins / 10
   Dockerfiles registered); check-release-consistency.py;
   check-suite-inventory.py (21 suites, unchanged counts — no test files
   touched); check-vulture-baseline.py CI-exact (1238 = 1238);
   pytest tests/test_pinned_digest_references.py tests/test_check_image_pins.py
   tests/test_image_lock_contract.py tests/test_get_ps1_wsl_detection.py —
   104 passed (the issue's 28 Windows-policy tests among them, harness
   included; no drift in get.ps1/tests since the 330feb778 verification).
7. Residuals: the hosted containers run on the new head is UNVERIFIED until
   CI executes (this round proves the same scanner versions on the same DB
   day pass on locally rebuilt images; hosted gha-cache/apt-state variance
   remains hosted). #2059/#2251 carry overlapping floors with different
   pyproject floor styles (mine: constraint floors only; theirs: manifest
   floors) — whichever merges last owns the final wording; lock rows are
   identical so no lock conflict is possible. No closure keywords; no
   issue-closure action.

## Round 6 (verifier, head e422c25f7c53, 2026-11-16)

1. Named-gate CI at this head (read-only rollup + logs): Compliance registry,
   Gate C — canonical clean install, Quality / Acceptance state (review-time),
   Quality / Agent store writes, Quality / Architecture fitness, Quality / BFCL
   provenance = SUCCESS. Container scan + SBOM + cosign = FAILURE at
   "Verify live Python packages and Conductor identity contract".
2. Root cause of that FAILURE (reproduced locally before CI confirmed it):
   the repair rounds bumped the hive-conductor base to
   python:3.13.18-slim-bookworm@a5a7017e and updated the in-image assert
   (packages/hive-conductor/Dockerfile:172 runs `(3, 13, 18)` at build time),
   but the two security.yml docker-run smoke asserts stayed at `(3, 13, 16)`.
   `docker run` on the pinned digest prints Python 3.13.18, so
   `assert sys.version_info[:3] == (3, 13, 16)` deterministically fails —
   CI run 43868252055 failed at exactly that step. Repair: both asserts moved
   to `(3, 13, 18)`, matching image-pins.json and the Dockerfile's own build
   assert. This is an assert/tree re-alignment, not a gate change.
3. Quality / Acceptance state in merge-queue mode (the mode that went RED at
   d3c793ae0): reproduced locally with GITHUB_EVENT_NAME=merge_group +
   GITHUB_EVENT_PATH payload — FAIL "unbanked improvement — design_coverage:
   44.4608, floor still says 39.641". Review-time (pull_request) mode passes
   without a bank ("no bank is required", CI log 133302259572), but the merge
   queue enforces banking. Repair: banked via the gate's own command
   (check-ac-state.py --run-tests --ratchet --bank) →
   quality/ac-state-notes/fix-windows-bootstrap-prerequisite.json
   (design_coverage floor raised 39.641 → 44.4608, stricter). Re-ran the
   CI-exact command under merge_group simulation: exit 0, actual-base guard
   OK. Post-bank, review-time mode still exit 0.
4. Issue-scoped re-verification at this tree: pytest
   tests/test_get_ps1_wsl_detection.py = 28 passed with pwsh installed — the
   mocked relaunch_policy_harness.ps1 EXECUTED (not skipped): real
   Invoke-Elevated/Register-Resume bodies produce exactly
   `-NoProfile -File "<path>" ...` with no -ExecutionPolicy, RunAs verb kept,
   RunOnce destination/entry contract kept. The static regression was proven
   to FAIL against the base f8a2df966 get.ps1 (both function bodies carry
   -executionpolicy/bypass). Suite inventory gate green (21 suites).
5. Local named-gate re-runs with CI's exact arguments: check-compliance.py OK;
   vendor_bfcl.py --check OK (13 artifacts); check-agent-store-writes.py OK;
   pytest packages/maistro-core/tests/fitness = 39 passed (one transient
   fixture error on first run, clean on re-run, matching CI SUCCESS);
   check-image-pins.py OK; git diff --check clean.
6. Coverage gate: diff-coverage scope is packages/*/src +
   hive-conductor/backend; the branch's only changed .py is a test file, so
   the diff half is trivially satisfied and the publish-set floor rides the
   unchanged source tree; hosted producers were still IN_PROGRESS at
   review time — formal conclusion belongs to CI.
7. Residuals: the repaired security.yml and the bank note are committed
   locally; CI must re-run on the new head for Container scan + SBOM +
   cosign to be formally green (hosted builds/cache variance UNVERIFIED
   until then). No closure keywords; no issue-closure action.
