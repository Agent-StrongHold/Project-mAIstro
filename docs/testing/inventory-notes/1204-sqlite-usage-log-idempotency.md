---
inventory-delta:
  packages/maistro-core/tests: +17
---
# #1204 SQLite usage-log idempotency

Four new cases in `packages/maistro-core/tests/quota/test_sqlite_usage_log.py` cover
legacy-schema identity backfill, same-timestamp event identity, forced
overlapping snapshots, and a commit that succeeds before its result is reported
as failed. Each restores the durable log and asserts exact request/token totals,
proving that retries and concurrent flushes cannot inflate quota usage. Two additional persistence cases exercise the shared quota tracker protocol: memory, SQLite, and PostgreSQL all deduplicate a repeated event identity and reject identity reuse with different usage.

## Merge resolution against trunk's serialized schema upgrades (#1461)

Trunk landed `serialized_schema_upgrade` (per-connection lock + `BEGIN
IMMEDIATE`) on top of the pre-#1204 watermark implementation, so the merge
conflicted in both `ensure_schema` methods. Resolution combines both:
`SqliteUsageLog.ensure_schema` runs the event-id column backfill and unique
identity index inside the shared discipline, nested under the instance
operation lock so the migration excludes `snapshot`/`restore` on the same
connection; `SqliteQuotaTracker.ensure_schema` creates `quota_usage` and
`quota_usage_events` inside the shared discipline. Trunk's `SqliteUsageLog`
watermark and per-scope timestamp dedup are fully replaced by the event
identity semantics this issue owns. Verified live against a pgvector:pg18
container: the legacy timestamp-only table upgrades and backfills
`legacy:<rowid>` identities, three overlapping snapshots restore exactly once
(2 requests / 25 total tokens for a 15-token backfilled row plus a 10-token
event), and a repeated `record_usage(event_id=...)` keeps `request_count=1`.

## Develop-merge resolution (60862b6c5)

Merging develop's 60862b6c5 into the lane conflicted in
`docs/architecture/CONVERGENCE-MATRIX.md` only: develop's #1470 rewrote the
Credentials row around the retired `credential_store_v2`, which this same merge
applies, so its row text was taken; but its Quota share of `most` was rejected
because `check-convergence-matrix.py` recomputes the merged tree's unreachable
quota share as `some` (7 of 14 modules) — the branch's wired quota backends are
part of that arithmetic. No quota/persistence source file conflicted: develop
did not touch the #1204 surfaces, and the migration chain re-verified as a
single linear head (`039_quota_usage_event_identity`) applying cleanly from
empty PostgreSQL.

## Retention and chain-tip repairs

Two durable-bookkeeping repairs from the validation round: `quota_usage_events`
needed an entry in `quality/durable-table-retention.json` (recorded honestly as
`undecided` against #325, which owns retention — this issue creates the ledger,
it does not decide its lifetime), and the `usage_events` entry's note no longer
claims `SqliteUsageLog` is unwired. The migration's parent also moved from
`038` to the develop chain tip `036_audit_log_org_scope` after develop's
`039`/`040` re-forked the chain; `test_audit_scope_migration`'s head pin
follows the new tip, the same reconciliation its own comment narrates for
#1531 and #1079.

## Migration chain linearization

The branch's migration previously shared trunk's renumbered 033-035 space and
sat as a second alembic head, which fails CI's `alembic upgrade head`. It is
renamed to `039_quota_usage_event_identity`; after develop's
`039_canvas_job_admission_key` and `040` merged, its parent moved again — from
`038` to the develop chain tip `036_audit_log_org_scope` — because the old
parent re-forked the chain into two heads. `tests/migrations/test_migration_chain.py`
applies the full chain to an empty PostgreSQL database, and the
downgrade/upgrade cycle recreates `quota_usage_events` — both run green
against the live server.

## Pinned-revision store suite follows its own convention

