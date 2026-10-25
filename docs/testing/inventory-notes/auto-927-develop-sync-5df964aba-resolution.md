---
inventory-delta:
  packages/maistro-rsi/tests: +0
---
# auto-927-develop-sync-5df964aba-resolution

Repair round for #927 ([RESEARCH M8-D3] observation-driven replanning after
failures, surprises, and changed constraints): resolved the preserved
develop-sync conflict against origin/develop `5df964aba`, then merged the one
newer develop commit (`007f09fbd`, owner-only backup destinations) cleanly on
top; re-validated at the merged head. No tests added or removed by this
round.

## Conflict resolved

`docs/research/README.md`, "Research note index" table — both sides appended
a row at the same position (after `924 — provenance-, trust-, and
uncertainty-aware memory selection`):

- this branch (8334ce586): row for `927 — observation-driven replanning`
  (M8-D3 leaf, WATCH);
- origin/develop (5df964aba): row for `928 — bounded beam/tree/MCTS-style
  plan search` (M8-D4, INCUBATE).

Resolution keeps both rows in the table's numeric order (927, 928); both
notes exist in-tree. The paragraph below the table ("six are INCUBATE …
plan-search leaf #928, and graph-pattern reuse leaf #929") remains correct
with both rows present: #927 is WATCH and adds no INCUBATE. Committed as
merge 0b923bb01 (parents 8334ce586, 5df964aba), followed by the clean merge
f56dd381d of 007f09fbd.

## Ledger integrity through the merges

`git diff --numstat origin/develop -- quality/` is empty at the merged head:
every `quality/*.json` is byte-identical to origin/develop, so no
per-identity ledger lost rows.

## Re-validation at the merged head (f56dd381d)

- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3260 files
  already formatted.
- `uv run pytest
  packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py -q`
  → 57 passed (the #927 harness; matches the recorded +57 delta).
- Full `uv run pytest packages/maistro-rsi/tests -q` → 1624 passed, 4 skipped
  (absorbs the develop-side test additions since the last sync).
- `uv run python scripts/check-suite-inventory.py` → all 17 suites match the
  recorded inventory (30909 unique node IDs).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact arguments) →
  1323 reviewed identities → 1323 findings, 0 unbanked; exit 0.
- `uv run python scripts/check-ratchet-provenance.py` → 0 lifecycle
  violations; `uv run python scripts/check-workflow-inventory.py` → clean
  (28 workflows); `uv run python scripts/check-doc-links.py` → every relative
  markdown link resolves; `uv run python scripts/check-citation-status.py` →
  OK; `uv run python scripts/check-merge-markers.py` → no conflict markers in
  any tracked file; `uv run python scripts/check-backlog-consistency.py` →
  OK (167 items).
- Meaningfulness spot-check (this round, executed against a temp copy, the
  tree untouched): reverting the harness import guard's `ast.ImportFrom`
  handling to the naive alias form Codex flagged on PR #2074 fails exactly
  `test_import_guard_covers_every_import_form` (`from maistro.graph import
  executor` no longer attributed to root `maistro`), confirming the
  hardening-round self-test catches its named regression at this head.

The #927 leaf delta vs origin/develop remains the research note
(`docs/research/927-observation-driven-replanning.md`, WATCH disposition), the
README index row, the inventory note, and the harness module
(`packages/maistro-rsi/tests/test_m8d3_replanning_benchmark_research.py`) —
no production file under `packages/*/src` is touched by the leaf.
