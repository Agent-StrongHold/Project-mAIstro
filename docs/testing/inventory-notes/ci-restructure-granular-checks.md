---
inventory-delta:
  tests/: +0
---

# CI granular-check restructuring

No pytest suites or node IDs changed (`tests/: +0`). The validation
surface is workflow-contract validation rather than application tests:

- `yaml.safe_load` over every workflow;
- `scripts/check-required-checks.py` and generated required-check tables;
- `scripts/check-branch-protection.py` and generated protection tables;
- `scripts/check-workflow-write-safety.py`;
- `scripts/check-suite-inventory.py` (unchanged inventory).

The quality and SAST commands retain their original arguments and baselines;
service-coupled CI jobs remain grouped where their ordering is part of the
assertion.
