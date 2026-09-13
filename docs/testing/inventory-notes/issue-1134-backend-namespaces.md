---
inventory-delta:
  tests/: +7
---
# Issue 1134 — backend namespace fitness check

Added four tests for `scripts/check-backend-package-namespaces.py`: the retained
backend layout passes, a flat `main.py` is rejected, a Python-bearing directory
outside an approved application package is rejected, and an unknown backend
namespace is rejected. Added subprocess coverage that imports both ASGI
applications and their route/middleware modules without generic module aliases,
then starts the documented Turing `uvicorn` command from its backend directory.
Added a reachability regression asserting packaged application roots remain
canonical while the scanner retains scoped identities for its ratchet.
