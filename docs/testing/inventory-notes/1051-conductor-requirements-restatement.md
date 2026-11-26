---
inventory-delta:
  tests/: +1
---
# Issue #1051 — Conductor CI requirements restatement guard

## The failure this guards

CI run 45824755339 (job 139926293188, head c5aff8768bee) red with **93
collection errors** in the `test` job's
`python -m pytest packages/hive-conductor/backend/tests` step, every one
`ModuleNotFoundError: No module named 'defusedxml'`, while every
workspace-environment gate stayed green. The mechanics: the step installs
ONLY `packages/hive-conductor/backend/requirements.txt` into the system
interpreter (`uv pip install --system -r ...`), then collects the backend
suite, which reaches maistro-core from SOURCE through the root pytest
`pythonpath` — so `maistro` imports fine while any third-party module core
imports unconditionally must be *installed* by that file. `defusedxml`
became a core hard dependency for discovery feed parsing (commit 8969f944fa,
`maistro/capabilities/providers/discovery_source.py`), and
`maistro.graph`'s node-module sweep pulls that provider into every graph
import — but it was never restated, breaking the contract the requirements
file's own comments state (#839: "its hard deps must be restated here").

## The repair (+0 conductor, +1 root)

- `packages/hive-conductor/backend/requirements.txt` (+0 tests): restate
  `defusedxml>=0.7,<1` at core's floor, with the sys.path-contract comment
  the file's siblings carry. No test count moves anywhere; the backend
  suite still collects exactly its recorded 4699 node IDs (proven by
  running the exact CI command in a requirements-only venv: 4587 passed,
  112 skipped).
- `tests/test_verify_minimum_dependencies.py` **+1**:
  `TestDeclaredFloors::test_every_core_hard_dep_is_restated_in_the_conductor_ci_requirements`.
  Statically pins the contract that was violated: every hard dependency
  declared in `packages/maistro-core/pyproject.toml` must appear in the
  conductor's no-lockfile requirements file, unless it is consciously
  soft-imported (imported under `try/except ImportError` — today exactly
  pgvector, guarded in `maistro/memory/store.py`) and recorded in the
  test's `SOFT_IMPORT_ALLOWLIST`. Presence-only by design: floors are
  deliberately independent between core's publish floor and the CI
  resolution (the PyJWT floor-agreement test covers the one dep where
  agreement IS the contract). Proven against its regression: with the
  requirements line removed the test fails naming `['defusedxml']`; with
  the fix it passes. This is the guard that would have caught 8969f944fa
  at PR time.
