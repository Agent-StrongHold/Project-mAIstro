---
inventory-delta:
  packages/maistro-core/tests: +8
---
# L1856: failed Container construction keeps the live default effect context

Issue #1856 (parent #55) at branch `auto-1856`, head `31d891a561dffd6db1312ea4a85c4835c8048440`
plus the fix commit on top; develop base `ce2048cd2430bf99a5896b229fd1999976dc07dd`.

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
