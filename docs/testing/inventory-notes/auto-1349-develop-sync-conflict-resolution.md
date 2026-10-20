---
inventory-delta:
  tests/: +0
---
# auto-1349-develop-sync-conflict-resolution

Repair round for #1349 (include `previous_filename` when classifying renamed
PR files for gates-ran scope): resolved the preserved develop-sync conflict and
re-validated; no tests added or removed.

## Conflict resolved

`.github/workflows/gates-ran.yml`, "Collect changed files for pull-request
scope" step — both sides had independently implemented the #1349 rename
expansion:

- this branch: `filePaths` flatMap — `filename` first, `previous_filename`
  appended for `status === 'renamed'` entries;
- origin/develop (7d9d98fb6 lineage): `paths` flatMap — previous-first via
  `file.previous_filename ? [previous, filename] : [filename]`.

Resolution keeps this branch's `filePaths` mapping because
`test_the_collection_script_emits_both_paths_for_a_rename` (already on this
branch) pins the exact envelope, including `filename`-first order and the
no-`undefined`-leak contract; adopt develop's clarification that the #1350
3,000-file cap is measured on the API response (`files.length`), not the
rename-expanded path list; drop develop's duplicate `paths` block so no dead
binding remains in the step. Committed as merge d855627bf (parents 5c015105a,
347959625).

## Discrimination evidence (test fails against the regression it names)

Running both implementations against the test's mocked `listFiles` response:
the as-merged script produces the pinned envelope
`['docs/a.md', 'packages/maistro-core/a.py', 'tools/b.txt', 'c.md']`; the
develop-side previous-first variant produces
`['packages/maistro-core/a.py', 'docs/a.md', ...]` and fails the pinned
envelope — the test discriminates the two orderings, so keeping HEAD's mapping
is load-bearing, not cosmetic.

## Validation executed at d855627bf

- `uv run pytest tests/test_check_gates_ran.py -x -q` — 49 passed (includes
  the three #1349 tests; node present, none skipped);
- `uv run pytest tests/test_pr_scope_policy_parity.py
  tests/test_ci_merge_group_scope.py tests/test_check_integration_scope.py -q`
  — 52 passed;
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0, 1326 reviewed
  identities match the ledger (no ledger amendment needed);
- `uv run ruff check .` and `uv run ruff format --check .` — pass;
- `uv run python scripts/check-suite-inventory.py` — 17 suites match;
- YAML parse of gates-ran.yml / ci.yml / integration-scope.yml — OK;
- `uv run pytest tests/migrations/test_migration_chain.py -q` — 17 skipped
  (live-Postgres gated; content came from green origin/develop).
