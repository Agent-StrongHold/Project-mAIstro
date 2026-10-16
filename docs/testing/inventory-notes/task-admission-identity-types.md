---
inventory-delta:
  packages/maistro-core/tests: +79
---

# Admission identity types (#1851)

Added contract tests for the inactive root-admission identity types module.

- New test file: `packages/maistro-core/tests/runs/test_root_admission_identity.py` (79 tests)
- New source module: `packages/maistro-core/src/maistro/runs/admission_identity.py` (defines 21 DTOs and enums)

The tests cover canonical JSON snapshots, immutability, fencing conjunctions, variant validation, and repr hygiene. They pass and prove the type contract only; the module has no runtime consumer in this leaf.