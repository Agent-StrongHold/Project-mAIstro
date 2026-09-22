---
inventory-delta:
  tests/: +8
---
# Issue 1134 — backend namespace fitness check

Added five tests for `scripts/check-backend-package-namespaces.py`: the retained
backend layout passes, a flat `main.py` is rejected, a Python-bearing directory
outside an approved application package is rejected, a `backend/__init__.py`
that would make the directory itself importable as the generic top-level name
`backend` is rejected, and an unknown backend namespace is rejected. The check
now flags a root `backend/__init__.py` instead of silently permitting one;
the vestigial `packages/maistro-turing/backend/__init__.py` was removed with
it (nothing imported `backend.*`; the shipped `uvicorn
maistro_turing_backend.main:app` startup path is exercised by test and passes
without it). `packages/maistro-turing/backend/tests/__init__.py` was removed
too: it only existed to give the suite the `backend.tests` package identity,
which required the forbidden root package marker; the suite now uses bare
module names like the hive-conductor suite (the repo runs pytest with
`--import-mode=importlib`, and the combined root + Turing + Conductor session
passes, including both `test_auth.py` basenames, which resolve as `test_auth`
vs `tests.api.test_auth`). Added subprocess coverage that imports both ASGI applications and
their route/middleware modules without generic module aliases, then starts the
documented Turing `uvicorn` command from its backend directory. Added a
reachability regression asserting packaged application roots remain canonical
while the scanner retains scoped identities for its ratchet. The five Turing
entries in `quality/shipped-surface-truth.json` were repointed from the pre-
namespace flat `backend/routes/*.py` paths to
`backend/maistro_turing_backend/routes/*.py` — a pure rename forced by this
migration; `check-shipped-surface-truth.py` (the `exact-debt-ledger` CI gate)
now passes.
