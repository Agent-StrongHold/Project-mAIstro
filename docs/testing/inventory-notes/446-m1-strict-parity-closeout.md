---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  tests/: +1
---

# M1 strict parity closeout

Issue #446 keeps the #459 closeout contract fail-closed and executes the
Builders, scheduler, and Evolve producer paths against canonical Run,
NodeRun, and Attempt stores. Normal parity development may record named
dependency blockers, but `M1_STRICT_CLOSEOUT=1` rejects blocker-only passes.
CI registers that strict invocation as a dedicated step, so it cannot report
M1 parity evidence while a required producer or observer scenario abstains.

## 2026-09 repair pass (no inventory delta; same node counts)

The closeout-safety audit's three repair findings, addressed without adding
or removing collected test nodes:

- **Legacy Builders executor retired from the shipped package.** The
  pre-#734 `GraphPipelineExecutor` (with `_Outcome`/`_GateRoute`) moved
  verbatim into `packages/maistro-core/tests/builders/conftest.py` as a
  frozen parity oracle exposed through the `legacy_graph_executor` fixture.
  The shipped `maistro.builders.graph_executor` module now carries only the
  canonical adapter, so direct construction of the evidence-free executor
  is an `ImportError`, not a silent second authority.
- **Parity Scenario 1 consumes the shipped composition.** The TUI's
  pipeline construction was extracted textually-free into
  `maistro.builders.session_composition` (`open_session_spine` /
  `build_session_pipeline` / `TurnDispatcher`); the TUI and the parity
  scenario both call it, so the closeout executes the shipped composition
  rather than a synthetic `BuilderPipeline` built beside it. Only the
  model-call boundary (`TurnRunner.execute_turn`) is deterministic in the
  test.
- **Reachability ledger pruned.** The 11 newly reachable `maistro.builders.*`
  modules left `quality/reachability-baseline.json`, and the
  `builders-competing-executor` RETIRE disposition plus the reachable
  entries of `builders-domain-logic` were pruned/trimmed in
  `quality/reachability-dispositions.json`, so the census tracks the
  converged state instead of absorbing it silently.
