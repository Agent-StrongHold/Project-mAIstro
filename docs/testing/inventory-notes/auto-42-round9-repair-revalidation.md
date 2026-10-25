---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 9: repair lane — revalidation at 2407fae17, residual skips enumerated

This repair round started at the exact assigned head
`2407fae17deeeae9b05630044bf5b577ebab86a4` with a clean tree. No
production code was changed: the sole residual identified by the round-9
verifier — GitHub issue **#1194 still OPEN** while #42's acceptance
requires "#1169, #1170 and #1194 close before this issue is considered
complete" — is an orchestrator-owned GitHub closure action this lane is
prohibited from performing. The underlying replay/idempotency contract
#1194 asks for remains implemented and test-proven (see prior rounds and
below). This round therefore (a) re-proved the gates at this head,
(b) closed the verifier's minor finding by enumerating the 3 residual
live-PG skips, and (c) recorded the live issue states.

## Live GitHub states (read-only `gh`, this round)

- **#1194 OPEN** (closedAt null) — sole unmet #42 acceptance item.
- #1169 CLOSED, #1170 CLOSED, #42 OPEN.

## Gates re-executed at 2407fae17 (all green)

- `uv run ruff check .` — "All checks passed!"; `ruff format --check .` —
  2609 files already formatted.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0; 1402 reviewed identities,
  `unclassified: 0`, `never_allowlist: 0`, ratchet vs base b43175c1d.
  No ledger amendment needed (no unbanked identities; no identity
  eliminated this round).
- `scripts/check-execution-lifecycles.py` — exit 0; 19 classified
  lifecycles -> 19 discovered (3 CANONICAL / 8 CONVERGE / 6 DOMAIN /
  2 PROJECTION).
- Lane pytest selection (a2a guests, invocation stores, durable_runs,
  graph nodes, sqlite runs store, server A2A API): **161 passed**,
  exit 0.

## Live-PG legs (scratch DB on lane container `auto-42-pg5`, dropped after)

- Scratch DB `l42_r9_scratch`; `alembic upgrade head` chained cleanly to
  the single head `044` on real PostgreSQL.
- `tests/runs` with `MAISTRO_TEST_PG_DSN`: **1200 passed, 3 skipped**,
  exit 0 — identical counts to rounds 7–9. The 3 residual skips are now
  enumerated (closes the prior round's minor finding); both are
  intentional, capability-conditioned conformance skips, not coverage
  gaps:
  - `tests/runs/test_archive_conformance.py:350` (1 skip) — "only a
    store that really moves the payload can lose it";
  - `tests/runs/test_retention_scope_conformance.py:211` (2 skips) —
    "backend exposes no separately-readable continuation store".
- `tests/graph/durable_runs` + `tests/tasks` + `tests/runtime` with
  `MAISTRO_TEST_PG_DSN`: **1006 passed, 0 skipped**, exit 0 (includes
  the ambiguous-effect replay guard, attempt executor, chat attempt
  recovery, and node-retry attempt surfaces that carry #42's
  acceptance evidence).

### Environment note for future rounds

`MAISTRO_TEST_PG_DSN` must use the plain `postgresql://` scheme: the
runs conftest hands the DSN to raw asyncpg, which rejects
`postgresql+asyncpg://` ("scheme is expected to be either
\"postgresql\" or \"postgres\"") — a wrong-scheme DSN produces hundreds
of setup errors that look like a regression but are not.

## Residual (unchanged, orchestrator-owned)

- #1194 OPEN on GitHub; no code repair exists in this lane for an issue
  state. Everything #1194 substantively required is live-proven on real
  PostgreSQL (effect_scope-keyed unique claim in
  `invocation_store.py` / `pg_invocation_store.py` / alembic `035`,
  `UnsafeEffectRetry` on ambiguous re-entry, cross-process dedup, and
  `test_ambiguous_effect_replay_guard.py` green in this round's
  durable_runs leg).
