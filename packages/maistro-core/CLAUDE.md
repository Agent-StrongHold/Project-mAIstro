# CLAUDE.md — maistro-core

This file provides guidance to Claude Code (claude.ai/code) when working in `packages/maistro-core/`.
See the repo-root CLAUDE.md for the full subsystem map; this file only adds the in-directory dev loop and conventions.

## Test loop

```bash
# All core tests
PYTHONPATH=packages/maistro-core/src pytest packages/maistro-core/tests/ -q

# One subsystem (keyword filter)
PYTHONPATH=packages/maistro-core/src pytest packages/maistro-core/tests/ -k memory -q

# Single test
PYTHONPATH=packages/maistro-core/src pytest packages/maistro-core/tests/test_circuit_breaker.py::test_name -v
```

`tests/conftest.py` sets `MAISTRO_DRY_RUN=1` (no real LLM calls), high rate limits, and autouse fixtures that
reset singletons and disable the auth requirement between tests. Override per-test when you need real auth/limits.

Use `maistro.testing` for fixtures: `FauxProvider`, `FauxResponse`, `ToolCallDef`, `HarnessEnvironment`,
`create_test_environment()`.

## Conventions (these are load-bearing)

- **`AgentConfig` is canonical.** `MaistroConfig`/`MaistroError`/`StrongholdError` are backwards-compat aliases —
  use the canonical names in new code.
- **No `org_id` in core.** Multi-tenant isolation is Stronghold-only. Keep scope isolation
  (global → team → user → agent → session); do not add org-level coupling.
- **Protocol-driven DI.** Business logic depends on `maistro.protocols` (abstract interfaces), never concrete
  implementations. New subsystems wire through `container.py`.

## Lint / types

```bash
ruff check packages/maistro-core/src
mypy packages/maistro-core --strict   # CI enforces strict on core
```
