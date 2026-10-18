# m1-14-develop-pr1993-root-suite-delta

## Superseded by develop's own `1993-hive-permission-preset-inventory.md`

**This note no longer carries an `inventory-delta` block.** develop has since
recorded the same node ID itself — `1993-hive-permission-preset-inventory.md`
(landed with PR #2155's merge, `1a2e1265`) grants `tests/: +1` for exactly the
same test this note described. Keeping both blocks would double-count the +1
after this branch merged develop: the gate answered
`DRIFT  tests/: expected 5505, collected 5504` on a scratch merge of
`origin/develop` into this branch's previous tip `c8fc6b80f`, off by exactly
the duplicated +1. The block is therefore withdrawn so the recorded sum
matches the collected tree; this file stays as the measurement record.

## Original finding (for the record)

Nothing stopped collecting and this lane added no root test. develop's own
head `2f56be40a` (merge of PR #1993, commit `edb669149`) added exactly one
root-suite node ID —
`tests/security/test_sentinel_permission_table_armed.py::test_hive_preset_tracks_the_executable_registry`
— without an inventory note. The diff between `f277bae57` and `2f56be40a`
touches no other file under `tests/`, keeps the
`test_permission_table_is_armed` parametrization at the same 7 profiles, and
removes nothing: net +1, unrecorded.

develop's own `test` job fails its inventory gate on this exact drift at its
own head (run 39112583663, job 117631652847:
`DRIFT  tests/: expected 5260, collected 5261`), and every branch based on it
inherits the same red — this lane's job (run 39117424847, job 117645940178)
failed identically with all 9352 tests passing. The alarm number is explained,
so per the gate's own instruction it is now recorded rather than chased.

Same shape as `k770-develop-root-suite-drift.md`: the delta is recorded at the
branch that measured it, per ADR-082526-547c — the sum absorbs whatever else
merged, so when this lands, develop's ledger reconciles against the same
collection. No test was added or removed by this note.
