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

## Repair pass (verifier findings at 2399a55a1)

The verifier reported two findings against 2399a55a1. Both were re-derived from
scratch; one was already resolved, one was root-caused and settled further:

- `builders/dag.py` conflict markers: not present. `git diff --check` exits 0 on a
  clean tree and a marker scan of the file finds none; the repair landed in
  35b3920d9 stands.
- `check-vulture-baseline.py` exit 1: root-caused with a base-tree experiment, not
  assumed. Scanning the develop base 8bb344e32 itself (scratch worktree, empty
  probe commit, same interpreter and scan args) reproduces the failure there:
  trusted NEW=967 / stale=952 with a mirrored candidate section, versus head's
  trusted NEW=968 / stale=952 before this pass. The failure set is therefore
  byte-for-byte upstream (the develop ledger, last banked at 84d937add, does not
  match its own tree: e.g. 486 hive-conductor findings in the base scan against a
  ledger that records none), and per the ratchet's own doctrine a candidate branch
  cannot authorize it ("land a reviewed grant first"). What the branch controls
  was settled in this pass:
  - candidate ledger re-banked from a real scan (`--update`): candidate
    bookkeeping section is now empty (0 NEW / 0 stale); rule definitions
    untouched, findings lists only;
  - `GraphNodeResult.next_nodes` removed: zero producers and zero consumers
    repo-wide, and the durable executor derives successors from `graph.edges`
    (`durable_runs/executor.py::_next_nodes`), never from this field, so it is
    pre-durable traversal residue exactly like the retired executor's other
    name-matches. Its removal converts the branch's one unbanked trusted key into
    a trusted stale row (a debt fix, the ratchet-correct direction); the
    candidate row was pruned by the same `--update`.
  - Final attribution: the branch's entire trusted-section footprint vs the
    develop base is +1 NEW (the already-authorized `parallel_generations` grant)
    and +1 stale (the `next_nodes` fix); the remaining 967 NEW / 952→953 stale
    identities are the develop base's own failure set and need the grants-first
    PR outside this lane.

Re-validated after this pass: `ruff check .` clean; `ruff format --check .` clean
(2522 files); `tests/graph` + `tests/testing` 1137 passed / 79 skipped;
`tests/orchestrator` + `tests/integration/test_chat_to_graph_e2e.py` + canvas
`test_canonical_execution.py` + hive `test_graph_runner.py` 217 passed;
`check-retired-guidance.py`, `check-execution-lifecycles.py`,
`check-convergence-matrix.py` all exit 0; ledger JSON valid. No test files
changed in this pass: suite inventories unchanged.

## Independent verification (bc4f97d66, lane head after develop merge 1dea30df)

Re-derived and re-executed at the merge head: `tests/graph` 1124 passed / 79 skipped
(includes `test_retired_executor.py` and the full `tests/graph/durable_runs/` suite the
driver's check list omits); hive `test_graph_runner.py` 21 passed (driver log);
`ruff check .` + `ruff format --check .` clean (driver logs); `git diff --check
1dea30df..bc4f97d66` exit 0 (dag.py markers stay resolved); `mypy` clean on the canonical
six-package set (710 files); `check-retired-guidance.py`, `check-execution-lifecycles.py`,
`check-convergence-matrix.py`, `check-merge-markers.py` all exit 0; both suite
inventories match (driver logs). Shipped Graph work crosses only `run_durable_graph`
(`master.py:630`, `builders/graph_executor.py:890`, `dag_agents.py:213`,
`canonical_dag_runner.py:558`, `evolution_graph.py:898`, turing `execution.py:370`);
`testing/harness.py` constructs no Graph work; `quality/retired-guidance.json` records
`pre-durable-run-graph` as retired by #1154; docs retirement annotations present
(ADR-062 top note, CONVERGENCE-MATRIX rows, SPEC-070226-b624 line 41). No closure
keywords in the PR body or commit messages. Stop condition respected.

**Open finding (this head):** `scripts/check-vulture-baseline.py` exits 1 at
bc4f97d66 — candidate-ledger bookkeeping regressed in the merge: 2 stale rows for
`credential_store_v2.py` (`AgnosticCredentialStore`, `get_first_secret_by_type`; file
deleted on the develop side by f546365fa) and 2 unbanked rows
(`tests/graph/durable_runs/test_pause_reason_wakers.py:89` `pytestmark`, added by
750edd84d; hive-conductor `tests/conftest.py:62` `_isolate_credential_store`, added by
f546365fa). The d6ddd9f04 re-bank was clean for the pre-merge tree (verified: the
wakers test is absent and credential_store_v2.py still present at d6ddd9f04); the
merge changed the tree without re-banking. Repair is the doctrine-sanctioned
findings-only re-bank (`--update`) at this head; no authorization grants are involved.
The trusted-section bulk remains the develop base's own failure set (probe:
`list_confirms` exists at 1dea30df but is absent from the base ledger), needing the
grants-first PR outside this lane.
