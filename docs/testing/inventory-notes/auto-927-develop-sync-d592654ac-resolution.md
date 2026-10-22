---
inventory-delta:
  packages/maistro-rsi/tests: +0
---
# auto-927-develop-sync-d592654ac-resolution

Repair round for #927 ([RESEARCH M8-D3] observation-driven replanning after
failures, surprises, and changed constraints): resolved the preserved
develop-sync conflict against origin/develop `d592654ac` and re-validated; no
tests added or removed.

## Conflict resolved

`docs/research/README.md`, "Research note index" table — both sides appended
rows at the same position (after `923 — episodic-to-semantic consolidation`):

- this branch (5c7d6f02e): row for `927 — observation-driven replanning`
  (M8-D3 leaf, WATCH);
- origin/develop (d592654ac): row for `926 — automatic canonical Graph
  synthesis from Goals` (M8-D2, WATCH).

Resolution keeps both rows in the table's numeric order (926, 927); both
notes exist in-tree and both dispositions are current at this head. The
paragraph below the table ("five are INCUBATE … graph-pattern reuse leaf
#929") remains correct: #926, #927, and #934 (the other develop-side row) are
all WATCH and add no INCUBATE. Committed as merge ae0a1d817 (parents
5c7d6f02e, d592654ac).

## Ledger integrity through the merge

`git diff --numstat origin/develop -- quality/` is empty at the merged head:
every `quality/*.json` is byte-identical to origin/develop, so no per-identity
ledger lost rows.

## Re-validation at the merged head (ae0a1d817)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3233 files
  already formatted.
- `uv run pytest
  packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py -q`
  → 57 passed (the #927 harness; matches the recorded +57 delta).
- Full `uv run pytest packages/maistro-rsi/tests -q` → 1584 passed, 4 skipped
  (absorbs the develop-side test additions).
- `uv run python scripts/check-suite-inventory.py` → all 17 suites match the
  recorded inventory (30701 unique node IDs; baseline + deltas absorbs both
  sides' test additions).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact arguments) →
  1323 reviewed identities → 1323 findings, 0 unbanked; exit 0.
- `uv run python scripts/check-ratchet-provenance.py` → 0 lifecycle
  violations; `uv run python scripts/check-workflow-inventory.py` → clean
  (28 workflows); `uv run python scripts/check-doc-links.py` → 0 broken
  relative links; `uv run python scripts/check-citation-status.py` → OK.
- Meaningfulness spot-check (this round, re-executed): mutating the harness
  oscillation guard (`consecutive_oscillations >= max_...` → `if False and
  …`) fails exactly
  `TestOscillationAndBudgets::test_hot_world_is_stopped_loudly_by_the_oscillation_guard`;
  reverted byte-identically (`git status` clean), module back to 57 passed.

The #927 leaf delta vs origin/develop remains the research note
(`docs/research/927-observation-driven-replanning.md`, WATCH disposition), the
README index row, the inventory note, and the harness module
(`packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py`) —
no production file under `packages/*/src` is touched by the leaf.
