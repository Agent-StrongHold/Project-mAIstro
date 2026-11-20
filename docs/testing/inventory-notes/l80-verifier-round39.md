---
inventory-delta:
  packages/maistro-bootstrap/tests: +0
  packages/maistro-core/tests: +0
---

# L80 verifier round 39 — develop-sync state confirmed; carried suite-inventory drift proven environmental (reproduces identically on origin/develop); full gate battery green at 620cf68aacf2

Head under validation: `620cf68aacf2` (clean worktree, no code edits this
round — this note records executed evidence). Base: `f927334a2e` (M2-B1).

## 1. Previous block — develop sync conflict: already resolved in-tree, verified

The lane brief carried "develop sync conflict preserved in worktree; resolve
before verification". The resolution is already committed:
`ec9dd31316` merges origin/develop (f927334a) into auto-80 and `620cf68aac`
re-points the sandbox lane onto the M2-B1 canonical selector. Verified live:
`git merge-base HEAD origin/develop` = `f927334a2e…` = `git rev-parse
origin/develop` — the branch contains develop tip and origin/develop has not
moved since. No conflict remains.

## 2. Carried validation failure (check-suite-inventory, bootstrap 318 vs 278) — environmental, not a regression

The prior round's `check-4.log` recorded `DRIFT packages/maistro-bootstrap/
tests: expected 318, collected 278 (net -40)`. Re-produced at this head
(`uv run python scripts/check-suite-inventory.py` → same DRIFT line), then
root-caused instead of papered over:

- `git diff origin/develop...HEAD -- packages/maistro-bootstrap/tests` adds
  exactly three files (`.dockerignore`, `Dockerfile.sandbox`,
  `test_container_lane.py`, +99 lines) and deletes nothing.
- Fresh detached worktree at origin/develop `f927334a` (removed after the
  probe; it was a clean checkout, zero unique files), collected with the
  identical venv (uv.lock has zero diff between develop and this branch):
  **277** bootstrap nodes vs this branch's **278**. Sorted node-ID diff is
  exactly `+ test_container_lane.py::test_lane_masks_securityfs_privately_
  and_drops_privileges` — the +1 already recorded in
  `cr1450-develop-sync-m2b1-reconciliation.md`.
- The 40-node gap is therefore an environment artifact of this WSL host that
  reproduces identically on untouched develop (317 CI-expected vs 277 here;
  318 vs 278 on the branch). CI's ubuntu runner collects the full suite and
  the gate is green there (last merge-queue evaluation: green). Nothing to
  repair; no `--update`, no delta re-recording — the recorded +1 is accurate.

The branch's own bootstrap collection: 278 nodes = 276 passed + 2 skipped,
both skips by design (`test_builders_sandbox.py:175` Windows-only escape
proof; `test_container_lane.py:19` opt-in designated-rootless-lane test that
CI's sandbox-conformance lane provisions and runs).

## 3. Executed validation battery at this head (all green)

- `uv run pytest packages/maistro-core/tests/sandbox/ -q` → **248 passed,
  38 skipped** (skips = live-backend opt-ins: Kata live conformance et al.,
  executed by the quality.yml producers in CI).
- `uv run pytest packages/maistro-bootstrap/tests -q` → **276 passed,
  2 skipped** (both by design, see above).
- `uv run pytest tests/test_distribution_contract.py
  tests/test_unit_suite_execution_partition.py -q` → **12 passed**.
- `uv run pytest tests/test_devskim_scan_scope.py -q` → **21 passed**.
- `uv run ruff check .` → All checks passed; `uv run ruff format --check .`
  → 3570 files already formatted.
- CI-exact vulture: `uv run python scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → **RC=0**
  (1236 reviewed identities → 1236 findings, balanced against base
  f927334a). Gate green ⇒ no ledger amendment required this round.
- Gate scripts (RC=0 each): `check-image-pins.py`, `check-test-duplicates.py`,
  `check-branch-protection.py`, `check-required-checks.py`,
  `check-image-inventory.py`, `check-ac-state.py` (writes the gitignored
  `quality/ac-state.json` only), `check-workflow-inventory.py`,
  `check-workflow-write-safety.py`.
- `bash -n scripts/ci-rootless-mountns.sh` → syntax OK.
- Fail-closed selector refusal (the CI lane's contract) is unit-proven in
  production terms at
  `packages/maistro-bootstrap/tests/test_container_sandbox.py::
  test_a_host_without_a_strong_enough_backend_refuses` — an empty selector
  (no evidenced backend) makes the production `ContainerBuilderSandbox.
  __enter__` raise `NoSuitableBackendError` with the host repo untouched.
  The live no-VM proof cannot reproduce on this host because Kata+KVM are
  genuinely evidenced here (same detection the kata live lane relies on) —
  exactly as documented in the round's reconciliation note.
- `check-image-lock-reconciliation.py` skipped: not a CI gate (requires
  `--image`; never invoked by ci.yml).

## 4. M2-B5 acceptance mapping (claim-stake #1450 → real coverage)

- Real escape/conformance coverage ships in
  `packages/maistro-core/tests/sandbox/` (escape conformance, network
  default-deny, credential boundary, host-path boundary, selector, single
  authority, launcher VM — 248 passing locally).
- The branch's `sandbox-conformance` CI lane is the M2-B1-reconciled
  contract lane: real-image build from a context that never ships the repo
  (`Dockerfile.sandbox` + `.dockerignore`), fail-closed selector proof on a
  runner with no vm-tier backend, then the rootless userns lane
  (`scripts/ci-rootless-mountns.sh`) running the builders image contract
  non-root with `--network=none` under an enforced memory budget.
- Registered checks stay consistent: branch-protection and
  REQUIRED-CHECKS.md gates pass (RC=0).
