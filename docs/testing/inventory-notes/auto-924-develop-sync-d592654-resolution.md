---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-924-develop-sync-d592654-resolution

Repair round for #924 ([RESEARCH M8-C5] provenance-, trust-, and
uncertainty-aware memory selection and write suppression): resolved the
develop-sync conflict preserved in the worktree and re-validated at the
merged head; no tests added or removed by this round (the leaf's own +52
delta is recorded in `924-m8c5-trust-memory-harness.md`).

## Conflict resolved

The worktree carried an in-progress `git merge d592654ac` (origin/develop;
MERGE_HEAD confirmed, fetch showed origin/develop still at d592654ac) with
`docs/research/README.md` unmerged — both sides appended a row at the same
position in the "Research note index" table tail:

- this branch (33798900f): row for `924 — provenance-, trust-, and
  uncertainty-aware memory selection and write suppression` (M8-C5 leaf,
  epic #901, WATCH);
- origin/develop (d592654ac): row for `926 — automatic canonical Graph
  synthesis from Goals` (M8-D2 leaf, epic #903, WATCH).

Resolution keeps both rows in numeric order (923, 924, 926, 929, 930); #924
stays WATCH so no disposition-count paragraph changes. All other develop
changes (the #926/#934/#966 research and pack-contract artifacts, the fleet
benchmark, `quality/workflow-inventory.json`,
`scripts/check-ratchet-provenance.py`,
`scripts/extension_lifecycle_proof.py`) auto-merged and are committed as
merge bd5dc27ac (parents 33798900f, d592654ac). Working tree clean after
the commit; the merged tree contains exactly the changes the preserved
worktree had staged (verified: merge diff equals the pre-commit staged set).

## Ledger integrity through the merge

The branch changed **no** file under `quality/` or `docs/testing/inventory/`
on its side of the merge, so the auto-merge reduces to develop's side for
every such file that differs. Post-merge check per the repo rule:
`git diff origin/develop HEAD -- quality/ docs/testing/inventory/` is
**empty** — HEAD is byte-equal to origin/develop for all six tracked
quality/inventory files including `vulture-baseline.json` (a multiset;
compared with `--numstat`, 0 differing rows, so no intentional duplicates
were dropped) and `inventory/baseline.json` (which now records develop's
own suite counts for the tests develop added).

## Re-validation at the merged head (bd5dc27ac)

- `uv sync --locked --extra dev`; `uv run ruff check .` → all checks
  passed; `uv run ruff format --check .` → 3233 files already formatted.
- `uv run pytest
  packages/maistro-core/tests/memory/test_m8c5_trust_aware_memory_research.py
  -q` → 52 passed (the #924 deliverable harness).
- `uv run pytest packages/maistro-core/tests -q` → 15059 passed, 1030
  skipped, 3 xfailed, **2 failed** — both failures are pre-existing local
  environment brittleness, not introduced by this round:
  `test_cli_certification.py::test_certify_refuses_a_malformed_signing_key`
  and `test_cli_compat.py::test_compat_preflight_rejects_unreadable_input`
  assert unwrapped substrings of Rich-wrapped console output
  (`cli/_extensions.py:331`); the wrap point depends on the pytest tmp
  path length, which grows with this machine's `/tmp/pytest-of-dev/pytest-N`
  counter. Re-running both tests at the **pre-merge starting head
  33798900f** in this same environment reproduces the identical two
  failures, and CI (fresh runners, short tmp paths) is green on the same
  assertions. No product or test file under these paths was touched by
  this branch or by develop's delta merged here.
- Merge-touched test files: `uv run pytest
  packages/maistro-core/tests/extensions/test_pack_contracts.py
  packages/maistro-core/tests/graph/test_m8d2_graph_synthesis_research.py
  packages/maistro-core/tests/ontology/test_rubric_model.py -q` → 167
  passed; `uv run pytest tests/test_bench_fleet_routing.py -q` → 48 passed.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests` → ok (16094 unique identities, 0
  duplicates); full `check-suite-inventory.py` → ok, 17 suites.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI-exact arguments):
  1323 reviewed identities → 1323 findings, 0 unbanked (baseline evaluated
  against base d592654ac).
- `uv run python scripts/check-ratchet-provenance.py` → OK (0 lifecycle
  violations, 53 quality-JSON consumers with provenance);
  `uv run python scripts/check-shipped-surface-truth.py` → OK;
  `uv run python scripts/check-doc-links.py` → 2013 files scanned, 0
  broken relative links (covers the README conflict resolution).
