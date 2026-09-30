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

## CI-repair re-verification (round at 5e0233199)

Independent re-execution of every gate at this head; no test added, removed,
or changed (node counts and the `inventory-delta` block above are unchanged).

- **Supply chain, fresh advisory DB:** `uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json` → `pip_audit_gate.py` exit 0. The DB now
  reports 2 advisories in 1 package (ecdsa PYSEC-2026-1325, pre-triaged in
  ALLOWED); urllib3 pins 2.8.0 with no finding.
- **Genuinely-dead re-audit:** every remaining vulture identity was checked
  for a real fix instead of banking. The `model.py` identities are
  `@field_validator`/`@model_validator` handlers (pydantic dispatches them at
  runtime; the conformance suite exercises them) or declared pydantic fields;
  the store identities are the protocol surface parametrized over by
  `test_backlog_store_conformance.py`. Nothing further to delete.
- **Ledger/grant exactness:** a fresh vulture scan produces 52 new findings
  over the trusted base = exactly 41 unique stable identities; the candidate
  `vulture-baseline.json` re-written by `--update` diffs empty (idempotent);
  the 41 staged vulture grants match the scan identity set with 0 missing and
  0 extra.
- **Provenance failure-mode census:** `check-vulture-baseline.py`,
  `check-reachability-provenance.py`, `check-reachability-dispositions-provenance.py`,
  and `check-ratchet-provenance.py` each exit 1 at this head solely on the
  "NEW ... not previously authorized" half for the five `maistro.backlog`
  modules / 41 vulture identities. GitHub `develop` is still `c5e070d97`
  (verified via `git ls-remote`), so the grants remain unlanded; per the
  deliberate two-merge design (`load_authorizations` reads the base revision,
  #534) no candidate-side change can clear this half. Driver steps: land the
  staged grants from this branch's `quality/ratchet-authorizations.json`
  (+41 vulture, +5 reachability) onto develop in a grants-only merge, then
  re-queue — every candidate-side half is green at this head
  (ruff/format, backlog suite 38 passed/16 skipped, mypy 732 files clean,
  suite inventory, durable-table inventory, enumerations,
  shipped-surface-truth, worktree reachability + dispositions).

## Develop sync re-verification (round at 54830db28)

The merge-queue target advanced: `origin/develop` moved from `c5e070d97` to
`742e4e8fd` (five WIP epic merges: bounded schedule catch-up #92, release-path
epic, product-gap dispositions, truthfulness sweep). `origin/develop` was
merged into `auto-82` with **zero conflicts** — the two sides had independently
made the identical urllib3 2.7.0→2.8.0 lock bump, and develop touched no
`quality/` file. No test was added, removed, or changed by this branch in this
round; node counts and the `inventory-delta` block above are unchanged.

- **Merged tree healthy:** ruff check + format green; backlog suite 38
  passed/16 skipped (unchanged); develop's new scheduling suite
  272 passed/36 skipped; suite inventory ok (11647 node IDs, develop's own
  +22 recorded by develop); durable-table inventory ok (74 tables, including
  alembic `048`'s backlog tables); mypy 732 files clean.
- **Supply chain (pip-audit), fresh advisory DB:** the exact CI `security`
  job sequence re-executed (`uv pip freeze --exclude-editable` →
  `pip-audit --strict --format=json -r` → `pip_audit_gate.py`): exit 0.
  urllib3 pins 2.8.0 with zero advisories; ecdsa PYSEC-2026-1325 remains the
  only finding, pre-triaged in ALLOWED; direct-dependency usage ledger ok.
- **exact-debt-ledger at the merged head:** fresh vulture scan gives
  1402 (trusted base 742e4e8fd) → 1454 findings — develop's ~2500 new
  scheduling/release lines contribute **zero** new unbanked debt; the 52-find
  delta is exactly the known 41 backlog identities. Grant exactness re-proven:
  41 scan identities vs 41 staged vulture grants, 0 missing, 0 extra; the 5
  `maistro.backlog` reachability grants are staged. `--update` idempotent
  (ledger diffs empty); candidate bookkeeping silent.
- **Remaining red is unchanged and driver-side:** `check-ratchet-provenance.py`,
  `check-reachability-provenance.py`, `check-reachability-dispositions-provenance.py`,
  and `check-vulture-baseline.py` each exit 1 solely on the
  "NEW … not previously authorized" half for the five `maistro.backlog`
  modules / 41 vulture identities. `git ls-remote` confirms `origin/develop`
  is still `742e4e8fd` without the grants; per the deliberate two-merge design
  (#534, `load_authorizations` reads the trusted base revision) no
  candidate-side change can clear this half. Driver step unchanged: land the
  staged grants from this branch's `quality/ratchet-authorizations.json` onto
  develop in a grants-only merge, then re-queue.
