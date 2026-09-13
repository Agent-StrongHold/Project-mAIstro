---
inventory-delta:
  tests/: +4
---
# Issue 1134 — backend namespace fitness check

Added three tests for `scripts/check-backend-package-namespaces.py`: the retained
backend layout passes, a flat `main.py` is rejected, and a Python-bearing
directory outside an approved application package is rejected. Added one
subprocess test that imports both ASGI applications and their route/middleware
modules without generic module aliases.
