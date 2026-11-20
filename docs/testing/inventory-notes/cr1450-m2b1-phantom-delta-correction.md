---
inventory-delta:
  packages/maistro-bootstrap/tests: -40
---

# CR1450 — the bootstrap ledger still counts tests the M2-B1 merge deleted

Corrective ledger delta for PR #1450 (issue #80, M2-B5). This note supersedes
the "environmental gap" claim in `l80-verifier-round39.md`,
`l80-verifier-round40.md`, and the closing paragraph of
`m2-b5-seed-symlink-boundary.md`: **there is no host-vs-CI collection gap.**
The recorded expectation, not the collection, is what drifted.

## Evidence (all executed 2026-11-17)

CI itself refutes the environmental claim:

- `test` job at this branch's head `abede31fb3` (run 44029080504, job
  133856475500) failed its "Suite inventory matches collected node IDs
  (C1/#286)" step with `DRIFT packages/maistro-bootstrap/tests: expected 319,
  collected 279` — **collected 279 on the ubuntu-24.04 runner**, byte-identical
  to this WSL host's collection (reproduced locally with `uv run pytest
  packages/maistro-bootstrap/tests --collect-only -q` → 279).
- The M2-B1 PR's own head `ddb5c06420d0` had `test` **success** in CI: the
  ledger there sums to 234 + 43 = **277** and CI collected 277. Develop tip
  `f927334a` (same content, squash of #2241) carries the same ledger. A green
  gate on the runner and 277 collected here is two anchors on the same number,
  not two environments that disagree.

## Where the 40 went

Ledger arithmetic (baseline `counts` 234 + unfolded note deltas):

| tree | recorded expected | collected (CI and this host) |
|------|-------------------|------------------------------|
| develop `f927334a` / M2-B1 head `ddb5c064` | 277 | 277 (CI green) |
| branch `620cf68aac` (round 39) | 318 | 278 |
| branch `abede31fb3` (this head, pre-correction) | 319 | 279 |

The branch's notes record a net **+42** against develop's 43, but the branch
adds exactly **+2** real nodes relative to develop — the whole three-dot test
diff (`git diff origin/develop...HEAD -- packages/maistro-bootstrap/tests`)
is one new file with one test (`test_container_lane.py::
test_lane_masks_securityfs_privately_and_drops_privileges`, recorded +1 in
`cr1450-develop-sync-m2b1-reconciliation.md`) and one added test
(`test_container_sandbox.py::
test_seed_never_materializes_what_a_worktree_symlink_points_at`, recorded +1
in `m2-b5-seed-symlink-boundary.md`). Nothing was deleted branch-side. The
remaining **+40** of recorded delta name tests that no longer exist anywhere:
the Docker-backed private builder-sandbox suite (`test_container_sandbox.py`
boundary/userns/seed-sentinel nodes, `test_container_sandbox_hardening.py`
identity-`uid_map` pins, `test_container_sandbox_output_bound.py` probes)
whose +deltas the branch's rounds 6–37 notes recorded, and whose
implementation **the M2-B1 merge deleted** when it adopted develop's
canonical selector architecture (1003/652/324-line rewrites of those three
files, −1337 lines total, in `ec9dd31316`; round-40's own commit message
calls them "the old sentinel tests"). Principal carrier notes: +11
`080-sandbox-rootless-userns-conformance`, +8 `l80-seed-path-replacement`,
+7 `m2-b5-seed-failure-cleanup`, +6 `m2-b5-container-builder-conformance`,
+4 `l80-lane-provisioning-repair`, +2 each `l80-uid-map-root-range-repair`,
+1 each `l80-securityfs-lane-repair`, `l80-shm-mqueue-read-only`,
`m2-b5-container-sandbox-repair` — 41 gross, offset by the −1 in
`auto-80-e205`, netting the 40 corrected here. Per-node attribution inside
those notes is not recoverable post-merge and is not needed: the gate
compares nets, and the net correction is exactly `--update`'s −40.

## Why a corrective note and not `--compact`

`--compact` would fold the phantom into `baseline.json` silently. A recorded
delta keeps the correction reviewable and names the merge that caused it.
Expected becomes 234 + 43 = 277 on develop side plus the branch's true +2 →
**279 = collected**, on CI and on any host that installs the dev group — the
number both environments already agree on.

## Validation at this head

- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-bootstrap/tests` → PASS (expected 279, collected 279).
- `uv run pytest packages/maistro-bootstrap/tests -q` → green (277 passed,
  2 by-design skips).
- `.github/workflows/ci.yml` sandbox-conformance fail-closed proof fixed in
  the same round: the step now runs `uv run --extra bootstrap python`
  (`maistro_bootstrap` is a workspace member shipped only in the root
  `bootstrap` extra; CI jobs 133856475787 and 133845373917 died on
  `ModuleNotFoundError: No module named 'maistro_bootstrap'` before reaching
  the selector). Import path proven locally with the same interpreter uv
  would sync; the refusal behavior itself stays pinned by
  `test_container_sandbox.py::test_a_host_without_a_strong_enough_backend_refuses`.
