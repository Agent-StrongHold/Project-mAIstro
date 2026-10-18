---
inventory-delta:
  packages/maistro-core/tests: +14
---
# L1856: failed Container construction keeps the live default effect context

Issue #1856 (parent #55) at branch `auto-1856`; this note's delta covers the
fourteen lifecycle tests the lane added on top of develop (eight for the effect
context and resource cleanup at head `31d891a5`, the quota-tracker default
test at head `26a4ec3c3`, and five repair-round tests for the failed-startup
cleanup helpers described at the end). Develop base now `35a72ff54d` after
the conflict-free `origin/develop` sync merge `b91f589fa`.

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

Coverage-gate repair round (2026-10-18, head `b91f589fa` + this change):
the merge-queue evaluation failed the Coverage gate's diff-coverage step —
`container.py` at 88.8% of 152 changed lines (need 90%), uncovering only
the defensive branches of the failed-startup cleanup helpers (uncovered
lines 3309–3317, 3332, 3335–3336, 3432–3443): the PostgreSQL release arm
of `_release_failed_startup_resources`, the None-skip and failing-close
arms of `_close_startup_sqlite_connections`, and `_wire_sqlite_backend`'s
own mid-wiring cleanup handler. Those branches are reachable only when a
startup fails between connects or a release/close itself fails, and the
two PostgreSQL-gated end-to-end tests skip in every CI coverage job (the
full core suite runs once, in the no-services producer), so no existing
test could cover them. Five tests now drive the helpers directly with the
registry-seeded fake-pool pattern `test_container_pool_ownership.py`
established; `create_container` itself is untouched. Sensitivity is
mutation-proven, not just green: dropping `forget_pool` reds
`..._pg_release_survives_a_failing_close_and_forgets` (a stale registry
alias survives); dropping the handler's `raise`, removing the None skip,
or letting a close failure propagate each red the matching midwiring or
closer test. Gate evidence at this head: the no-services core producer
under `coverage run --branch --source=packages/maistro-core/src/maistro`
collected 15396 passed, 1078 skipped, 3 xfailed, and
`check-diff-coverage.py coverage.xml --base 35a72ff54d4f…` reports ok
(every measured file ≥90% lines / ≥80% branch arcs; the CI combine adds
only more producers for the same `--source`, so it cannot score lower).
The issue's validation command re-run: 33 passed, 3 skipped without
PostgreSQL; 36 passed, 0 skipped against a freshly migrated
pgvector/pg18 database (`maistro_r1856b` on the same service), lifecycle
file alone 19/19 with the pool-ownership cases executing.
