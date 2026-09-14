---
inventory-delta: add canonical Kata backend selector and lifecycle conformance coverage
---

# Issue 76 inventory delta

Added focused tests for the canonical Tier-1 Kata backend launch contract,
explicit egress behavior, no Docker-socket mount, and selector reachability for
all four standard workload policies. Tests use command construction and an
injected backend only because this development host does not expose a Kata
runtime; live VM containment remains deployment-profile validation.
