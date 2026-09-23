---
inventory-delta:
  packages/maistro-core/tests: -239
---
# Issue 1154

Added `test_retired_executor.py` to pin the public-surface retirement: `maistro.graph`
and `maistro.graph.executor` no longer expose `run_graph` or `GraphRun`, the retired
lifecycle event factories are absent from `maistro.graph.events`, the retired `NodeRun`
implementation is absent from `maistro.graph.node`, and the deleted
`maistro.graph.run` and the unused pre-durable `maistro.graph.strategy` modules
cannot be imported. Removed the pre-durable `graph.phases` lifecycle module, the
direct `NodeRun.execute` fixture and the unused
pre-durable strategy fixtures; durable traversal tests remain
under `tests/graph/durable_runs/` and cover Graph-domain routing and lifecycle through
canonical Run/NodeRun/Attempt evidence. The chat-to-Graph integration fixture now
stops at classification/spec/spawn and explicitly does not execute physical Graph work.
The execution-lifecycle ledger no longer retains the deleted `GraphPhase`/`NodePhase`
identities, and the Vulture ledger prunes the remaining deleted node/lifecycle findings
(including the retired `testing.harness` event assertions). The same scan banked the
19 identities the retirement unmasked (former `run_graph` name matches such as
`parallel_generations` plus the pre-durable scout/strategy/backoff call surfaces that
the reachability ledger already holds for #44/#63 wiring); those bankings still need
the trusted-base grants per the ratchet's two-merge rule.

## Independent verification (2ba0485048d6, develop base 8bb344e32)

Re-derived from the issue and re-executed: `tests/graph/` 1091 passed / 79 skipped
(includes `test_retired_executor.py`); `tests/testing/` + `tests/orchestrator/waves/`
+ `tests/integration/test_chat_to_graph_e2e.py` + `tests/builders/` 281 passed;
`ruff check` clean; mypy clean on `maistro.graph` + `maistro.testing`;
`check-retired-guidance.py`, `check-execution-lifecycles.py`,
`check-convergence-matrix.py`, `check-suite-inventory.py` all exit 0;
`git diff --check` clean (dag.py markers resolved). Physical Graph entries all cross
`durable_runs`: master.py creates the Run then calls `run_durable_graph`;
hive-conductor `graph_runner.execute_dag` delegates to `canonical_dag_runner`;
maistro-server touches only `graph.concurrency`. `check-vulture-baseline.py` exit 1
is pre-existing at the develop base (identical terminal state in an isolated clone
of 8bb344e32); this branch's delta is banked in the candidate ledger with owner and
issue attribution (`parallel_generations`, #1154) and the residual requires the
grants-first PR per the ratchet's two-merge rule. Stop condition respected: no
executor gained persistence; `GraphRun` is retired outright.

## Repair pass (f9daace05 + this commit)

Vulture attribution was re-derived exactly (gate logic run in-process against both
this tree and an isolated clone of the develop base, full scans, not the truncated
human output). Findings and repair:

- The branch still added 4 unauthorized keys vs the trusted base
  (`graph/types.py`: `lint_errors`, `type_errors`, `tool_evaluation`,
  `pass_rate`) — the retired pre-durable `node.py` reviewer prompt
  (develop `node.py:164-169`) was their last reader, so deleting the executor
  orphaned the legacy `ToolEvaluation` telemetry model. Removed the dead model,
  the `GraphBlackboard.tool_evaluation` field and the `maistro.graph` re-exports;
  no production or test consumer existed (repo-wide grep).
- The same deletion class orphaned `TaskResult.tests_failed`
  (`tasks/models.py`): its last scanned usage was the deleted legacy
  `test_node.py` fixture; no producer or consumer remains in any language.
  Removed the always-null field.
- Pruned 19 candidate-ledger entries that the final scan no longer produces
  (18 stale bankings from the mid-repair `--update` — durable-path readers
  reappeared for `run_scout`/`compute_backoff`/`should_retry`/ensemble methods/
  token fields — plus `ToolEvaluation.evaluation_score`, dead with its model).
- Post-repair attribution: zero branch-only failure keys and zero branch-only
  bookkeeping keys vs the develop base; branch staleness strictly below develop's
  (897 vs 908). The gate's remaining ~806 unauthorized keys are byte-identical to
  the develop base's own failure set (gate exits 1 there too, reproduced in the
  isolated clone) and still require the grants-first PR outside this lane.

Re-validated after the repair: `ruff check .` clean; `ruff format --check .` clean
(2522 files); `mypy` clean on the canonical six-package set (709 files);
`tests/graph` + `tests/testing` + `tests/orchestrator/waves` + `tests/builders` +
`tests/integration/test_chat_to_graph_e2e.py`: 1372 passed / 79 skipped / 1 xfailed;
hive `test_graph_runner.py` 21 passed; `check-suite-inventory.py` ok for
maistro-core and hive-conductor; `check-retired-guidance.py`,
`check-execution-lifecycles.py`, `check-convergence-matrix.py`,
`check-merge-markers.py` all exit 0. No test files changed: suite inventories
unchanged. `LegacyGraphRunArchive` verified read-only (`mode=ro` URI;
`ArchivedGraphRun.resume()` raises `LegacyRunNotResumable`).

## Independent verification (f60b228bf, this lane re-run)

All claims above re-derived and re-executed at f60b228bf: `tests/graph` 1091 passed /
79 skipped (incl. `test_retired_executor.py`); `tests/testing` + `tests/resilience` +
`tests/orchestrator` + `tests/builders` + `tests/tasks` 912 passed / 1 xfailed; hive
`test_graph_runner_injection.py` + `test_evolution_canonical_graph.py` +
`test_dag_agents.py` 43 passed; `ruff check .` and `ruff format --check .` clean;
`git diff --check` clean; `check-merge-markers.py`, `check-retired-guidance.py`,
`check-execution-lifecycles.py`, `check-convergence-matrix.py`,
`check-m1-convergence-freeze.py --base 8bb344e32` all exit 0. Two-tree vulture
comparison (same interpreter, full scans of `git archive 8bb344e32` and this tree):
base 967 trusted-added keys vs head 968 — the single branch-only key is the
authorized `parallel_generations` grant; candidate staleness 952 (base) -> 937 (head),
worsened 0 / pruned 15, so the gate's exit 1 is byte-for-byte pre-existing at the
develop base and not branch-caused. Shipped Graph work crosses only
`run_durable_graph`/`run_durable_dag` (`master.py:630`, `builders/graph_executor.py:890`,
`agent_synth_dag.py:474`, `dag_registry.py`); the sole shipped `GraphRun`-named import
is the read-only `LegacyGraphRunArchive` (`mode=ro`, `resume()` raises
`LegacyRunNotResumable`). No closure keywords in the PR body or commit messages.
Stop condition re-checked: no executor gained persistence.
