---
inventory-delta:
  packages/hive-conductor/backend/tests: +16
---
# 1877 — projection publishes only canonical Run lifecycle truth

## What moved

`packages/hive-conductor/backend/tests`: +16 collected node IDs, all in the new
`test_dag_run_canonical_lifecycle.py`. Nothing was removed, and no existing
test was weakened.

## Why

Issue #1877: two seams published false terminal lifecycle metadata for
readable same-Workspace canonical Runs. The projection writer
(`routes/dags.py::_record_run_projection`) called `finish_run` for every
status — giving a waiting or paused Run a `finished_at` the Run model forbids
nonterminal Runs to carry — and coerced a missing status to `failed`. The read
overlay (`services/dag_run_inspection.py::_overlay`) replaced only the fields
the canonical Run happened to fill, so a stale projection `result`/`error`
survived a canonical null and a stale `finished_at` survived a nonterminal Run.

## What the new IDs cover

- The writer spy matrix: each of the five nonterminal `RunStatus` members
  (derived from the enum, not a string list) produces exactly zero
  `finish_run` calls while `start_run`/`append_event` still record the row;
  the terminal control still finishes exactly once; missing/empty/unknown/
  wrong-case statuses take the existing caught-and-logged projection-failure
  path with zero store mutations and are never coerced to `failed`.
- The read overlay matrix: a deliberately stale completed row under each
  nonterminal canonical Run reads back with canonical status, null
  `finished_at`, and canonical null `result`/`error` overwriting the stale
  values; each of the four terminal statuses converts the supplied
  timezone-aware canonical `finished_at` to exactly `datetime.timestamp()`
  (so a wall-clock value minted at read time cannot pass); canonical values
  overwrite null projection fields in the other direction too.
- Preservation: no-canonical and Workspace-mismatch `_overlay` fallbacks
  return the record verbatim (identity), and creative provenance is still
  relayed beside the replaced lifecycle block.
- One durable-store test: a valid Run transitioned nonterminal → terminal in
  a sqlite-backed canonical store, read back through a reopened store, still
  derives the exact terminal metadata through inspection. This pins store
  transition + read derivation only — it is not executor resume/recovery.

## One existing test touched, not weakened

`test_dag_run_creative_inspection.py::test_detail_of_a_non_creative_run_gains_no_creative_block`
fabricates a `_PlainRun` double. The overlay now reads `finished_at`, a field
the canonical Run model always declares, so the double declares it too. The
test's assertions (no creative block, no artifacts on a non-creative run) are
unchanged.
