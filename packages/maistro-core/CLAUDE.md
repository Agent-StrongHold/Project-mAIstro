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
- **Soft scope here; hard tenancy in the importing product.** maistro-core carries the soft scope
  axes `global → org → team → user → agent → session` — a user may be in several teams and orgs, so
  `org`/`team` filters here are legitimate scope (ADR-013/015/016/017). Only the *hard* `tenant`
  boundary — fully segmented, one tenant per user — belongs to Stronghold.
  See root `CLAUDE.md` decision 7 and **ADR-068**; ADR-019 §"Scope vs. tenancy" carries the amendment.
  This bullet used to read *"No `org_id` in core"*, which conflated scope with tenancy and is
  **superseded** — core has ~214 `org_id` references and the schema has carried the column for
  releases (#386).
- **Protocol-driven DI.** Business logic depends on `maistro.protocols` (abstract interfaces), never concrete
  implementations. New subsystems wire through `container.py`.

## Lint / types

```bash
ruff check packages/maistro-core/src
mypy packages/maistro-core --strict   # CI enforces strict on core
```
