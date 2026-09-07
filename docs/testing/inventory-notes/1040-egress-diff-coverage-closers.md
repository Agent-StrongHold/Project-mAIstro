---
inventory-delta:
  packages/maistro-core/tests: +15
---

# Diff-coverage closers for the governed model egress (PR #1040 / m1/56)

CI diff coverage at head `9ad61fa5` flagged four files below the branch floor.
These fifteen node IDs are focused tests against exactly the named uncovered
lines/arcs — nothing else in the suites moves.

**+5** in `test_invocation_usage_validation.py` (new) close the three
`InvocationUsage._validate_usage` raise lines (`invocation.py` 90/92/94): blank
`units`, negative `input_units`, negative `output_units`, negative `cost_cents`,
plus the accepting direction (zero cost is measured; absence stays `None`).

**+3** in `test_model_chat_egress.py` close the partial arcs at
`model_chat.py` 56/161/169, each exercised both ways: a non-dict gateway body
yields no usage while a dict body still maps; an `Unavailable` resolver result
returns untracked from `tracked_resolve` and refuses with
`CapabilityUnavailable` before any HTTP; `usage_from` with no tracked provider
returns `None`, and after `tracked_resolve` records a gateway handle it maps
through `_gateway_usage`.

**+5** in `test_llm_gateway_branches.py` (new) close the partial arcs at
`llm_gateway.py` 113/128/145/147: `tools` merge into the payload only when
present, a non-object JSON body refuses with `RuntimeError`, and a foreign
provider handle or raw-dict request refuses the seam with `TypeError`.

**+2** in `test_sync_kinds_branch_coverage.py` (parametrized `""` and `"   "`)
close the refusing arc at `llm_summarize.py` 128: a blank `binding_id` raises
`BindingNotFound` before any egress or HTTP. The resolving direction was
already covered by every governed `llm.summarize` test in that file.

Local scoped measurement after the change: `invocation.py` 94% lines (the
three named lines gone from the miss list), `model_chat.py` and
`llm_gateway.py` 100% lines and 100% branch arcs, `llm_summarize.py` 100%
lines and 100% of its 6 branch arcs.
