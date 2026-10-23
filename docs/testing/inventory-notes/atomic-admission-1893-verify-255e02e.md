---
inventory-delta:
  tests/: 0
  packages/maistro-core/tests: 0
---

# #1893 verification round at 255e02e3 (develop-sync merge)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`1790729ef4dd7d506410b77298a3b0a11da5f2d7`, worktree clean at entry. This
round's one tree change is the lane-brief-sanctioned develop sync:
`git merge --no-edit origin/develop` (ab8b3737, #1627) → merge commit
`255e02e3411fceb7b368aff418656eb45866b7b1`, conflict-free
(`git merge-tree` probe exit 0 before executing). No source, test, ledger,
grant or gate edits; no GitHub mutations.

## Inventory effect of the merge

`tests/test_check_retired_guidance.py` (+4 node IDs) arrives with the merge;
`docs/testing/inventory/baseline.json` was **not** touched by the merge
(`git diff HEAD~1..HEAD --stat -- docs/testing/inventory/baseline.json`
empty) because the branch's baseline already carried develop's root-suite
count from an earlier shared state — the merge therefore *repairs* a latent
root-suite drift rather than creating one. `scripts/check-suite-inventory.py`
at the merged head: **exit 0, 17 suites ok, `tests/` 5210 == recorded,
31451 collected == 31451 unique, 0 duplicate evidence**. Net inventory delta
of this round: 0.

## Fresh evidence executed at 255e02e3

- Driver battery: `uv run ruff check .` (All checks passed),
  `uv run ruff format --check .` (3301 files already formatted),
  focused pytest (cli_lock, pack_contracts, root_admission_identity,
  admission_codec, graph test_protocol) **400 passed, 3 skipped**, of which
  the B2 pair alone is **201 passed, 3 skipped**; mypy
  `packages/maistro-core/src`: **Success, 791 files**.
- CI `test` job legs, CI env (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):
  `tests/ --ignore=tests/tools/registry` **4982 passed, 135 skipped**;
  server **557 passed, 8 skipped**; turing **210**; turing/backend **90**;
  design **572 passed, 1 skipped**; ext-harness **273**; ext-sdk **147**.
  The lane-named `test: failure` is not reproducible.
- Live read-only CI attribution (`gh run list --branch auto-1893`): latest
  runs on the branch — **CI success, quality success, Vulture Ratchet
  failure**, DevSkim success, Gate C success. The only red workflow is
  `Vulture Ratchet` → job `exact-debt-ledger`.
- exact-debt-ledger at CI-exact arguments, base now resolving to the current
  develop tip (ab8b3737) after the merge:
  `check-shipped-surface-truth.py` exit 0;
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0 (**1322 reviewed = 1322 findings** —
  the lane-brief vulture amendment still has no target);
  `RATCHET_BASE_REV=origin/develop check-ratchet-provenance.py` exit 1 on
  **exactly** the two reachability entries (`maistro.runs.admission_identity`,
  `maistro.tasks.admission_codec`: NEW disposition/unreachable module not
  authorized from the trusted base). Every other ratchet OK.
- Candidate-side legs: `check-reachability.py packages` exit 0 (1403
  production modules, **171 unreachable**); `check-reachability-dispositions.py`
  exit 0 (**50 groups** cover all 171: 149 CONNECT, 20 LIBRARY, 2 RETIRE);
  `scripts/check-retired-guidance.py` (CI argv, ci.yml:216) exit 0 — the
  merged #1627 scan change finds nothing in this tree.
- quality/ integrity after merge: `git diff --numstat origin/develop --
  quality/` = +2/-0 reachability-baseline.json, +11/-0
  reachability-dispositions.json only; `retired-guidance.json` merged to
  develop's version (the pre-merge 1-line delta was develop's own #1627
  change), zero silent row loss.

## Structural blocker (unchanged, re-proven at the merged head)

The two-merge wall stands: `git merge-base --is-ancestor 3235229f5fed
origin/develop` → **NO** (the prepared reachability grant commit is not on
develop), and `origin/develop:quality/ratchet-authorizations.json` has 11
reachability grants, **none** naming an admission module. With develop now
merged into this branch, the trusted base *is* the current develop tip — the
candidate ledgers are already correct, so `check-ratchet-provenance.py`
passes the moment the grant's authorization content lands on develop (a
develop-side push, worker-prohibited). An in-branch grant is inert by
construction (`ratchet_provenance.load_authorizations` reads the merge base)
and forbidden by the issue ("no baseline/grant/gate modifications to make an
unwired slice green"); removing the baseline rows instead would fail the
candidate-side reachability gate, since the modules are genuinely unwired
(their consumer is leaf C). No closure keywords against #1893.
