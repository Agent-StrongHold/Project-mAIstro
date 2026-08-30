---
inventory-delta:
  tests/: +13
---

# #55 direct-effect inventory analyzer coverage

Adds thirteen focused root-suite cases for the AST direct-effect analyzer: positive model, typed-tool, MCP/provider-boundary detection; import-vs-usage behavior; stable identities; bidirectional inventory reconciliation; environment-default model endpoints; non-`src` shipped package Python; and the SQL/unrelated-HTTP/`maistro.events.invocations.InvocationStore` false-positive cases called out by #55.

The production scan covers shipped Python across `packages/**`, excluding test trees and `test_*.py`. `packages/hive-conductor/run_hill_climb.py` is the one explicit package-tree exclusion because it is a manually invoked developer hill-climb driver rather than an application/runtime product path. Standalone operator/developer utilities outside `packages/**`, including `scripts/openrouter_rpm_pacer.py`, remain outside this product-path ratchet by construction. Non-Python developer wrappers such as `packages/hive-conductor/hill-climb-ui.sh` are outside the AST analyzer's language scope.

The checked-in baseline contains 60 actual AST call sites: 44 model effects, 7 tool effects, 3 MCP effects, 4 harness/provider lifecycle effects, and 2 canonical capabilities Invocation calls. Every site has a reviewed disposition, owner, and rationale. Canonical Invocation and terminal provider/harness boundaries are intentional infrastructure; shipped bypass callers are assigned to #56, #57, or #59 for migration without implementing that wiring in this slice.

`check-model-egress.py` imports the analyzer statically so the reachability graph sees the real quality-gate dependency. The corresponding Repo tooling row in the convergence matrix is refreshed to `18/57`: 39 workflow-rooted tooling scripts and 18 intentionally unrooted scripts.
