---
inventory-delta:
  packages/maistro-rsi/tests: +6
---
# Issue #890 — CrossHair symbolic-execution prototype (+6)

`packages/maistro-rsi/tests` gains
`test_m8a_crosshair_research.py` (+6 node IDs): the M8-A10 leaf's deliverable
gate plus a running prototype of the technique under study. Unlike the sibling
#918 harness (dependency-free miniature), the tool here is real and
deterministic, so the module drives the actual `crosshair check` engine
(subprocess, `sys.executable -m crosshair`) against real maistro seams:
`expand_scopes`, `normalized_daily_budget`, and the `BudgetRule` policy rule.

The six checks pin: the research note and its INCUBATE disposition exist with
the three evidence classes recorded; `crosshair-tool` is declared in
`[dependency-groups].dev` and the shadowing legacy `crosshair` distribution
stays out; the 6-contract CI profile passes against unmodified production
(~20 s, the module's dominant cost); the engine genuinely analyzes (exact
minimal counterexample text asserted on a deliberately broken toy contract);
the documented budget-dependent false positive is reported AND disproven by
concrete replay of the exact printed input; and the E1 applicability datum
(seven production modules import cleanly yet contain no checkable functions)
holds for every scanned module.

No other suite count moved. The dependency change is dev-group only
(`crosshair-tool>=0.0.111` added; the mis-pinned legacy `crosshair` package
removed before it could shadow the real tool's import package); runtime code,
product code, and every other suite are untouched. Full experiment record:
`docs/research/890-crosshair-symbolic-execution-pure-invariants.md`.
