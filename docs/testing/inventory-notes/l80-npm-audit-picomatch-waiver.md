---
inventory-delta:
  tests/: +12
---

# L80 — npm audit gate for the unpatchable picomatch advisory (GHSA-fc5q-39xc-vjpf)

The `test` job's bare `npm audit --audit-level=high` step over
`packages/maistro-canvas/frontend` became unsatisfiable on every tree when
GHSA-fc5q-39xc-vjpf (published 2026-10-19) landed: the advisory lists *every
published picomatch* as vulnerable (`<=4.0.7`; 4.0.7 is the newest release)
with **no patched version**, and picomatch is a hard dependency of the
frontend's dev toolchain — `vite@8.3.8` depends on `picomatch ^4.0.7`
directly, tinyglobby 0.2.17 depends on it too. This is develop-borne, not
branch-borne: `origin/develop` (d0e8e235a8) carries the identical lock
versions (picomatch 4.0.7, vite 8.3.8, vitest 5.1.0), so the step fails on
develop tip as well.

Evidence that no lock-based repair exists (all executed 2026-11-18):

- `npm audit --audit-level=high` at the branch head: exit 1, 6 high
  (picomatch cascade).
- `npm audit fix --force` in a scratch copy: exit 1, and the resulting tree
  still fails the audit — the forced fix downgrades into an older vite tree
  carrying additional launch-editor and vite advisories (1 moderate, 4 high,
  2 critical).
- `https://api.github.com/advisories/GHSA-fc5q-39xc-vjpf`: `vulnerable:
  <= 4.0.7`, `first_patched_version: null`.

## Behavior change

Same shape as the Python supply chain (PYSEC-2026-1325 "no planned fix" in
`scripts/pip_audit_gate.py`), same answer — one list, one verdict:

- `.github/workflows/ci.yml`: the `test` job's audit step now writes
  `npm audit --json > /tmp/npm-audit.json || true` and
  `python scripts/npm_audit_gate.py /tmp/npm-audit.json` owns the verdict.
- `scripts/npm_audit_gate.py` (new): fails on any high/critical advisory
  whose ID is not in the triaged `ALLOWED` dict — resolving npm's
  "Depends on vulnerable versions of X" cascade transitively so the verdict
  names the root advisory ID; quotes npm's `fixAvailable` as the hint;
  treats empty/unparseable/registry-error reports as infrastructure failure
  (exit 3), never a clean verdict; and fails on a waiver whose advisory is
  no longer reported (two-way ratchet — the waiver must be deleted once
  picomatch ships a patch and the lock is refreshed). Nothing else is
  relaxed: a future advisory on the same packages has a different ID and
  blocks until triaged on its own merits.

## Test delta

- `tests/test_npm_audit_gate.py` (+12): fixtures mirror the real
  `npm audit --json` shape captured at the branch head (one root advisory
  object, five cascade strings). Covers: the live waiver passing the real
  cascade; unwaived advisory failing with ID + affected packages + npm's fix
  hint; a second advisory on the same chain not covered by the first
  waiver; cascade attribution in both directions; moderate/low never
  blocking; critical blocking; empty/unparseable/registry-error/malformed
  reports exiting 3 (infrastructure); stale waiver failing (exit 1); usage
  error (exit 2). Pure unit tests over canned JSON — no npm invocation, no
  network.
