# Repair notes — L1837 — stale residual inventory note invalidated by develop sync (head 708bc2c62)

## Symptom

CI `test` gate fails at `ci.yml` ("Suite inventory matches collected node IDs
(C1/#286)"):

```
DRIFT  tests/: expected 5897, collected 5896
FAIL: 1 suite(s) drifted from the recorded inventory (net -1 node IDs).
```

Reproduced locally on head 708bc2c623cca2ced23b7385ccbf34a3c60440a9 with
`uv run python scripts/check-suite-inventory.py`.

## Root cause

The branch-local note `docs/testing/inventory-notes/auto-1837-5646.md`
(added in a5840d787) recorded a residual `tests/: +1`, with the prose premise
that `ops-folded-notes-evidence-2336.md` "is deleted" and only one of its three
tests still collects.

The develop sync merge 708bc2c62 (merge of 833a98a91, PR #2336) re-added
`ops-folded-notes-evidence-2336.md` (`tests/: +3`) **and** all three tests it
describes, so the note's premise is no longer true on this tree:

- `test_folded_notes_baseline_is_evidence_not_policy` — `tests/test_autonomous_merge_policy_inputs.py`
- `test_folded_notes_evidence_is_yellow_eligible` — `tests/test_autonomous_merge_quality_classes.py`
- `test_blast_radius_yellow_stays_ineligible` — `tests/test_autonomous_merge_quality_classes.py`

All three collect, and the ops note's `+3` is counted again. The residual `+1`
therefore double-counts one of those tests: expected = 4117 + 1780 = 5897 vs
collected 5896.

## Fix

Delete the stale branch-local note `docs/testing/inventory-notes/auto-1837-5646.md`.
Its content is preserved in git history at a5840d787. The ledger then records
exactly the ops note's `+3` for the three tests that actually collect.

No shared line is touched: `baseline.json` is unchanged, `folded` is unchanged.

## Verification (executed on this tree)

- `uv run python scripts/check-suite-inventory.py` → all suites ok, 0 drift
  (was FAIL with `DRIFT tests/: expected 5897, collected 5896`).
- `uv run pytest tests/test_autonomous_merge_quality_classes.py
  tests/test_autonomous_merge_policy_inputs.py -q` → the three ops-note tests
  collect and pass.
- `uv run python scripts/check-adr-status-language.py && git diff --check` →
  pass (the issue's own deterministic hygiene command).
- `uv run ruff check .` / `uv run ruff format --check .` → pass.

## Still open (human gate, unchanged)

ADR-101826-c3f1 remains `status: Proposed`. Issue #1837 requires explicit
acceptance by the ADR owner (@BlakeMatthews-dev or a designated
architecture/security reviewer); per the issue text this cannot be granted by
any command or worker. The decision stays visibly open.
