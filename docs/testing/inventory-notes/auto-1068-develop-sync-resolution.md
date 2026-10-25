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

## Second develop sync (base `2f56be40ad`, merge `af84c28fb`)

Merged `origin/develop` tip `2f56be40a` (20 commits over the prior base
`ab8b3737f`). No conflicts: the only file both sides touched was
`docs/architecture/CONVERGENCE-MATRIX.md`, auto-merged with the Builders rows
intact. Develop's new range does not touch `maistro.builders`/`maistro.cli`
builders surfaces.

This round also lands the salvage from the rate-limit-interrupted job
`51f586cb` (uncommitted diff against `fd88802ae`, backed up before work):
`resolve_local_operator_principal` plus actor-principal plumbing through
`BuildersExecutionSpine`/`CanonicalInteractiveTurnExecutor`. Evidence it was
required, not cosmetic: at `fd88802ae`,
`test_cli_spine_retains_run_identity_across_reopen` fails with
`ValueError: actor_principal_id is required` (develop's #364/#1841 store
boundary; `maistro/runs/sqlite_store.py` enforces it independently of the
`maistro.runs.store` import the builders test conftest monkeypatches), so the
shipped SQLite-backed TUI spine could not admit any turn. The in-memory
executor tests passed only through the conftest's
`DEFAULT_TEST_ACTOR_PRINCIPAL_ID` substitution. The spine now always admits
with a resolved local-operator identity.

### Gate reconciliations on the merged candidate

- Vulture (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`):
  the TUI now calls `BuilderSession.add_user`, so
  `maistro_bootstrap/builders/session.py::unused method 'add_user'` is no
  longer a finding and was pruned from `quality/vulture-baseline.json`
  (1322 -> 1321 reviewed identities), as the gate's own output instructs for
  fixed debt.
- Suite inventory: this branch records `packages/maistro-core/tests: +5`
  (3 interactive-execution tests, 1 CLI architecture test, 1 principal
  precedence unit test). Pure develop tip `2f56be40a` itself carries
  `tests/: +1` drift (expected 5260, collected 5261), reproduced in an
  isolated worktree at that revision; identical on this branch, inherited,
  and not repairable from this lane.

### Validation on the merged candidate (second sync)

`ruff check .` and `ruff format --check .` clean; `mypy packages/maistro-core/src`
clean (790 files); builders+cli+runs 1689 passed / 290 skipped / 1 xfailed;
`tests/cross_product_parity` 12 passed (development mode, ci.yml arguments);
`check-execution-lifecycles.py`, `check-reachability-provenance.py`,
`check-reachability-dispositions-provenance.py`,
`check-contract-markers-provenance.py`, and the vulture gate all OK against
base `2f56be40ad`.
