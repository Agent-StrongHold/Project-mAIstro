---
inventory-delta:
  packages/maistro-core/tests: +4
---
# fix-m1-schedule-duplicate-winner-linkage-v2-6c6d

Four new tests closing the diff-coverage gate the earlier commit on this PR
opened by adding `RunStore.get_runs_for_occurrences` (the batched, Codex-flagged
performance fix for schedule recovery's serial per-occurrence claim lookups)
and the `_MAX_RECOVERED_OCCURRENCES` truncation branch it leans on:

- `test_get_runs_for_occurrences_is_the_batched_twin_of_the_single_lookup`
  (`packages/maistro-core/tests/runs/test_spine_conformance.py`, parametrized
  over the `spine` fixture's three backends — `+3` node IDs) — creates three
  Runs claiming distinct occurrences of the same schedule, resolves a mixed
  batch of matching and non-matching `scheduled_for` values in one call, and
  asserts the returned dict is keyed by `scheduled_for` and contains only the
  matches, then asserts an empty request short-circuits to `{}` rather than
  querying. Same shape `get_run_for_occurrence`'s own conformance test already
  uses, one call instead of one lookup per occurrence. The memory and SQLite
  legs run locally; the PostgreSQL leg (exercising `PgRunStore`'s
  `= ANY($2::text[])` query and `_hydrate` row-building) only runs where
  `MAISTRO_TEST_PG_DSN` is set, same as every other test behind this fixture —
  no local PostgreSQL was available to confirm it directly, so that leg's
  correctness rests on mirroring the already-passing `SqliteRunStore` shape
  and on `coverage (PostgreSQL)`/`postgres (pg17|pg18)` in CI, which run
  `packages/maistro-core/tests/runs` against a real server.

- `test_advance_truncates_recovered_occurrences_past_the_cap`
  (`packages/maistro-core/tests/scheduling/test_store.py`, a plain function —
  `+1` node ID) — calls `scheduling.store._advance` directly against a
  `Schedule` already carrying `_MAX_RECOVERED_OCCURRENCES` (1024) recovered
  occurrences, credits one more, and asserts the ledger stays at 1024 entries
  with the single oldest one dropped and the newly-credited (newest) one kept
  — the truncation branch that keeps a schedule stuck in repeated crash
  recovery from growing `recovered_occurrences` without bound.

No existing test's behavior changed.
