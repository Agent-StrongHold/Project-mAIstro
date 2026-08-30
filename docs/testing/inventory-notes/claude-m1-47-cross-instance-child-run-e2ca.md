---
inventory-delta:
  packages/maistro-core/tests: +3
---
# cross-instance delegation child Runs

Three new tests in `tests/graph/nodes/test_agent_delegate_remote_child_run.py`
closing #47's fifth criterion — *"at least one local and one remote delegation
path has E2E coverage"*. The in-process path already had child-Run coverage;
`_dispatch_cross_instance` filed a child Run that no test ever read back, so
"delegation creates a child Run" was proven for one of the two ways delegation
happens. Purely additive; no production code changed.

- a cross-instance delegation creates a child of the delegating Run *and*
  NodeRun, filed in the parent's Workspace and Project;
- its provenance names the peer, the A2A `task_id`, the mode and both agents —
  the receipt stays a receipt rather than becoming the work's only identity;
- a peer that declines files no child Run, since nothing was admitted and there
  is no execution to give an identity to — the same rule the in-process
  rejection already followed.
