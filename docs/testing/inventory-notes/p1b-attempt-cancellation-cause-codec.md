---
inventory-delta:
  packages/maistro-core/tests: +36
---

# P1b Attempt cancellation-cause codec (#1885)

inventory-delta basis: `packages/maistro-core/tests` +36 collected node IDs,
true at the original branch base and unchanged by the sync below (the sync
moves no collected count).

Lineage (all SHAs verified with `git merge-base`/`git show`):
- Original branch base `a586560170a9ce4d72ee7d750100d0178c1f69d0`: the leaf
  commit was authored here (pre-P1a; no `cancellation_cause` in
  `Attempt.model_fields`).
- Assigned develop base `ab8b3737fa64f8d840f421ef87ca506c509444ff`: P1a
  (#1884) is present — landed via #1928, commit `91996e192` — so the
  dependency block below is resolved at the base this leaf is judged on.
- Final head: merge `44f16b483` joining the leaf commit `ec986e182` with the
  assigned base (conflict-free; the leaf adds two new files only). Final leaf
  content = the two files in `ec986e182`, byte-identical.

Production inputs verified byte-identical to the pinned audit at the original
base: `runs/evidence_json.py` blob `5a069112a0a1ffcf33888a912f21e88465f0f1c8`,
`graph/durable_runs/types.py` blob `943271b4beec5961ce0ee0b7e823102c7baeb3c9`,
`runs/model.py` blob `0de6b8ed9dedc87d590b39019cb0b0431e6259a2`. The sync
brings P1a's audited model/serializer changes to `runs/model.py` from develop;
the leaf itself still touches no production file.

## Dependency state (read this before interpreting results)

This leaf was DEPENDENCY_BLOCKED on #1884 (P1a optional
`Attempt.cancellation_cause` + null-dropping wrap serializer). That dependency
is now **resolved**: P1a is merged into the assigned develop base via #1928
(`91996e192`), `Attempt.model_fields` has `cancellation_cause`, and
`packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py`
is present. Historical pre-merge evidence: P1a's tested branch
`origin/feat/1884-attempt-cancellation-cause-model` @
`3ed42ca6c7f731988bcf5d95a4424b07a6f8d1d1`, where this file first ran 36/36.

The file still degrades honestly on any checkout that predates P1a: case rows
that cannot exist without the field carry
`pytest.mark.skipif(not _HAS_P1A, ...)` (`_HAS_P1A = "cancellation_cause" in
Attempt.model_fields`) with the reason "P1a (#1884) optional
Attempt.cancellation_cause is absent from this checkout". At the synced head
all 36 rows run live.

## What the 36 collected cases prove

`test_attempt_cancellation_cause_codec.py`, oracle nodes:
`test_cause_round_trips_through_canonical_evidence_json` (21 rows: causes
unknown/requested/recovered × transports payload-dict/str/bytes/bytearray/
decoded-dict/json-of-text/json-of-bytes), `test_unknown_cause_is_omitted_
without_dropping_other_none` (2), `test_nested_durable_record_preserves_
cause_and_lineage` (3), `test_cause_round_trip_preserves_nonfinite_physical_
evidence` (3), `test_codec_transport_shapes_preserve_identical_attempt` (3),
`test_invalid_cause_and_extra_fields_still_fail_after_decode` (4).

Assertions compare the wire exactly against a hand-frozen legacy baseline
(independently written dict + JSON text from blob `0de6b8ed9`, never generated
by the serializer), assert the unknown cause emits no key at root and nested
Attempt positions while every other explicit null and the empty metrics
mapping survive, round-trip a DurableRunRecord with true Run/NodeRun/Attempt
linkage, tag NaN/+Infinity/-Infinity in results/metrics and restore them
semantically via `evidence_values_equal` (not NaN == NaN), hydrate identical
Attempts from dict/str/bytes/bytearray inputs, and keep unknown values, wrong
types, non-CANCELLED typed causes and extra fields rejected after decode.

## Observed runs

- Pre-sync branch base `a58656017`: 36 collected, **15 passed, 21 skipped**
  (the P1a-gated rows), `uv run --frozen pytest ... -q -ra`. Reproduced
  independently this round before syncing.
- P1a branch `3ed42ca6c` (isolated scratch worktree, this file copied in
  unmodified): **36 passed, 0 skipped** (historical, pre-merge).
- Synced head `44f16b483` (leaf + assigned develop base, all rows live):
  **36 passed, 0 skipped**, and P1a's own
  `test_attempt_cancellation_cause_model.py`: **34 passed** — the issue's
  exact commands, `--frozen`, this round.
- `uv run --frozen ruff check` / `ruff format --check` on the leaf file: pass;
  repo-wide `ruff check .` and `ruff format --check .`: pass.
- `uv run --frozen python scripts/check-suite-inventory.py` after
  `uv sync --locked --extra dev --extra bootstrap` (CI's extras): ok, 17
  suites match, `packages/maistro-core/tests: 16396` = develop 16360 + this
  leaf's 36. (Without the bootstrap extra the two extension suites fail to
  collect — an environment gap, not drift; CI installs them.)

## Mutation evidence (each mutation applied, run, then restored byte-identical)

Independently re-verified this round at the synced head `44f16b483` (all 36
rows live; originals saved, restored by byte-copy, `git diff` clean after
each):

- wrap serializer pops the cause key unconditionally (`runs/model.py`
  `_serialize_attempt_without_unknown_cause`): **20 failed** — exactly the
  typed-cause rows across every node and transport.
- `encode_evidence` returns `None` for non-finite floats (`runs/evidence_json.py`):
  **3 failed** — exactly `test_cause_round_trip_preserves_nonfinite_physical_evidence[*]`.
- `Attempt` `extra="forbid"` → `extra="ignore"`: **1 failed** — exactly
  `test_invalid_cause_and_extra_fields_still_fail_after_decode[unexpected-extra-field]`.

Historical record from the authoring round:

On the P1a branch (all 36 rows live): serializer pops an unknown cause
unconditionally → 20 failed (exactly the typed rows); serializer registration
removed (child serializer bypassed, unknown emits null) → 10 failed (root and
nested unknown rows); wrap serializer applies global `exclude_none` →
32 failed (all payload-exact rows, node 6 untouched); `encode_evidence`
converts non-finite evidence to null → 3 failed (exactly the non-finite node);
Attempt `extra="forbid"` → `"ignore"` → 1 failed (unexpected-extra-field; the
other four rejections are semantic enum/type/lifecycle errors, correctly
unaffected).

On the pinned base (15 live rows): encoder passthrough → 1 failed
(`..._nonfinite_physical_evidence[unknown]`); `extra="ignore"` → 4 failed
(all four rejection rows). Production files were restored and verified with
`git status`/`git diff` after every mutation; the final diff adds the test
file and this note only.

## Scope

Test-only leaf: no production code, store, adapter, migration, lifecycle,
writer seam or producer-default change. Typed REQUESTED/RECOVERED fixtures are
model/codec inputs only and authorize no writer. PG/SQLite JSONB round trips,
archive cold hydration and SQLite reopen remain separate persistence units in
#232/#1151. Old-reader `extra=forbid` incompatibility with non-null causes
remains until the separately reviewed cutover.