`tests/migrations/test_quota_and_session_stores.py` pins the revision the
durable stores run against; `PgQuotaTracker` now touches `quota_usage_events`,
which the old pin (023) predates. The pin moves *within* the existing suite,
so that suite's collected count does not change — hence no delta for it above. Per the suite's documented drift procedure
(the #327 move), the pin moves to `039_quota_usage_event_identity`; the
fixture's plain upgrade-from-empty already exercised the `vector`-dependent
001, so no new image coupling is introduced. All 11 cases pass against the
migrated scratch database.

## Independent verification (lane L1204, head bb42cd1a6)

Re-executed by the independent verifier against the exact head; no source files
changed. Lane paths: 95 passed / 22 skipped (matches the recorded driver run).
With `MAISTRO_TEST_PG_DSN` pointed at the lane pgvector:pg18 container: the full
`packages/maistro-core/tests/persistence/` + quota usage-log + container + RSI
selection runs 661 passed with zero skips, including
`test_retrying_one_event_does_not_double_count[memory|sqlite|postgres]` — the
PostgreSQL leg ran against a real server, not the mock. `tests/migrations`
passes 96/96 with `MAISTRO_TEST_DATABASE_URL` set (note: that suite's
`empty_database` fixture deliberately `downgrade base`s the database the URL
names — point it at a sacrificial database, and do not also export
`DATABASE_URL`, which overrides the scratch-DB `DB_*` env the qs-suite builds
and silently redirects its alembic run at the wrong database). Full
`packages/maistro-core/tests`: 10172 passed, 655 skipped, 1 xfailed.
`ruff check` / `ruff format --check`, both `check-suite-inventory` gates,
`check-durable-table-inventory`, `check-convergence-matrix`, and
`check-reachability` all pass. `alembic upgrade head` from an empty database
applies the chain to the single head `039_quota_usage_event_identity`; the four
pivotal quota tests (legacy backfill, same-timestamp identities, forced
overlapping snapshots, commit-result-lost retry) and the three-backend
conformance test were re-run by name and pass. PR body and branch commits
carry no closure keywords; PR 1462 remains a draft.

## Re-verification (lane L1204, head e2ae1c1e, job 0b8a94df)

Third-party re-check of the same code; no source files changed. Fresh
pgvector:pg18 scratch database created, `alembic upgrade head` applied the
linear chain to the single head `039_quota_usage_event_identity`, and
`\d quota_usage_events` confirmed `PRIMARY KEY (event_id)`. With
`MAISTRO_TEST_PG_DSN` pointed at it: `packages/maistro-core/tests` runs
10711 passed / 116 skipped / 1 xfailed (zero failures, PG conformance legs
live), `packages/maistro-rsi/tests/test_runner.py` 18 passed, and
`tests/migrations` 29 passed with `DATABASE_URL` exported. The four pivotal
quota tests (same-timestamp identities, forced overlapping snapshots,
commit-result-lost retry, restored-identity re-flush) and
`test_retrying_one_event_does_not_double_count[memory|sqlite|postgres]` were
re-run by name and pass. `ruff check` / `ruff format --check` clean;
`check-durable-table-inventory` (64 tables) and `check-suite-inventory`
(13 suites) pass; mypy shows only the pre-existing five `maistro_bootstrap`
import-not-found errors under `cli/` (optional `bootstrap` extra not
installed; files untouched by this branch).

## Develop-sync round (merge ca4caec7d, lane L1204, head ac37487de)

The mandated develop sync (merge origin/develop `ca4caec7d`) forked the chain
again: develop's `042_manual_fire_occurrence_identity` took
`036_audit_log_org_scope` as its parent while this branch was open, leaving
`039_quota_usage_event_identity` and `042` as two heads over the same parent —
the exact "multiple head revisions" failure resolved three times before.
Resolution follows the same convention in the opposite direction:
`039_quota_usage_event_identity` re-parents onto `042` (the develop chain
tip), restoring the single linear head; `042`'s docstring records the
reversal, and the `test_audit_scope_migration` conflict resolved to develop's
durable form (exactly one head, with the audit migration on the head's walked
path — both sides' assertions hold under the new parentage). Proven on a fresh
pgvector:pg18 database: `alembic upgrade head` applies
`040 -> 036_audit_log_org_scope -> 042 -> 039_quota_usage_event_identity` and
ends single-headed. Post-merge validation, all on that merged tree: full
`packages/maistro-core/tests` 11009 passed / 116 skipped / 1 xfailed with the
PG conformance legs live (including
`test_retrying_one_event_does_not_double_count[memory|sqlite|postgres]`),
`tests/migrations` 96 passed, `packages/maistro-rsi/tests` 779 passed, mypy
clean across 721 source files, ruff check/format clean,
`check-vulture-baseline` (exact-debt-ledger) exit 0, both inventory gates
pass.

One cross-lane residual, measured and not fixable inside this lane:
`check-ac-state --run-tests --ratchet` now measures `design_coverage` 33.607
against the folded floor 38.0924 (held jointly by the `auto-1204`, `auto-1158`
and `auto-1138` notes, two of which landed here from develop). The fall is a
corpus-composition effect of the mandated merge — develop's WIP corpus adds
taken-but-unproven ADR decisions (93 of 156 taken ADRs now score zero, e.g.
ADR-065 0/26, ADR-081226-69ee 0/13), each new zero decision diluting the
corpus mean by ~0.64 points. The mechanism's own remedy for a landed corpus
whose recorded floor no longer holds is a reviewed grant in
`quality/ratchet-authorizations.json` (owner-reviewed; reads at the base so a
commit cannot grant itself), which this lane is prohibited from writing. The
#1204 surfaces are unaffected: every quota/usage criterion of this issue
remains proven on the merged tree by the runs above.

## Diff-coverage repair round (merge of develop a71fc2e43, lane L1204)

CI at 6bccec60e failed two gates; the actual logs name three files below the
diff-coverage floor and one superseded grant. Both are addressed here:

- **Coverage gate (diff coverage)**: seven collected cases (one is
  parametrized over the three backends) close the exact measured gaps.
  `test_container_sqlite_backend.py` gains the swallowed shutdown-flush
  failure path (`_flush_usage_log_on_shutdown`'s `except` arm: a snapshot
  that raises must not block `aclose`). `test_backend_conformance.py` gains
  `test_reusing_an_event_identity_with_different_usage_is_rejected`, run
  against memory, SQLite, and PostgreSQL: identity reuse with different usage
  is rejected and the original event stays the only contribution (the
  equivalent no-double-count semantics criterion, now at conformance level —
  this also covers `InMemoryQuotaTracker`'s reuse-rejection raise, which no
  test exercised). `test_pg_quota.py` gains the three conflict-path cases the
  FakeConnection can force: RETURNING-empty retry with the same payload
  counts once, with a different payload is rejected, and with a vanished row
  is rejected (`pg_quota.py:82`'s partial branch).
- **Quality gate (acceptance-state ratchet)**: the failure was not the
  floor — CI's own log measures `design_coverage` 38.0924 over 156 taken
  decisions (92 at zero) with the PG legs live, exactly on the floor. It was
  `authorized floor(s) independent landings have superseded`: the
  `design_coverage@33.9095` grant (#729) in `quality/ratchet-authorizations.json`
  is durably overtaken by the `auto-1138`/`auto-1158`/`auto-48` notes and had
  to be pruned. Develop's #1114 lane already pruned it (the section is now
  empty at a71fc2e43), so the mandated develop sync (merge of origin/develop
  at a71fc2e43) lands that prune; no grant was written by this lane.

## CI-repair round (lane L1204, head 03b48facc)

CI at the develop-merge head failed four checks; all four are addressed with
evidence from this round (PG via a dedicated pgvector:pg18 container, port
18499):

- **exact-debt-ledger**: the #1204 wiring (`container.py`'s
  `usage_log_persistence.restore()` call) made the name `restore` referenced
  tree-wide, so vulture dropped five identities — `SqliteUsageLog.restore`
  plus the four RSI `restore` methods (`local_loop`, `protocols`,
  `sandbox/local`, `sandbox/microvm`). The five were pruned from
  `quality/vulture-baseline.json` (1410 = 1410);
  `check-vulture-baseline.py` exits 0.
- **Quality gate / radon**: the shutdown-flush block this issue added to
  `Container.aclose` pushed it to C(11) vs the trusted base's B. Extracted
  into `_flush_usage_log_on_shutdown()`; `check-radon-baseline.py` 69 = 69,
  xenon 69 <= 77, mypy --strict clean (with the `bootstrap` extra installed),
  pyright 21 = baseline 21, and every other runnable quality-gate step passes.
- **Quality gate / acceptance-state ratchet**: the lane's added tests raised
  design coverage to 38.0924 vs the trusted floor 33.9095 — an unbanked
  improvement, which this strict ratchet treats as a failure. Banked to
  `quality/ac-state-notes/auto-1204.json` (per-branch note, #585);
  `check-ac-state.py --run-tests --ratchet` exits 0.
- **Quality gate / reachability dispositions**: `quota-verification` still
  dispositioned `maistro.quota.sqlite_usage_log` as unreachable (CONNECT);
  the checker itself reports it became reachable and demands the prune —
  done; `check-reachability-dispositions.py` passes.

Re-verification on this tree: persistence suite 629 passed with
`MAISTRO_TEST_PG_DSN` live (includes
`test_retrying_one_event_does_not_double_count[memory|sqlite|postgres]`,
3 passed re-run by name); the four pivotal usage-log tests plus the container
flush/restore lifecycle pass; migration-chain, pinned-store, audit-scope and
pg-wiring suites 44 passed against a sacrificial database;
`packages/maistro-core/tests` 10227 passed / 674 skipped / 1 xfailed
(no PG exported — same shape as CI's `test` job); RSI + evolve 1366 passed;
formal/ 421 passed; suite inventory 13/13; ruff check and format clean.
