---
inventory-delta:
  tests/: +1
---
# fix-gates-ran-devskim-reconciliation

The required-check contract test now includes the owner-added `DevSkim` workflow
in the exact base-coupled set derived by `collect()`. The check remains advisory,
not required: `.github/branch-protection.json`, `REQUIRED-CHECKS.md`, and
`BRANCH-PROTECTION.md` state that classification consistently.

The quality-gate reconciliation also records the CI AC-state measurement from
run `34671371678`: `design_coverage` was `35.6796`, above the prior floor
`33.9095`. The per-branch note preserves that measured improvement without
weakening the ratchet.
