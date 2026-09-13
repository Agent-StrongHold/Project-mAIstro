---
inventory-delta:
  tests/: +3
---

# CI granular-check restructuring

No pytest suites changed; the contract surface adds one class with three
test nodes to `tests/test_check_required_checks.py` (`tests/: +3`). The
validation surface is workflow-contract validation rather than application
tests:

- `yaml.safe_load` over every workflow;
- `scripts/check-required-checks.py` and generated required-check tables;
- `scripts/check-branch-protection.py` and generated protection tables;
- `scripts/check-workflow-write-safety.py`;
- `scripts/check-suite-inventory.py` (unchanged inventory).
- `tests/test_check_required_checks.py::TestReusableWorkflowNames` verifies
  caller/callee composed check names; its real-workflow checks pin PostgreSQL
  routing for Hypothesis and topic-branch Vulture coverage.

The quality and SAST commands retain their original arguments and baselines;
service-coupled CI jobs remain grouped where their ordering is part of the
assertion.
