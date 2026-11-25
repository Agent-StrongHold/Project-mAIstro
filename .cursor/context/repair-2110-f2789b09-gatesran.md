# Issue #2110 repair round — manual CI inspection at f2789b09 (gates-ran adjudication)

Frozen scope: PR #2110 only; worktree /home/dev/Git/wt/cr-2110, branch
fix/windows-bootstrap-prerequisite. Head f2789b09b513f2832b0cce947cb6614844561c86
(working tree clean at start); develop base f8a2df966a1d0db82be5fc08a571ed4750902c88.
Job directory /home/dev/maistro/jobs/0cebd6391f96450db4706001c3c7dd36. This record does
not close the issue and is not merge or integration approval.

## Why this round exists

The driver's merge-queue evaluation reported "CI gates red" with a truncated CI
response and forwarded the previous block's conclusion ("CI gates red with no
repairable findings; operator review required"). The driver ran no deterministic
checks this round (`checks: []` in the job manifest), so every gate was re-executed
locally here and the captured hosted evidence was inspected manually.

## Manual inspection of the truncated CI response (dispatch-context.json, captured 2026-11-16T15:57:38Z)

- `commits/f2789b09/check-runs`: 126 check-runs, all `completed`. 125 `success`,
  1 `skipped` — the skipped instance is job id 133337187842 of
  "Container scan + SBOM + cosign" (workflow run 43878328952, started 13:42:17Z);
  a sibling instance of the same job name on the same head sha started 13:43:32Z
  and finished `success` at 14:08:10Z. No failed check-run exists at head.
- Every gate named in the old red block has a `success` check-run at head:
  Compliance registry (13:42:43Z), Container scan + SBOM + cosign (14:08:10Z),
  Coverage gate (publish-set floor + diff coverage) — both instances success
  (14:22:11Z, 14:28:00Z), Gate C — canonical clean install (13:46:21Z),
  Quality / Acceptance state (13:50:58Z), Quality / Agent store writes (13:50:28Z),
  Quality / Architecture fitness (13:45:47Z), Quality / BFCL provenance (13:45:14Z).
- The real blocker: the required `gates-ran` commit **status** on f2789b09 is
  `pending` (six instances, latest 14:22:29Z; no final success/failure published by
  capture time, over an hour after the last check-run finished). `.github/workflows/gates-ran.yml`
  publishes that status from hosted `workflow_run` events on the default branch;
  it is publisher-side state that branch content cannot and must not influence.
  The PR timeline shows five auto-merge enable/disable cycles — the queue kept
  bouncing on that pending required status.

## Executed evidence at f2789b09 (all run locally by this lane, CI-exact arguments)

1. `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .` →
   "3561 files already formatted" (both exit 0).
