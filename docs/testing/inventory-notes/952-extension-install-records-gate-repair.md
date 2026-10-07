---
inventory-delta:
  packages/maistro-core/tests: +3
---

# 952-extension-install-records-gate-repair

CI-repair round for PR #1988 (issue #952). The first merge-queue evaluation
failed four gates on content that the deterministic verify pass had already
proven green, because three of the failures were cross-gate invariants the
fast path does not run. This round fixes those invariants; the +3 tests are
the part of the repair that closes a real coverage gap the diff-coverage gate
reproduced locally.

**+3 `packages/maistro-core/tests/extensions/test_install_records.py`** —
each pins a fail-closed or round-trip behavior the first pass left untested,
and each was written against a line/branch the diff-coverage audit named:

- `test_signature_verification_refuses_a_manifest_that_digests_elsewhere` —
  the manifest-digest precondition of `verify_package_signature`
  (verify.py:71-72). The store-level manifest-tampering test reaches the
  signature refusal instead; this pins the earlier refusal, before any key
  material is touched.
- `test_signature_verification_refuses_malformed_key_or_signature_material` —
  the `except ValueError` hex/material refusal (verify.py:79-80), for both the
  signature and the pinned-key argument.
- `test_naive_timestamps_in_durable_payloads_are_read_as_utc` — the naive
  arc of `_datetime_value` (types.py:216): a durable payload carrying a
  naive ISO-8601 timestamp reads back timezone-aware UTC and equal to the
  aware original, as `record_from_json`'s docstring promises. All fixtures
  use aware datetimes, so this documented behavior had no test.

The `build()` fall-through arc in `record_from_json` (types.py:253) stays
untaken: all three call sites pass exactly the three dataclasses the
if/elif names, so the arc is unreachable by construction. The gate is a
floor, not a demand for 100%.

Non-test repair in the same round (no count movement): `maistro.extensions`
registered on `CORE_PUBLIC_SURFACE` (enumeration ratchet), the new modules
attributed to the existing `Skills, code registry, repertoire` matrix row —
module cell and recomputed `most`→`some` share kept, row title unchanged, so
the M1 convergence freeze sees no new subsystem and needs no exception label —
the fixture parameter `key` → `signer` (gitleaks generic-api-key false
positive, same remedy as `tests/code_registry/test_registry.py`), and the
CLAUDE.md subsystem row the surface list contract says to keep in sync.

Validation on this head: the two tests named for verify.py lines and the
naive-UTC test each fail against a mutated guard (raise muted / replace
applied) and pass restored; full diff-coverage audit
(`check-diff-coverage.py` against the maistro-core + scripts producers)
reports every measured changed file at or above 90% lines / 80% branch arcs.
