---
inventory-delta:
  packages/maistro-core/tests: +9
---
# L1856: failed Container construction keeps the live default effect context

Issue #1856 (parent #55) at branch `auto-1856`; this note's delta covers the
nine lifecycle tests the lane added on top of develop (eight for the effect
context and resource cleanup at head `31d891a5`, plus the quota-tracker
default test at head `26a4ec3c3`). Develop base now `420d503d4` after two
conflict-free `origin/develop` sync merges (`33dd02f`, then the
deps-bump-only merge `b2787cf89`).

Eight `packages/maistro-core/tests` node IDs arrive in
`test_container_effect_context_lifecycle.py`, all pinning one boundary: a
`create_container` startup that fails at the real model-binding bootstrap
rejection (`ModelBindingConfig(binding_id="bad", project_id="p",
credential_refs=("unregistrable-ref",))` — never mocked into a no-op) must
neither replace the process-default effect context nor leak the resources it
opened.

- Prior state (1) — live outer Container: the exact captured
  `default_effect_context()` object is still the default after the
  `ConfigError`, and still serves. Prior state (2) — cached fallback, no live
  Container: the exact fallback object survives. A retry publishes its own
  context; an injected caller-owned context is neither mutated nor published.
- Resource cleanup: the four SQLite connections a failed `sqlite://` startup
  opened are closed (failing-before: they stayed usable); the PostgreSQL pool
  the attempt opened through the registry is released (`pool_count()`
  restored — failing-before: `1 != 0`); a caller-supplied pool and an
  existing Container's connections stay open. The two PostgreSQL cases are
  gated on `MAISTRO_TEST_PG_DSN` like the persistence conformance tests and
  isolate themselves from the process-global pool registry.

Failing-before evidence (head `31d891a5`, tests added first): the SQLite
cleanup case failed with `DID NOT RAISE any of (ValueError, ProgrammingError)`
(leaked connections still execute) and the owned-pool case failed with
`assert 1 == 0` where `0 = pool_count()`. Passing-after: the issue's
validation command — lifecycle + convergence + model-binding bootstrap —
26 passed, 3 skipped without PostgreSQL, and 29 passed, 0 failed with a
migrated pgvector/pg18 service (`MAISTRO_TEST_PG_DSN` set).

Salvage-round re-verification (2026-10-18, merged head `b2787cf89`, tests
re-run from scratch against the real rejection, bootstrap never mocked):

- Failing-before reproduced three ways. (1) At head `31d891a5` + the new
test file, `test_failed_startup_closes_the_sqlite_connections_it_opened`
failed with `DID NOT RAISE any of (ValueError, ProgrammingError)`. (2) At
PR #2207's head `4567dd98a` + the quota test,
`test_failed_startup_keeps_the_previous_quota_tracker_default` failed with
the failed candidate's `SqliteQuotaTracker` installed as the process default
(`assert <SqliteQuotaTracker ...> is <InMemoryQuotaTracker ...>`). (3) With
the issue's named regression re-created by hand — publication moved back
above `bootstrap_model_bindings`, the #1362 arrangement — both preservation
cases failed: the failed candidate displaced a live outer container's
default and the cached fallback.
- Passing-after at `b2787cf89`: the issue's validation command collected 31
nodes — 28 passed, 3 skipped without PostgreSQL; 31 passed, 0 failed, 0
skipped with a migrated pgvector/pg18 service
(`MAISTRO_TEST_PG_DSN=postgresql://maistro:postgres@127.0.0.1:18556/maistro`,
75 public tables) — including both PostgreSQL pool-ownership cases.
Adjacent container suites (`test_container_pool_ownership.py`,
`test_container_sqlite_backend.py`, `test_container_wiring.py`) 81 passed.
Gates re-run with CI's exact arguments: ruff check/format clean, mypy
`--strict packages/maistro-core/src` clean under `--all-extras`, suite
inventory 17/17, radon ledger 137→137, xenon 137 blocks = baseline with
module and average axes clean, vulture ledger 1322→1322, promotion surface
ok, reachability ok.
