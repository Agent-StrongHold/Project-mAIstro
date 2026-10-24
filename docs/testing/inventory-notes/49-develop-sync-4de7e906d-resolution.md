---
inventory-delta:
  packages/maistro-core/tests: -10
---

# auto-49 develop-sync resolution at base 4de7e906d (issue #49)

The develop sync (merge of `origin/develop` at `4de7e906d` into `auto-49`)
brought PR #2177 (`7f8683be2`, issue #1068): the shipped `maistro builders`
interactive path now enters through `maistro.builders.interactive`
(`BuildersExecutionSpine`), and develop independently carries the #1067
canonical-vs-legacy parity fixes this branch had ported at `0b53a9591`. The
merge resolution adopts develop's interactive spine as the one shipped CLI
authority and retires this branch's duplicate `builders/cli_execution.py`
seam. Two of this branch's earlier deltas therefore no longer describe the
merged tree; this note cancels them, per the same convention as
`auto-891-develop-sync-inventory-reconciliation.md`.

- `-9` cancels `49-1067-parity-port.md` (+9): all nine node IDs
  (`builders/test_canonical_execution.py` ×8,
  `graph/durable_runs/test_executor_gaps.py` ×1) exist byte-identical on
  develop tip — landed there through the #1067/#1068 reconciliation — so
  develop's ledger already counts them, and the merged tree held the delta
  twice. Verified: `git diff 0ef6a3d64 origin/develop --` on both files shows
  only this branch's docstring/comment annotations; every `def test_` name is
  present on both sides.
- `-1` cancels the `test_interactive_turn_runner_is_inside_canonical_run`
  half of `49-builders-canonical-cutover.md` (+2): its module
  `builders/cli_execution.py` and `tests/builders/test_cli_execution.py` were
  removed in this merge resolution because develop's `builders/interactive.py`
  is the shipped CLI delegation path (TUI → `BuildersExecutionSpine` →
  `CanonicalInteractiveTurnExecutor` → `CanonicalGraphPipelineExecutor`) and
  keeping a second in-memory CLI seam would recreate exactly the
  independently-valid-executor state issue #49 forbids. The turn-admission
  property that test asserted is covered on develop by
  `tests/builders/test_interactive_execution.py` (12 nodes), already in
  develop's ledger.

The surviving half of `49-builders-canonical-cutover.md` (+1) —
`test_builder_pipeline_production_composition_uses_canonical_run_store` in
`tests/builders/test_builder_pipeline.py` — is unique to this branch and
remains counted there.

Post-reconciliation state: expected `packages/maistro-core/tests` = 17783 =
collected 17783 (develop tip collects 17782 in the same environment; the
+1 is the branch-unique composition test).
