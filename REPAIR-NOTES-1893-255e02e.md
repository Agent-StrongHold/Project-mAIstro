# Repair round at 255e02e3 (job 070b3007) — #1893

Starting head verified exactly `1790729ef4dd7d506410b77298a3b0a11da5f2d7`
(worktree clean). Scope snapshot: resolve the carried BLOCKED round for issue
#1893 — develop sync + gate re-proof. No source or test edits; no ledger,
grant or gate edits; no GitHub mutations.

## What this round did

1. **Develop sync (the brief's conditional instruction).** `git fetch origin`:
   `origin/develop` = ab8b3737 (#1627, graph beam test + retired-guidance scan
   tightening) — one commit ahead of the branch's old merge base ac737014.
   `git merge-tree` probe exit 0, then
   `git merge --no-edit origin/develop` → merge commit **255e02e3411f**,
   conflict-free. Post-merge quality integrity proven
   (`git diff --numstat origin/develop -- quality/`: only the branch's two
   intended reachability ledgers, +2/+11, no row loss; retired-guidance.json
   identical to develop).
2. **Suite inventory aligned.** The merge delivers
   `tests/test_check_retired_guidance.py`; the branch's baseline already
   recorded develop's root-suite count, so the full
   `scripts/check-suite-inventory.py` is green at the merged head (17 suites,
   tests/ 5210 == recorded, 0 duplicate evidence) — the merge repaired a
   latent root-suite drift the pre-merge single-suite driver check could not
   see. Inventory delta of the round: 0 (truthful note:
   `docs/testing/inventory-notes/atomic-admission-1893-verify-255e02e.md`).
3. **Lane-named `test: failure` disproven three ways at this head.**
   (a) Live read-only `gh run list --branch auto-1893`: latest branch runs
   show **CI success, quality success**, only **Vulture Ratchet failure**;
   (b) all seven CI `test` legs re-executed locally in CI env — root
   `tests/ --ignore=tests/tools/registry` 4982 passed 135 skipped, server
   557+8sk, turing 210, turing/backend 90, design 572+1sk, ext-harness 273,
   ext-sdk 147 — all green;
   (c) driver battery green (ruff check/format, focused pytest 400+3sk,
   mypy core 791 files Success, suite inventory ok).
4. **exact-debt-ledger decomposed at CI argv** with the trusted base now
   resolving to the current develop tip: shipped-surface-truth exit 0;
   vulture CI-argv exit 0 (1322 = 1322 — the permitted vulture amendment has
   no target); `check-ratchet-provenance.py` exit 1 on **exactly**
   maistro.runs.admission_identity + maistro.tasks.admission_codec (NEW
   unreachable/dispositioned, not authorized from base). Candidate-side
   reachability exit 0 (171 banked / 50 groups) and
   `check-retired-guidance.py` exit 0 post-merge.
5. **Two-merge wall re-proven unchanged:** grant commit 3235229f5fed is not
   an ancestor of origin/develop; develop's ratchet-authorizations.json has
   11 reachability grants, none admission-related. Because develop is now
   merged in, the trusted base *is* develop's tip and the candidate ledgers
   are already correct — the provenance gate passes the moment the grant's
   content lands on develop (owner-side push; worker-prohibited). An
   in-branch grant is inert by construction and forbidden by the issue
   ("no baseline/grant/gate modifications to make an unwired slice green");
   unwiring the baseline rows would instead fail the candidate-side
   reachability gate. No closure keywords against #1893.

## Handoff state

Everything provable in-branch is proven and committed. Remaining blocker
(external, single): owner lands the reachability authorization for the two
admission-contract modules on develop; no further branch change is required
afterwards — `RATCHET_BASE_REV=origin/develop
scripts/check-ratchet-provenance.py` passes with the ledgers as committed.
