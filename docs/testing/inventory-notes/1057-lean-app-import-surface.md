inventory-delta:
  packages/maistro-server/tests: +1
---

# #1057 CI repair — importing the server app must not require the `[llm]` extra

The lane's CI `test` job (run 36269196110, job 108479774008) failed at the
hive-conductor backend step while every workspace-venv run was green. Root
cause, found by mirroring the CI interpreter (`uv pip install -r
packages/hive-conductor/backend/requirements.txt` into a clean Python 3.12
venv): the #1057 two-user E2E
`test_production_workspace_scope.py::test_shared_bridge_keeps_two_authenticated_user_tasks_isolated`
imports `maistro_server.main` to exercise the real server ASGI boundary, and
that module eagerly imported `maistro.tools.sandbox.server` — the one import
in its graph that pulls maistro-core's optional `[llm]` extra (fastmcp).
Hive's requirements file deliberately omits that stack (the shipped image
opts in via a build-arg, #668), so the import failed with
`ModuleNotFoundError: No module named 'fastmcp'` in exactly that one job.

Repair (`packages/maistro-server/src/maistro_server/main.py`): the sandbox
cleanup import moved from module scope into the lifespan's shutdown path and
degrades to a no-op when the extra is absent — a missing sandbox stack means
no sandbox containers exist, so there is nothing to tear down. Skipping the
call is correct, not a fallback.

**+1 `packages/maistro-server/tests/test_import_surface.py`**:

- `test_importing_the_app_does_not_require_the_llm_extra` — imports
  `maistro_server.main` in a clean subprocess whose import finder blocks
  `fastmcp` resolution, reproducing the lean CI interpreter's shape. Fails
  with the original ModuleNotFoundError if the app's import graph ever again
  reaches for an optional extra at module scope.

Validation on this head: CI-mirror venv full hive battery 2870 passed /
6 skipped (1 failed before the repair);
`packages/maistro-server/tests` 400 passed (399 + this test);
`packages/maistro-core/tests/tasks` 370 passed / 14 skipped;
mypy --strict on all package sources clean; ruff check and format clean.
