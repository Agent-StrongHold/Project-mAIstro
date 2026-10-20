---
inventory-delta:
    packages/maistro-core/tests: 5
---

# Issue 76 inventory delta

Added focused tests for the canonical Tier-1 Kata backend launch contract,
explicit egress behavior, no Docker-socket mount, and selector reachability for
all four standard workload policies (net +5: `test_kata_backend.py` adds five;
`test_real_backend.py` swaps the `preexec_fn` hook test for the thread-safe
exec-helper test, net zero there). Tests use command construction and an
injected backend only because this development host does not expose a Kata
runtime; live VM containment remains deployment-profile validation.
