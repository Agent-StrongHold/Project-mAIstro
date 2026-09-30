---
inventory-delta:
  packages/maistro-core/tests: +54
---
# 82-backlog-work-source

Epic M3-C (#82) starts its DB-backed Workspace BacklogItem service (#98, with
the model-level parts of #100 claims/leases and #101 history) as a new
`maistro.backlog` package in maistro-core. The +54 node IDs are two new files
in `packages/maistro-core/tests/backlog/`, and the split matters:

- **9 model nodes** (`test_backlog_model.py`): pure pydantic invariants —
  closure evidence required exactly at terminal status, non-blank identity
  fields, naive datetimes normalized to UTC, self-parenting refused,
  optimistic-concurrency version floor.
- **45 conformance nodes** (`test_backlog_store_conformance.py`): one body per
  behavior, parametrized over the `memory`/`sqlite`/`postgres` backends so all
  three store implementations are held to the same contract (the
  `PgStrikeTracker` lesson, #134). The durable-SQLite leg reads through a
  second connection the writer never used, so durability is observed, not
  asserted. The PostgreSQL leg skips without `MAISTRO_TEST_PG_DSN` (16 of the
  45 here) and runs in CI against a migrated Postgres, where alembic `048`
  owns the schema; setting `MAISTRO_REQUIRE_PG_LEGS=1` turns a silent skip
  into an error.

The conformance bodies cover what the epic's first slice promises: workspace
isolation, version-conflict refusal (never merge), UNSET-vs-None clearing
semantics, terminal-status unreachability through ordinary edits, closure
evidence requirements, close/reopen event cycles, decomposition guards,
list filters, and the atomic claim/lease lifecycle including concurrent-claim
admission of exactly one winner.

Until #102 performs the authority cutover, root `BACKLOG.md` stays canonical;
these tests pin the structured service that cutover will migrate into, not a
replacement authority.

## CI-repair addendum (merge-queue round at a483af0e0)

Two merge-queue gates were red at this head. Test node counts are unchanged by
this repair; no test was added or removed.

- **Supply chain (pip-audit):** urllib3 2.7.0 carried CVE-2026-97687/88/89
  (fixed upstream in 2.8.0). Lockfile-only bump via `uv lock --upgrade-package
  urllib3`; the backlog slice introduced no dependency. Gate re-executed
  locally: `pip_audit_gate.py` exit 0 (ecdsa PYSEC-2026-1325 remains the
  pre-triaged ALLOWED set; direct-dependency usage ledger unchanged).
- **exact-debt-ledger:** the new package tripped four ratchets at once.
  - *Dead code fixed:* `_require_fresh_version_removed` in sqlite_store.py was
    a never-called stub (`# pragma: no cover - never called`) — deleted, no
    behavior change, conformance suite green.
  - *Enumeration gap eliminated by declaration:* `maistro.backlog` joined
    CORE_PUBLIC_SURFACE in scripts/verify-wheel-imports.py (the #94 canvas
    pattern): the module is intended public core API, imports cleanly on the
    bare tier (the package `__init__` pulls only model + in-memory store), and
    the core_surface gap disappears instead of being banked as tolerated.
  - *Retained identities banked:* 52 vulture findings (41 unique stable
    identities — store.py's protocol declarations and in-memory methods share
    names, as do two same-named validators) banked in
    quality/vulture-baseline.json via `--update`; the 5 unreachable modules
    banked in quality/reachability-baseline.json with a CONNECT disposition
    group in quality/reachability-dispositions.json naming the #99 server
    wiring as the root.
  - *Authorizations staged:* the vulture (41) and reachability (5) grants are
    written into quality/ratchet-authorizations.json with owner/issue/reason.
    load_authorizations() reads grants from the trusted BASE revision by
    design (#534; the #1683 radon precedent), so a candidate branch cannot
    authorize its own debt: these gates stay red on exactly the
    "not previously authorized" half until the grants land on develop in a
    grants-only merge FIRST, after which this branch re-enters the queue with
    every half green. All candidate-side bookkeeping is provably complete
    in-branch: `--update` idempotent, enumerations/shipped-surface/
    dispositions-shape/lifecycle green, and the only remaining gate messages
    name the missing base grants.
