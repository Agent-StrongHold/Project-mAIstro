---
inventory-delta:
  tests/: +0
---
# auto-926-develop-sync-1c55afe51-resolution

Repair round for #926 ([RESEARCH M8-D2] automatic canonical Graph synthesis
from Goals and constraints): resolved the preserved develop-sync conflict and
re-validated at the merged head; no tests added or removed by this round (the
branch's own +41 delta is recorded in
`926-m8d2-graph-synthesis-harness.md`).

## Conflict resolved

`docs/research/README.md`, "Research note index" table tail — both sides
appended rows at the same position:

- this branch (3dd88c316): row for `926 — automatic canonical Graph synthesis
  from Goals` (M8-D2 leaf, epic #903, WATCH);
- origin/develop (1c55afe51): rows for `900` (M8-B epic family, INCUBATE),
  `918` (M8-A leaf, WATCH), `923` (M8-C4 leaf, WATCH), `929` (M8-D5 leaf,
  INCUBATE), `930` (M8-E1 leaf, WATCH), plus the matching INCUBATE-count
  paragraph update ("four are INCUBATE …").

Resolution keeps all six rows in the table's numeric order (923, 926, 929,
930) — the two epic-#903 rows (926, 929) end up adjacent. #926 stays WATCH,
so develop's paragraph count remains correct. Committed as merge 9a2e7d42c
(parents 3dd88c316, 1c55afe51).

## Ledger integrity through the merge

The branch changed **no** file under `quality/` or `docs/testing/inventory/`
relative to the merge base e46ad6708 (`git diff --stat <base> HEAD -- …` is
empty), so the auto-merge correctly reduces to develop's side for all six
files that differ (merged worktree byte-equal to 1c55afe51 for
`vulture-baseline.json`, `route-permissions.json`,
`shipped-surface-truth.json`, `workflow-inventory.json`,
`frontend-typed-client-baseline.json`, `inventory/baseline.json`; develop's
own edits — including its 3-row vulture debt removal — carry over intact and
no rows were lost from either side).

## Re-validation at the merged head (9a2e7d42c)

- `uv sync --locked --extra dev`, `uv run ruff check .` (pass),
  `uv run ruff format --check .` (3221 files already formatted) — pass.
- `uv run pytest
  packages/maistro-core/tests/graph/test_m8d2_graph_synthesis_research.py -q`
  → 41 passed, 41 collected (frozen-report determinism cases included).
- Full graph suite: `uv run pytest packages/maistro-core/tests/graph -q` →
  1949 passed, 125 skipped (develop's merge added two graph tests; the seams
  the harness imports are unaffected).
- `uv run python scripts/check-suite-inventory.py` → ok, 17 suites, 30424
  unique identities, 0 duplicates.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact arguments):
  1323 reviewed identities → 1323 findings, 0 unbanked (baseline evaluated
  against base 1c55afe51).
- `uv run python scripts/check-ratchet-provenance.py` → OK (0 lifecycle
  violations, 52 quality-JSON consumers with provenance).
- `uv run python scripts/check-shipped-surface-truth.py` → OK.

The branch's delta vs origin/develop remains the four additive research
surfaces: `docs/research/926-graph-synthesis-from-goals.md`, the README index
row, `docs/testing/inventory-notes/926-m8d2-graph-synthesis-harness.md`, and
`packages/maistro-core/tests/graph/test_m8d2_graph_synthesis_research.py` —
no production file under `packages/*/src` is touched.
