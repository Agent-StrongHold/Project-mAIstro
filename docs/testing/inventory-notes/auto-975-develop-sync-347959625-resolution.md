# auto-975: develop-sync salvage — resolve the blocked origin/develop merge (347959625)

Salvage of issue #975 (M9-H3 extension certification): the worktree sat at
HEAD `25e04d2cb4a9` with a merge of `origin/develop` (`34795962548a`) in
progress and exactly two unmerged paths. This round resolved both conflicts,
committed the merge (`35ef52ed8ba6`), and re-ran the validation battery at the
merged head. No tests were added or removed by the resolution, so there is no
suite-count delta; this note records the reconciliation and evidence.

## What the conflict resolution did

- `packages/maistro-core/src/maistro/extensions/__init__.py`: kept **both**
  docstring bullets — the branch's M9-H3 certification (#975) bullet and
  develop's M9-I2 metering (#977) bullet — and unioned the closing
  no-code-execution sentence ("…certification and metering all operate on
  bytes, declarations, identity and amounts alone"). The import blocks and
  `__all__` had auto-merged to carry both surfaces (certification + metering);
  also dropped the stale duplicate `"ROOT_REQUEST_ORIGIN"` row that HEAD's
  `__all__` carried (set-based consumers never noticed; the surface-union
  test still passes).
- `scripts/ci_merge_group_scope.py`: the only conflict was the wheel-imports
  firing condition, which both sides had made semantically identical
  (develop's #1351 `PATH_SCOPED_EVENTS` policy — merge_group and pull_request
  both path-scoped — rides in the already-merged regions). Kept the branch's
  compact `path in (...)` form; `tests/test_ci_merge_group_scope.py`,
  `test_pr_scope_policy_parity.py`, `test_ci_specialized_scope_wiring.py`,
  `test_ci_merge_group_outputs.py` and `test_check_integration_scope.py`
  (77 tests) pass at the merged head.
- No quality ledger rows were lost: `quality/vulture-baseline.json` (1326
  identities), radon (137 blocks) and reachability gates all pass at the
  merged head with CI-exact arguments.

## Validation at the merged head (35ef52ed8ba6)

- `uv run ruff check .` — clean; `uv run ruff format --check .` — 3170 files formatted.
- `uv run pytest packages/maistro-core/tests/extensions -q` — 853 passed
  (certification #975 + metering #977 + surface-union + lifecycle-proof suites).
- `uv run pytest packages/maistro-core/tests/{capabilities,runs,scheduling,graph/durable_runs} -q`
  — 2818 passed, 362 skipped (PG-dependent skips, no server in this run).
- `uv run pytest packages/hive-conductor/backend/tests/test_scheduler_{bounded_tick,canonical_admission,canonical_due}.py -q`
  — 34 passed, 14 skipped.
- `uv run pytest tests/migrations -q` — 36 passed, 121 skipped (renumbered
  chain: `041_canonical_run_effect_claim` → `034`, `043`/`045` deletions hold).
- `uv run mypy packages/maistro-core/src` — no issues in 771 source files.
- Gate scripts: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (CI-exact), `check-reachability.py`,
  `check-suite-inventory.py` (17 suites match), `check-radon-baseline.py`,
  `check_enumerations.py`, `check-workspace-retirement.py`,
  `check-route-permissions.py`, `check-principal-identity.py` — all exit 0.
- CI-evaluator unit tests (`test_check_gates_ran.py`,
  `test_gates_ran_merge_group_scope.py`, `test_gates_ran_publisher_contract.py`,
  `test_codeql_scan_scope.py`, `test_devskim_scan_scope.py`,
  `test_ci_merge_group_outputs.py`) — 90 passed.
