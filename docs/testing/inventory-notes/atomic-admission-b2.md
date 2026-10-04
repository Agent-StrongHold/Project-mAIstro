---
inventory-delta:
  packages/maistro-core/tests: +66
---
# atomic-admission-b2

## What moved

B2 of the #1845 admission-decode stack (#1893): the new
`maistro.tasks.admission_codec` module turns forward-schema admission rows
into exact #1851 immutable DTOs or typed fail-closed errors, and the new
`packages/maistro-core/tests/tasks/test_admission_codec.py` pins that
contract with 66 tests. All 66 are pure unit tests over `Mapping` rows — no
database, no clock, no HTTP — because the forward schema itself is B1
(#1892), which is not on this branch yet.

## Base provenance

The assigned lane head was bare develop (`680329c96`). The #1893 prerequisite
(#1851 typed vocabulary) lives on `origin/auto-1851`, so the work is staged
as: merge `origin/auto-1851` (clean, additive ledger rows only — verified
against `origin/develop` by row diff), then the codec leaf on top.

## Why unit-level only

The issue gates database round-trip tests on B1: "The forward schema leaf
#1892 (B1) is required for database round-trip tests; pure codec work may be
prepared earlier." The prospective
`test_raw_and_production_pool_codecs_read_identical_text_snapshots` is
therefore pinned at the value level here (snapshots are TEXT str in both
pool kinds; a pre-decoded value is rejected, never silently accepted), and
the real raw-asyncpg vs `_register_json_codecs` two-pool contrast against
the migrated schema lands with B1. No skipped test is counted as durability
proof — there are no skips in this file.

## Contracts worth remembering

- Header decode is scalar-only and deliberately skips cross-field timestamp
  ordering, so C can order valid header → inclusive expiry → fingerprint →
  full decode; header evidence survives every full-decode failure.
- Unknown `format_version` (including `True`/`1.0`, which `==` would equate
  to 1) fails `unsupported_format` and can never reach a legacy record;
  `decode_admission_record` re-derives the header structurally, so a loose
  `==` can never launder a non-scalar column into a supported format.
- Legacy binding: both ids + receipt identity is bound; neither + no receipt
  evidence is unbound; one-sided pairs, receipt-only rows, unreadable
  evidence, and bound-pairs-without-receipt are all `partial_legacy_binding`
  — a receipt is never fabricated to make a row fit.
- The v2 mapping always emits `task_id` as NULL: the #1851 DTO is
  task-agnostic by design, and the binding statement owns that bookkeeping.
  `test_v2_round_trip_preserves_all_snapshot_bytes` pins the resulting
  encode→decode→encode identity.
- Error messages never quote snapshot bytes or owner tokens, and parsing
  chains are suppressed (`__suppress_context__` asserted).

## Reachability expectation (integration head)

`maistro.tasks.admission_codec` is production code with no runtime consumer
until the C leaf lands, and this leaf deliberately makes **no**
baseline/grant/gate edits: at the integration head the reachability gate is
expected to report the new module (and to require pruning
`maistro.runs.admission_identity`, which this codec genuinely imports). That
reconciliation belongs to the integration/disposition round per the issue's
common-acceptance text, not to this leaf.
