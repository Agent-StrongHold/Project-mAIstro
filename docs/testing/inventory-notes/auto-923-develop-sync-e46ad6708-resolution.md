---
inventory-delta:
  tests/: +0
---
# auto-923: develop-sync salvage — resolve the preserved origin/develop merge (e46ad6708)

Repair round for issue #923 (M8-C4 episodic-to-semantic consolidation, temporal
contradiction handling, forgetting): the worktree sat at declared head
`88d0663145` with a merge of `origin/develop` (`e46ad6708`) in progress and
exactly one unmerged path. This round resolved the conflict, committed the
merge (`0d360ddf8`), and re-ran the validation battery at the merged head. No
tests were added or removed by the resolution, so there is no suite-count
delta; this note records the reconciliation and evidence.

## What the conflict resolution did

- `docs/research/README.md` note index: kept **both** rows — develop's
  922 M8-C3 adaptive-context-budgeting row and the branch's 923 M8-C4
  consolidation row — family-ordered 922 then 923 (consistent with the
  table's M8-C ordering 920, 921, 922, 923). Verified after resolution:
  21 index rows = merge-base 17 + the branch's 923 row + develop's three
  additions; zero duplicates (`sort | uniq -d` empty);
  `scripts/check-doc-links.py` passes (0 broken relative links).
- `docs/README.md` research-count line auto-resolved to the branch's bump
  (18 → 19); develop never touched the line (its own tip still reads 18 with
  20 index rows and 28 note files), so it was left as-is, matching the
  auto-777 precedent (`229990635`, which merged the same develop tip and did
  not modify `docs/README.md`).
- No quality ledger rows were lost: `quality/vulture-baseline.json` is
  identical (as a multiset) across both parents and the merge result;
  `quality/ratchet-authorizations.json` likewise unchanged.

## Validation at the merged head (0d360ddf8)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 3192 files
  formatted.
- `uv run pytest packages/maistro-core/tests/memory -q` — 1012 passed,
  11 skipped (includes the M8-C4 research suite, 50 checks).
- `uv run pytest packages/maistro-rsi/tests/test_m8c3_context_budgeting_research.py
  packages/maistro-rsi/tests/test_m8e2_historical_calibration_research.py
  packages/maistro-rsi/tests/test_m8d_planning_strategies_research.py
  packages/maistro-rsi/tests/test_m8a_crosshair_research.py
  packages/maistro-core/tests/research
  packages/maistro-core/tests/tasks/test_m8a8_replay_equivalence_research.py -q`
  — 222 passed, 1 skipped (the develop-introduced research suites that now
  share the tree).
- `uv run python scripts/check-doc-links.py` — 0 broken links.
- `uv run python scripts/check-suite-inventory.py` — ok: 17 suites match the
  recorded inventory (29913 unique test identities, 0 duplicates).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1326 reviewed identities,
  1326 findings, pass (CI-exact arguments).

## Second develop sync: resolve the preserved origin/develop merge (8fbbbfb91)

A later repair round for the same issue inherited the worktree with a second
merge of `origin/develop` — now advanced from `e46ad6708` to `8fbbbfb91` —
in progress with two unmerged paths (develop had since touched the lines the
first resolution owned). Resolution committed as `89c3e99a9`:

- `docs/research/README.md` note index: kept **both** rows — the branch's
  923 M8-C4 consolidation row (WATCH, matching the note's disposition) and
  develop's new 929 M8-D5 graph-pattern row (INCUBATE), in numeric order
  923 then 929 between the 922 and 935 rows. The following tally paragraph
  (outside the conflict) already counted both (four INCUBATE leaves
  including #929).
- `docs/README.md` research-count line: this time **both** sides had bumped
  the same line since the merge base (branch: 19, develop: 20), producing
  the conflict — and both values were stale for the merged tree (the count
  was last exact at the charter commit `5c859ab5a`, 18 notes = 18 files).
  Resolved to **32**, the exact number of markdown files in `docs/research/`
  at this merge, README included (the convention since the founding commit
  `0976bf988`, count 1 = README alone). No gate parses this column; the
  value is kept truthful for readers.
- `quality/` is byte-identical to `origin/develop` after the merge
  (`git diff --numstat origin/develop -- quality/` empty) — no ledger rows
  lost to the auto-resolve hazard.

### Validation at the merged head (89c3e99a9)

- `uv sync --locked --extra dev` — clean; `uv run ruff check .` — clean;
  `uv run ruff format --check .` — 3198 files formatted.
- `uv run pytest packages/maistro-core/tests/memory/
  test_m8c4_consolidation_temporal_forgetting_research.py -q` — 50 passed
  (the issue #923 deliverable suite).
- Develop-introduced suites re-run on the merged tree:
  `test_m8a5_differential_reference_model_research.py`,
  `test_m8a7_pg_race_harness.py`, `test_m9e_family_install.py`,
  `tests/test_bench_graph_pattern_reuse.py`,
  `tests/test_credential_authority.py`,
  `tests/test_unit_suite_execution_partition.py` — 146 passed, 9 skipped
  (Docker/pg-gated); merge-modified `test_durable_store_conformance.py`,
  `test_model_egress_container_composition.py`,
  `test_tasks_idempotency.py` — 105 passed, 43 skipped.
- `uv run python scripts/check-doc-links.py` — 0 broken relative links.
- `uv run python scripts/check-workflow-inventory.py` — clean, 27
  workflows dispositioned.
- `uv run python scripts/check-suite-inventory.py` (CI-exact, all suites) —
  ok: 17 suites match the recorded inventory (30011 unique test identities,
  0 duplicates, 0 byte-identical files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — 1326 reviewed
  identities, 1326 findings, 0 unclassified, pass (CI-exact arguments).