2. Quality / Acceptance state, CI-exact: fresh pg18 database, `uv run alembic
   upgrade head`, then `RATCHET_BASE_REV=origin/develop uv run python
   scripts/check-ac-state.py --run-tests --ratchet --mandate f8a2df966a1d…` →
   exit 0; design_coverage 44.4608 (166 taken decisions); ratchet OK ("10 debt
   counters sit exactly on their ceilings and 1 progress counter sits exactly on
   its floor, folded from 48 note(s) at f8a2df966a1d"); criteria mandate: 0 added
   or newly claimed, 0 unproven; chain mandate: 0 absent links.
3. exact-debt-ledger / Quality / Vulture, CI-exact: `uv run python
   scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
   '*/third_party/*'` → exit 0 ("1238 reviewed identities -> 1238 findings",
   baseline base f8a2df966a1d, candidate f2789b09b513).
4. `scripts/check-ratchet-provenance.py` exit 0; `scripts/check-shipped-surface-truth.py`
   exit 0 (completes the vulture-ratchet workflow's local proof).
5. Compliance registry, CI-exact: `python3 scripts/check-compliance.py` → exit 0
   ("compliance registry and COMPLIANCE.md are valid").
6. Quality / Architecture fitness, CI-exact: `PYTHONPATH=packages/maistro-core/src
   RATCHET_BASE_REV=origin/develop uv run pytest packages/maistro-core/tests/fitness
   -q --timeout=30` → 39 passed.
7. Quality / Agent store writes: `scripts/check-agent-store-writes.py` exit 0
   (stores.agents mutated only by services/agent_materialization.py).
8. Quality / BFCL provenance: `scripts/vendor_bfcl.py --check` exit 0
   ("vendored BFCL tree OK (13 artifacts + shim)").
9. SAST gitleaks, CI-exact (gitleaks 8.30.1, the version sha256-pinned in
   security.yml): PR form `--log-opts=f8a2df966a…..f2789b09b…` → 17 commits, "no
   leaks found", exit 0; push fallback `f2789b09b…^..f2789b09b…` → "no leaks
   found", exit 0. The three fb322ab fingerprints in .gitleaksignore:186-203
   verified against the live files: test_attribution.py:462/476 pass a `context_key`
   variable beside a `ProducerKind` qualifier; test_task_admission_generation_upgrade.py:46
   defines synthetic lowercase 32-hex fixture constants for a CHECK contract —
   names and fixture hex, no credentials.
10. `uv run pytest tests/test_get_ps1_wsl_detection.py -q` → 28 passed (28.48s,
    pwsh 7.4.6 present, no skip).
11. `uv run pytest tests/test_distribution_contract.py -q` → 6 passed.
12. `pwsh -NoProfile -File tests/installer/run-wsl-detection-e2e.ps1` → all 23
    detection cases passed and the wired-in relaunch harness ran ("RESULT
    relaunch-policy ok"), exit 0.
13. Regression bite re-proven: `git show f8a2df966a1d:get.ps1` extracted to /tmp
    (worktree untouched); harness throws 'Unexpected elevation arguments'
    (relaunch_policy_harness.ps1:42) and exits 1 against the base get.ps1, which
    still carries `-ExecutionPolicy Bypass`; exits 0 against head get.ps1.
    Head get.ps1 grep for "ExecutionPolicy" matches only the read-only
    `Get-ExecutionPolicy -List` doc lines (71, 82); Invoke-Elevated (391-398)
    uses `-Verb RunAs` with `-NoProfile -File`, Register-Resume (402-409) writes
    the HKCU RunOnce string without any policy override.
14. `scripts/check-suite-inventory.py` → ok (21 suites);
    `scripts/check-backlog-consistency.py` → OK. Inventory note
    docs/testing/inventory-notes/security-windows-policy-prerequisite.md unchanged
    (`inventory-delta: tests/: +3`) — no test surface changed this round.
15. No `fixes/closes/resolves #N` in any commit body f8a2df966a…..f2789b09b….

## Conclusion

No repairable finding exists in the tree at f2789b09: every locally runnable gate
passes with CI's exact arguments, and the captured hosted evidence shows all 126
check-runs green (125 success, 1 skipped duplicate with a successful sibling).
The only red-adjacent signal is the required `gates-ran` commit status stuck
`pending` — hosted publisher state requiring operator attention (re-run of the
Gates Ran publisher / merge-queue re-admission), not a code change. Per the
brief, no guessed scanner findings or cosmetic changes were introduced: the only
edit this round is this evidence note.

## Residual risks

- Real Windows PowerShell 5.1 behavior (native UAC prompt, RunOnce resume,
  effective policy after logon) remains unverifiable in WSL; covered by the
  mocked real-function AST harness and honestly disclosed in the PR body.
- The skipped Container-scan instance (job 133337187842) is a conditional-duplicate
  of a job that succeeded on the same sha; if branch protection keys on the job
  name, hosted evaluation already has a success instance to credit.
- If the `gates-ran` publisher never resolves on its own, the PR stays blocked
  regardless of branch content — operator review required, as the previous block
  concluded.
