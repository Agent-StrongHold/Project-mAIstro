---
inventory-delta:
  packages/maistro-core/tests: +36
---

# P1b Attempt cancellation-cause codec (#1885)

Base: `a586560170a9ce4d72ee7d750100d0178c1f69d0` (branch `auto-1885`, identical
to the develop base). Final leaf SHA: this commit.

Production inputs verified byte-identical to the pinned audit:
`runs/evidence_json.py` blob `5a069112a0a1ffcf33888a912f21e88465f0f1c8`,
`graph/durable_runs/types.py` blob `943271b4beec5961ce0ee0b7e823102c7baeb3c9`,
`runs/model.py` blob `0de6b8ed9dedc87d590b39019cb0b0431e6259a2` (the audited
pre-P1a model, confirmed against the P1a note).

## Dependency state (read this before interpreting results)

This leaf is DEPENDENCY_BLOCKED on #1884 (P1a optional
`Attempt.cancellation_cause` + null-dropping wrap serializer). The pinned base
does not contain P1a: `Attempt.model_fields` has no `cancellation_cause`, and
`packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py`
does not exist here. P1a's tested branch was located locally and verified:
`origin/feat/1884-attempt-cancellation-cause-model` @
`3ed42ca6c7f731988bcf5d95a4424b07a6f8d1d1`, where its own 58 model cases pass.

The file is written against P1a's exact tested shape and degrades honestly on
the pre-P1a base: case rows that cannot exist without the field carry
`pytest.mark.skipif(not _HAS_P1A, ...)` (`_HAS_P1A = "cancellation_cause" in
Attempt.model_fields`) with the reason "P1a (#1884) optional
Attempt.cancellation_cause is absent from this checkout". Once P1a merges, all
skipped rows activate with zero edits.

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

- Pinned base (this branch): 36 collected, **15 passed, 21 skipped** (the
  P1a-gated rows), `pytest -q -ra`.
- P1a branch `3ed42ca6c` (isolated scratch worktree, this file copied in
  unmodified): **36 passed, 0 skipped**. The same run there shows P1a's own
  `test_attempt_cancellation_cause_model.py`: 58 passed.

## Mutation evidence (each mutation applied, run, then restored byte-identical)

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
