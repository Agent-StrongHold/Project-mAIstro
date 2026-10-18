---
inventory-delta:
  tests/: +0
---

# auto-1068 develop-sync conflict resolution (issue #1068)

Merged `origin/develop` (tip `48071677a`, 663 commits) into `auto-1068`
(`6e74ff249` feat(builders): admit interactive turns on canonical runs) and
resolved the two preserved conflicts in place. No tests were added or removed
by the resolution itself; the merge brings develop's evolved Builders tests.

## Conflict resolution

Both conflicted files had semantic (not just textual) auto-merge hazards:

- `packages/maistro-core/src/maistro/builders/graph_executor.py` — took
  develop's side wholesale: the legacy parity oracle is now the private
  `_LegacyGraphPipelineExecutor` (develop's `test_canonical_execution.py`
  asserts the public `GraphPipelineExecutor` name is gone), and
  `CanonicalGraphPipelineExecutor` gained optional stores with a
  `_ensure_default_stores()` fallback, `actor_principal_id`, gate
  revise-target defaulting to the gate node, and a budget-exhausted status.
  This branch's hunks (public oracle name, lazy default stores inside
  `BuilderPipeline`) are superseded by strictly stronger develop equivalents.
- `packages/maistro-core/src/maistro/builders/pipeline.py` — took develop's
  typed `BuilderPipeline` constructor (`RunStore`/`DurableRunStore` types,
  `workspace_id: str | None`, `actor_principal_id`), its pre-built
  `_canonical_executor` attribute, and the invalid-graph receipt before
  canonical admission. Removed two auto-merge leftovers this resolution
  identified: a duplicated `canonical_run_id` field on `PipelineRun` and a
  `_canonical_executor` method/attribute name collision (the instance
  attribute would have shadowed the method).

## Preserved branch-unique #1068 work

- `packages/maistro-core/src/maistro/builders/interactive.py` — the canonical
  interactive-turn adapter (`CanonicalInteractiveTurnExecutor`,
  `BuildersExecutionSpine`, `_ReActDispatcher`); develop has no equivalent.
- `packages/maistro-core/src/maistro/cli/_builders_tui.py` — this branch's
  richer TUI (canonical run-id bar, `record_session_run` correlation).
- `packages/maistro-core/tests/builders/test_interactive_execution.py` and the
  shipped-TUI canonical-admission guard in
  `packages/maistro-core/tests/cli/test_builders.py`.

## Validation evidence (post-merge head `4698be48f`)

- `uv run pytest packages/maistro-core/tests/builders packages/maistro-core/tests/cli -q`
  -> 303 passed, 1 xfailed.
- `uv run ruff check .` and `uv run ruff format --check .` -> clean.
- `uv run mypy packages/maistro-core/src` -> 0 issues (after installing the
  `bootstrap` extra; the earlier `maistro_bootstrap.cli` import-not-found was
  environmental, not merge-introduced).
- `scripts/check-execution-lifecycles.py`, `check-shipped-surface-truth.py`,
  `check-reachability.py`, `check-reachability-provenance.py`,
  `check-convergence-matrix.py`, `check-model-egress.py`,
  `check-lifecycle-provenance.py` -> all OK.

## Suite-inventory ledger reconciliation

The prior round's note `1068-builders-interactive-canonical-runs.md` carried a
malformed `inventory-delta:` block (prose values instead of `<suite>: <±count>`),
which made `scripts/check-suite-inventory.py` fail to parse. Fixed to the
truthful `packages/maistro-core/tests: +4` (three interactive-execution tests
plus the shipped-TUI canonical-admission guard, verified via
`git diff 4ca4afd6c 6e74ff249 -- packages/maistro-core/tests`).

Measured drift (identical on both trees, `--suite packages/maistro-core/tests`):

- pure develop tip `48071677a`: expected 10297, collected 10306 (net +9);
- merged head `4698be48f`: expected 10301, collected 10310 (net +9).

The merge adds exactly the recorded +4 tests; the residual +9 is unrecorded
drift already present on develop tip and is not repairable from an ordinary
implementation lane (ledger edits to `docs/testing/inventory/baseline.json`
are out of scope here).

## Vulture dead-code fix inherited from develop

`scripts/check-vulture-baseline.py` fails on pure develop tip `48071677a` with
exactly two never-allowlist findings: duplicated `return` statements at lines
149 and 175 of
`packages/maistro-core/tests/runs/test_retention_scope_conformance.py`
(inherited verbatim from develop's #1233 merge). This resolution removes the
two dead duplicate returns (semantically identical; 17 passed / 9 skipped on
the file) because the develop sync owns the integrated state of merged code.
The gate then proceeds past the early exit and surfaces develop's own
candidate-ledger drift (2 unrecorded hive-conductor identities, 1 stale
maistro-bootstrap identity); the affected code and `quality/vulture-baseline.json`
are byte-identical between develop tip and this merge, so that drift is purely
inherited and needs a reviewed grant this lane cannot authorize.

Residual: live configured-provider TUI turn execution and the #459 strict-mode
real CLI/TUI producer path remain environment-gated (no provider credentials
in this lane), unchanged from the prior round's findings.
