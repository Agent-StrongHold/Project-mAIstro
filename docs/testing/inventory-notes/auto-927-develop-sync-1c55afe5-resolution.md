---
inventory-delta:
  packages/maistro-rsi/tests: +0
---
# auto-927-develop-sync-1c55afe5-resolution

Repair round for #927 ([RESEARCH M8-D3] observation-driven replanning after
failures, surprises, and changed constraints): resolved the preserved
develop-sync conflict and re-validated; no tests added or removed.

## Conflict resolved

`docs/research/README.md`, "Research note index" table — both sides appended
rows at the same position (after `922 — adaptive context budgeting`):

- this branch (837658c53): row for `927 — observation-driven replanning`
  (M8-D3 leaf, WATCH);
- origin/develop (1c55afe51): rows for `923 — episodic-to-semantic
  consolidation` (M8-C4, WATCH), `929 — Graph pattern induction and reuse`
  (M8-D5, INCUBATE), and `930 — self-consistency, semantic entropy,
  answer-variation signals` (M8-E1, WATCH).

Resolution keeps all four rows in the table's numeric order (923, 927, 929,
930) — all four notes exist in-tree and all dispositions are current at this
head. The paragraph below the table ("four are INCUBATE … graph-pattern reuse
leaf #929") taken from develop remains correct: #927 is WATCH and adds no
INCUBATE. Committed as merge 2012e11ed (parents fb31e0e08, 1c55afe51).

## Ledger integrity through the merge

`git diff --numstat origin/develop -- quality/` is empty at the merged head:
every `quality/*.json` is byte-identical to origin/develop, so no per-identity
ledger lost rows. Row-count spot checks agree (vulture-baseline 15=15 identity
rows, workflow-inventory 28=28).

## Re-validation at the merged head (2012e11ed)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3221 files
  already formatted.
- `uv run pytest
  packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py -q`
  → 57 passed (the #927 harness; matches the recorded +57 delta).
- Full `uv run pytest packages/maistro-rsi/tests -q` → 1550 passed, 4 skipped.
- `uv run python scripts/check-suite-inventory.py` → all 17 suites match the
  recorded inventory (baseline + deltas absorbs both sides' test additions;
  maistro-rsi collects 1554).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact arguments) →
  1323 reviewed identities → 1323 findings, 0 unbanked; exit 0.
- `uv run python scripts/check-doc-links.py` → 0 broken relative links;
  `uv run python scripts/check-citation-status.py` → OK.
- Meaningfulness spot-check: disabling the oscillation guard
  (`max_consecutive_oscillations` GiveUp branch) in the harness module fails
  exactly `TestOscillationAndBudgets::test_hot_world_is_stopped_loudly_by_the_oscillation_guard`;
  restored byte-identically, module back to 57 passed.

The #927 leaf delta vs origin/develop remains the research note
(`docs/research/927-observation-driven-replanning.md`, WATCH disposition), the
README index row, the inventory note, and the harness module
(`packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py`) —
no production file under `packages/*/src` is touched by the leaf.
